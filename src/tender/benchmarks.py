"""Layered, isolated LangSmith experiments with deterministic reference evaluators."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from langsmith import Client, evaluate, tracing_context
from langsmith.schemas import Example

from tender.config import Settings
from tender.db import Repository
from tender.demo import seed
from tender.guardrails import assess_brief
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.providers import INTAKE_SCHEMA, PROMPT_VERSION, ModelAdapter
from tender.schemas import DomainPack, Identity, ProjectBrief
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow

ROOT = Path(__file__).resolve().parents[2]


def score_output(inputs, outputs, reference_outputs):
    """Explicit metrics; missing/failed outputs always fail, never disappear from denominators."""
    expected = reference_outputs
    scores = {"execution_success": float(not outputs.get("error"))}
    if outputs.get("error"):
        return {
            "results": [{"key": key, "score": 0.0} for key in ["execution_success", "reference_correctness"]]
        }
    if inputs["layer"] == "agent":
        if inputs["role"] == "intake":
            facts = outputs.get("answer", {}).get("facts", [])
            actual = {f["field"]: f["value"].casefold() for f in facts}
            gold = expected["facts"]
            correct = sum(actual.get(k) == str(v).casefold() for k, v in gold.items())
            scores["field_recall"] = correct / len(gold) if gold else float(not actual)
            scores["field_precision"] = correct / len(actual) if actual else float(not gold)
            description = inputs["context"]["description"]
            scores["quote_grounding"] = float(
                all(f["quote"] and f["quote"].casefold() in description.casefold() for f in facts)
            )
            scores["reference_correctness"] = float(
                correct == len(gold) and len(actual) == len(gold) and scores["quote_grounding"] == 1
            )
        else:
            answer = outputs["answer"]
            issues = answer.get("concerns", []) + answer.get("missing_components", [])
            evidence = {e["evidence_id"]: e["text"] for e in inputs["context"].get("retrieved_context", [])}
            grounded = [
                i
                for i in issues
                if i["evidence_id"] in evidence and i["quote"] and i["quote"] in evidence[i["evidence_id"]]
            ]
            scores["citation_grounding"] = len(grounded) / len(issues) if issues else 1.0
            expected_ids = set(expected.get("defect_evidence_ids", []))
            detected = {i["evidence_id"] for i in grounded}
            # Evidence-specific defect detection proxy, not full semantic correctness.
            scores["defect_recall_proxy"] = (
                len(detected & expected_ids) / len(expected_ids) if expected_ids else float(not issues)
            )
            scores["false_positive_free"] = float(not (detected - expected_ids))
            scores["reference_correctness"] = float(
                scores["citation_grounding"] == 1
                and scores["defect_recall_proxy"] == 1
                and scores["false_positive_free"] == 1
            )
    elif inputs["layer"] == "guardrail":
        scores["reference_correctness"] = float(outputs["allowed"] == expected["allowed"])
    elif inputs["layer"] == "retrieval":
        results = outputs["results"]
        hits = [
            i + 1
            for i, r in enumerate(results)
            if expected["source_id"] == r["source_id"] and expected["contains"] in r["content"]
        ]
        scores["recall_at_k"] = float(bool(hits))
        scores["reciprocal_rank"] = 1 / min(hits) if hits else 0.0
        scores["reference_correctness"] = scores["recall_at_k"]
    else:
        result = outputs["result"]
        checks = []
        if "status" in expected:
            checks.append(result["status"] == expected["status"])
        if "base_total" in expected:
            checks.append(
                result["base_total"] is None
                if expected["base_total"] is None
                else result["base_total"] is not None
                and Decimal(result["base_total"]) == Decimal(expected["base_total"])
            )
        items = {b["key"]: b for b in result["boq"]}
        for field in ["quantity", "unit_rate", "amount"]:
            for key, value in expected.get(field, {}).items():
                actual = items.get(key, {}).get(field)
                checks.append(
                    actual is not None and abs(Decimal(actual) - Decimal(value)) <= Decimal("0.001")
                )
        codes = {f["code"] for f in result["findings"]}
        checks.extend(code in codes for code in expected.get("finding_codes", []))
        if "minimum_retrieved" in expected:
            checks.append(result["metrics"].get("retrieved_chunks", 0) >= expected["minimum_retrieved"])
        if "minimum_evidence_coverage" in expected:
            checks.append(
                result["metrics"].get("evidence_coverage", 0) >= expected["minimum_evidence_coverage"]
            )
        priced = [
            b
            for b in result["boq"]
            if b["quantity"] is not None and b["unit_rate"] is not None and b["amount"] is not None
        ]
        from tender.engines import money

        scores["arithmetic_exact"] = float(
            all(
                Decimal(b["amount"]) == money(Decimal(b["quantity"]) * Decimal(b["unit_rate"]))
                for b in priced
            )
        )
        scores["reference_correctness"] = float(bool(checks) and all(checks))
        calls = [
            t
            for t in result["agent_trace"]
            if t["usage"].get("provider") not in {None, "offline", "deterministic"}
        ]
        scores["model_availability"] = (
            sum(t["usage"].get("status") != "unavailable" for t in calls) / len(calls) if calls else 1.0
        )
        scores["evidence_coverage"] = result["metrics"].get("evidence_coverage", 0)
    return {"results": [{"key": k, "score": v} for k, v in scores.items()]}


def make_target(model, provider, live_web=False):
    def target(inputs):
        start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="tender-eval-") as scratch:
                base = Path(scratch)
                settings = Settings(
                    _env_file=None,
                    data_dir=base / "var",
                    outputs_dir=base / "outputs",
                    drafts_dir=base / "drafts",
                    database_url=f"sqlite:///{base}/db.sqlite",
                    database_dir=base / "inbox",
                    model_provider=provider,
                    model_name=model,
                    model_base_url="http://127.0.0.1:11434",
                    rag_enabled=True,
                    web_enabled=live_web,
                    seed_demo=True,
                    logs_enabled=False,
                )
                repo = Repository(settings)
                workflow = None
                try:
                    gateway = KnowledgeGateway(repo, ObjectStore(settings), settings)
                    layer = inputs["layer"]
                    if layer == "agent":
                        answer, usage = ModelAdapter(settings, gateway).run(
                            inputs["role"],
                            inputs["context"],
                            "evaluation",
                            INTAKE_SCHEMA if inputs["role"] == "intake" else None,
                        )
                        output = {"answer": answer, "usage": usage}
                    elif layer == "guardrail":
                        output = assess_brief(ProjectBrief(description=inputs["description"]))
                    else:
                        seed(gateway)
                        pack_path = ROOT / "database/cpwd/office-preliminary.pack.json"
                        pack = DomainPack.model_validate_json(pack_path.read_text())
                        gateway.import_pack(pack, Identity(), internal_demo=True)
                        if layer == "retrieval":
                            output = gateway.search(
                                inputs["query"], "demo", authority="cpwd", limit=inputs.get("k", 5)
                            )
                        else:
                            workflow = EstimationWorkflow(repo, gateway, FolderIngestor(gateway))
                            brief = ProjectBrief.model_validate(inputs["brief"])
                            actor = Identity()
                            created = repo.create_project(brief, actor)
                            token = repo.claim(created.revision_id, actor.tenant)
                            if layer == "workflow":
                                workflow.execute(created.revision_id, actor, token)
                                result = repo.get_revision(created.revision_id, actor.tenant).result
                                output = {"result": result, "artifacts": result.get("artifacts", {})}
                            else:
                                state = {
                                    "result": repo.get_revision(created.revision_id, actor.tenant).result,
                                    "tenant": "demo",
                                    "token": token,
                                    "scope_repairs": 0,
                                    "price_repairs": 0,
                                }
                                cp = inputs["checkpoint"]
                                groups = [
                                    [
                                        "intake",
                                        "retrieve_context",
                                        "rules",
                                        "scope",
                                        "design",
                                        "quantities",
                                        "verify_scope",
                                    ],
                                    ["prices", "economics", "calculate", "verify_prices"],
                                    ["evidence", "report"],
                                ]
                                # Correct, deterministic upstream fixture; target checkpoint uses selected model.
                                selected = workflow.agents.models.settings.model_provider
                                for index, nodes in enumerate(groups, 1):
                                    if index > cp:
                                        break
                                    workflow.agents.models.settings.model_provider = (
                                        selected if index == cp else "offline"
                                    )
                                    if index == cp and inputs.get("mutation") == "broken_evidence":
                                        state["result"]["evidence"][0]["parent_ids"] = ["missing-reference"]
                                    for name in nodes:
                                        state.update(workflow.logged_node(name)(state))
                                output = {"result": state["result"]}
                                repo.release(created.revision_id, token)
                    output["latency_ms"] = round((time.perf_counter() - start) * 1000)
                    return output
                finally:
                    if workflow:
                        workflow.close()
                    repo.engine.dispose()
        except Exception as exc:
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.perf_counter() - start) * 1000),
            }

    return target


def wilson(successes, n):
    if not n:
        return [0, 1]
    z = 1.96
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(centre - half, 4), round(centre + half, 4)]


def run_benchmark(
    dataset: Path,
    model="qwen2.5:3b",
    provider="ollama",
    repetitions=1,
    upload=False,
    layer=None,
    output_dir=None,
):
    source_hash = hashlib.sha256()
    for source in sorted((ROOT / "src/tender").glob("*.py")):
        source_hash.update(source.name.encode() + source.read_bytes())
    code_sha256 = source_hash.hexdigest()
    cases = json.loads(dataset.read_text())
    cases = [c for c in cases if layer is None or c["inputs"]["layer"] == layer]
    if not cases:
        raise ValueError("No cases selected")
    if provider == "offline" and any(c["inputs"]["layer"] == "agent" for c in cases):
        raise ValueError(
            "Agent evaluations require a live provider; choose --layer workflow/checkpoint/guardrail/retrieval for offline tests"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    destination = (
        output_dir
        or ROOT / "eval/results" / f"{stamp}-{model.replace(':', '-').replace('/', '-')}-{layer or 'all'}"
    )
    destination.mkdir(parents=True, exist_ok=True)
    examples = [
        Example(
            id=uuid.uuid4(),
            dataset_id=uuid.uuid5(uuid.NAMESPACE_URL, str(dataset.resolve())),
            inputs=c["inputs"],
            outputs=c["expected"],
            metadata={"case_id": c["id"]},
            created_at=datetime.now(timezone.utc),
        )
        for c in cases
    ]
    client = None
    if upload:
        from dotenv import dotenv_values

        for name, value in dotenv_values(ROOT / ".env").items():
            if name.startswith("LANGSMITH_") and value:
                os.environ.setdefault(name, value)
        if not os.environ.get("LANGSMITH_API_KEY"):
            raise ValueError("--upload requires LANGSMITH_API_KEY in the shell or .env")
        client = Client()
        name = f"Tenderworks-{dataset.stem}-{layer or 'all'}-{hashlib.sha256(dataset.read_bytes()).hexdigest()[:12]}"
        if not client.has_dataset(dataset_name=name):
            remote = client.create_dataset(
                name,
                description="Developer-labelled Tenderworks benchmark; not independently engineer-validated.",
            )
            client.create_examples(
                dataset_id=remote.id,
                examples=[
                    {"inputs": c["inputs"], "outputs": c["expected"], "metadata": {"case_id": c["id"]}}
                    for c in cases
                ],
            )
        examples = list(client.list_examples(dataset_name=name))
        expected_by_id = {c["id"]: (c["inputs"], c["expected"]) for c in cases}
        actual_by_id = {e.metadata.get("case_id"): (e.inputs, e.outputs) for e in examples}
        if actual_by_id != expected_by_id or len(examples) != len(cases):
            raise ValueError(
                "Remote dataset differs from the versioned local benchmark; refusing to compare different labels"
            )
    underlying_target = make_target(model, provider)

    def target(inputs):
        # LangGraph nested tracing must also be disabled in local-only experiments.
        with tracing_context(enabled=True if upload else False):
            result = underlying_target(inputs)
            with (destination / "events.jsonl").open("a") as stream:
                stream.write(json.dumps({"inputs": inputs, "output": result}, default=str) + "\n")
            print(
                f"Completed {inputs['layer']} / {inputs.get('role', inputs.get('checkpoint', 'case'))}",
                flush=True,
            )
            return result

    # LangSmith native tracing and evaluation, optional cloud publication of this curated dataset only.
    experiment = evaluate(
        target,
        data=examples,
        evaluators=[score_output],
        upload_results=upload,
        client=client,
        disable_evaluator_tracing=not upload,
        max_concurrency=1,
        num_repetitions=repetitions,
        experiment_prefix=f"tenderworks-{model}-{layer or 'all'}",
        metadata={
            "prompt_version": PROMPT_VERSION,
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        },
    )
    rows = []
    for entry in experiment:
        run = entry["run"]
        example = entry["example"]
        feedback = entry["evaluation_results"]["results"]
        rows.append(
            {
                "case_id": example.metadata["case_id"],
                "layer": example.inputs["layer"],
                "inputs": example.inputs,
                "reference": example.outputs,
                "output": run.outputs,
                "run_error": run.error,
                "scores": {f.key: f.score for f in feedback},
            }
        )
    metrics = {}
    for key in {k for row in rows for k in row["scores"]}:
        values = [row["scores"][key] for row in rows if row["scores"].get(key) is not None]
        metrics[key] = statistics.mean(values) if values else None
    times = sorted(row["output"].get("latency_ms", 0) for row in rows if row["output"])
    successes = sum(row["scores"].get("reference_correctness") == 1 for row in rows)
    summary = {
        "model": model,
        "provider": provider,
        "repetitions": repetitions,
        "cases": len(cases),
        "runs": len(rows),
        "metrics": metrics,
        "pass_count": successes,
        "reference_pass_rate": successes / len(rows),
        "wilson_95_interval_per_run": wilson(successes, len(rows)),
        "interval_caveat": "Repeated runs of the same case are correlated; interval is descriptive, not independent-project generalization.",
        "latency_p50_ms": statistics.median(times) if times else None,
        "latency_p95_ms": times[max(0, math.ceil(0.95 * len(times)) - 1)] if times else None,
        "source_tree_sha256": code_sha256,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "prompt_version": PROMPT_VERSION,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "package_sha256": hashlib.sha256(
            (ROOT / "database/cpwd/office-preliminary.pack.json").read_bytes()
        ).hexdigest(),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "limitations": [
            "Small developer-labelled benchmark, not an independent engineer-reviewed test set.",
            "Critic defect metrics are evidence-ID proxies and require human semantic adjudication.",
            "No historical ablation results are inferred from these measurements.",
        ],
        "uploaded": upload,
    }
    try:
        import httpx

        summary["ollama_models"] = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5).json()["models"]
    except Exception:
        pass
    (destination / "runs.json").write_text(json.dumps(rows, indent=2, default=str))
    (destination / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({"path": str(destination), **summary}, indent=2, default=str))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/datasets/final-v3.json")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--provider", choices=["offline", "ollama"], default="ollama")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--layer", choices=["agent", "checkpoint", "workflow", "guardrail", "retrieval"])
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        parser.error("repetitions must be between 1 and 10")
    summary = run_benchmark(
        args.dataset, args.model, args.provider, args.repetitions, args.upload, args.layer, args.output
    )
    if summary["reference_pass_rate"] < 1 or summary["metrics"].get("model_availability", 1) < 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

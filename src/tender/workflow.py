"""Three-checkpoint LangGraph workflow with durable state, bounded repairs and human interrupts."""

import logging
import time
from contextlib import ExitStack
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from tender.agents import Specialists, finding
from tender.db import Repository
from tender.evaluation_reports import write_evaluation_workbook
from tender.exports import ReportCompiler
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.providers import ModelAdapter
from tender.schemas import DomainPack, EstimateResult, EvidenceRecord, Identity

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict, total=False):
    result: dict
    pack: dict
    tenant: str
    token: str
    scope_repairs: int
    price_repairs: int


class EstimationWorkflow:
    def __init__(self, repo: Repository, gateway: KnowledgeGateway, ingestor: FolderIngestor):
        self.repo, self.gateway, self.ingestor = repo, gateway, ingestor
        self.agents = Specialists(gateway, ModelAdapter(repo.settings, gateway))
        self.compiler = ReportCompiler(gateway.objects)
        self.stack = ExitStack()
        if repo.settings.database_url.startswith("sqlite"):
            self.checkpointer = self.stack.enter_context(
                SqliteSaver.from_conn_string(str(repo.settings.data_dir / "checkpoints.sqlite"))
            )
        else:
            self.checkpointer = self.stack.enter_context(
                PostgresSaver.from_conn_string(
                    repo.settings.database_url.replace("postgresql+psycopg://", "postgresql://")
                )
            )
            self.checkpointer.setup()
        graph = StateGraph(WorkflowState)
        for name in (
            "ingest",
            "intake",
            "retrieve_context",
            "rules",
            "scope",
            "design",
            "quantities",
            "verify_scope",
            "scope_repair",
            "design_review",
            "prices",
            "economics",
            "calculate",
            "verify_prices",
            "price_repair",
            "evidence",
            "report",
        ):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "ingest")
        graph.add_edge("ingest", "intake")
        graph.add_conditional_edges("intake", lambda s: "retrieve_context" if s.get("pack") else "report")
        for a, b in [
            ("retrieve_context", "rules"),
            ("rules", "scope"),
            ("scope", "design"),
            ("design", "quantities"),
            ("quantities", "verify_scope"),
            ("scope_repair", "scope"),
            ("design_review", "prices"),
            ("prices", "economics"),
            ("economics", "calculate"),
            ("calculate", "verify_prices"),
            ("price_repair", "prices"),
            ("evidence", "report"),
            ("report", END),
        ]:
            graph.add_edge(a, b)
        graph.add_conditional_edges("verify_scope", self.after_scope)
        graph.add_conditional_edges("verify_prices", self.after_prices)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def close(self):
        self.stack.close()

    def result(self, state):
        return EstimateResult.model_validate(state["result"])

    def pack(self, state):
        return DomainPack.model_validate(state["pack"])

    def save(self, state, result, role, started, usage=None):
        result.agent_trace.append(
            {
                "role": role,
                "checkpoint": result.checkpoint,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "usage": usage or {"provider": "deterministic"},
            }
        )
        self.repo.save_result(result, state["token"])
        return {"result": result.model_dump(mode="json")}

    def ingest(self, state):
        start, result = time.perf_counter(), self.result(state)
        report = self.ingestor.scan(state["tenant"])
        result.status = "running"
        result.metrics["ingestion"] = {k: v for k, v in report.items() if k != "files"}
        if report["failed"]:
            finding(
                result,
                "ingestion_failures",
                1,
                f"{report['failed']} source files could not be indexed. See the knowledge inbox.",
                "warning",
            )
        return self.save(state, result, "ingestion", start)

    def intake(self, state):
        start, result = time.perf_counter(), self.result(state)
        result.checkpoint = 1
        usage = self.agents.intake(result, state["tenant"])
        selected = self.agents.route(result, state["tenant"])
        updates = {}
        if selected:
            _, pack = selected
            self.repo.pin_pack(result.revision_id, pack.model_dump(mode="json"))
            updates["pack"] = pack.model_dump(mode="json")
        else:
            result.status = "needs_input"
            result.pending = {
                "kind": "routing",
                "message": "Revise the project or add an applicable reviewed domain package.",
            }
        updates.update(self.save(state, result, "intake_and_routing", start, usage))
        return updates

    def rules(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.rules(result, self.pack(state))
        usage = self.agents.model_review("rules", result, state["tenant"])
        return self.save(state, result, "rules_and_applicability", start, usage)

    def retrieve_context(self, state):
        """Retrieve advisory context once; this evidence never participates in calculation inputs."""
        start, result = time.perf_counter(), self.result(state)
        if not self.repo.settings.rag_enabled or any(e.kind == "retrieved" for e in result.evidence):
            return self.save(state, result, "retrieve_context", start)
        pack = self.pack(state)
        components = ", ".join(component.key for component in pack.components[:12])
        queries = [
            f"{result.brief.building_type} {components} requirements exclusions",
            f"{result.brief.authority} building fire accessibility sanitation requirements",
            f"{result.brief.authority} building measurement specification clauses",
        ]
        seen: set[tuple[str, str]] = set()
        for query in queries:
            found = self.gateway.search(
                query,
                state["tenant"],
                authority=result.brief.authority,
                state=result.brief.state,
                as_of=result.brief.estimate_date,
                limit=8,
            )
            for item in found["results"]:
                marker = (item["document_id"], item["locator"])
                if marker in seen or len(seen) >= 12:
                    continue
                seen.add(marker)
                evidence_id = f"retrieved:{item['document_id']}:{len(seen)}"
                result.evidence.append(
                    EvidenceRecord(
                        id=evidence_id,
                        kind="retrieved",
                        title=item["title"],
                        source_id=item["source_id"],
                        version=item["version"],
                        locator=item["locator"],
                        snapshot_ref=item["snapshot_ref"],
                        content_hash=item["content_hash"],
                        value=item["content"],
                        trust=item["trust"],
                    )
                )
        result.metrics["retrieved_chunks"] = len(seen)
        return self.save(state, result, "retrieve_context", start)

    def scope(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.scope(result, self.pack(state))
        usage = self.agents.model_review("scope", result, state["tenant"])
        return self.save(state, result, "scope_planner", start, usage)

    def design(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.design(result, self.pack(state))
        usage = self.agents.model_review("design", result, state["tenant"])
        return self.save(state, result, "concept_design", start, usage)

    def quantities(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.quantities(result, self.pack(state))
        return self.save(state, result, "quantity_estimator", start)

    def verify_scope(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.verify_quantities(result, self.pack(state))
        usage = self.agents.model_review("quantity_verifier", result, state["tenant"])
        return self.save(state, result, "scope_and_quantity_verifier", start, usage)

    def after_scope(self, state):
        repairable = {"duplicate_component", "missing_required_component"}
        if (
            any(f["code"] in repairable for f in state["result"]["findings"])
            and state.get("scope_repairs", 0) < 2
        ):
            return "scope_repair"
        return "design_review"

    def scope_repair(self, state):
        result = self.result(state)
        result.findings = [
            f for f in result.findings if f.code not in {"duplicate_component", "missing_required_component"}
        ]
        return {"result": result.model_dump(mode="json"), "scope_repairs": state.get("scope_repairs", 0) + 1}

    def design_review(self, state):
        result = self.result(state)
        if result.brief.review_design and result.design:
            # No external mutation before interrupt. The node is safe to replay on resume.
            response = interrupt(
                {
                    "kind": "design_review",
                    "revision_id": result.revision_id,
                    "message": "Review concept assumptions and quantities, then accept or create a corrected revision.",
                }
            )
            if response.get("decision") != "accept_design":
                raise ValueError("Design review requires an explicit accept_design decision")
            for assumption in result.assumptions:
                assumption.status = "accepted"
            result.pending = None
            result.status = "running"
        return {"result": result.model_dump(mode="json")}

    def prices(self, state):
        start, result = time.perf_counter(), self.result(state)
        result.checkpoint = 2
        self.agents.prices(result, self.pack(state), state["tenant"])
        usage = self.agents.model_review("rate_estimator", result, state["tenant"])
        return self.save(state, result, "rate_estimator", start, usage)

    def economics(self, state):
        start, result = time.perf_counter(), self.result(state)
        usage = self.agents.model_review(
            "economics",
            result,
            state["tenant"],
            context={
                "authority": result.brief.authority,
                "brief": result.brief.model_dump(mode="json"),
                "adjustments": [a.model_dump(mode="json") for a in self.pack(state).adjustments],
                "rate_inclusions": {b.key: b.inclusions for b in result.boq},
            },
        )
        return self.save(state, result, "economics", start, usage)

    def calculate(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.calculate(result, self.pack(state))
        return self.save(state, result, "cost_engine", start)

    def verify_prices(self, state):
        start, result = time.perf_counter(), self.result(state)
        self.agents.verify_prices(result, self.pack(state))
        usage = self.agents.model_review("pricing_verifier", result, state["tenant"])
        return self.save(state, result, "pricing_verifier", start, usage)

    def after_prices(self, state):
        if (
            any(f["code"] == "arithmetic_mismatch" for f in state["result"]["findings"])
            and state.get("price_repairs", 0) < 2
        ):
            return "price_repair"
        return "evidence"

    def price_repair(self, state):
        result = self.result(state)
        result.findings = [f for f in result.findings if f.code != "arithmetic_mismatch"]
        return {"result": result.model_dump(mode="json"), "price_repairs": state.get("price_repairs", 0) + 1}

    def evidence(self, state):
        start, result = time.perf_counter(), self.result(state)
        result.checkpoint = 3
        self.agents.audit_evidence(result, self.pack(state))
        usage = self.agents.model_review("evidence_audit", result, state["tenant"])
        result.metrics.update(
            {"scope_repairs": state.get("scope_repairs", 0), "price_repairs": state.get("price_repairs", 0)}
        )
        return self.save(state, result, "evidence_audit", start, usage)

    def report(self, state):
        start, result = time.perf_counter(), self.result(state)
        if result.boq:
            self.compiler.compile(result)
        return self.save(state, result, "report_compiler", start)

    def execute(self, revision_id: str, identity: Identity, token: str, resume: dict | None = None):
        config = {"configurable": {"thread_id": revision_id}, "recursion_limit": 70}
        try:
            row = self.repo.get_revision(revision_id, identity.tenant)
            snapshot = self.graph.get_state(config)
            if resume is not None:
                # Replace lease metadata while preserving the saved interrupt.
                self.graph.update_state(config, {"token": token})
                payload = Command(resume=resume)
            elif snapshot.values:
                self.graph.update_state(config, {"token": token})
                payload = None
            else:
                payload = {
                    "result": row.result,
                    "tenant": identity.tenant,
                    "token": token,
                    "scope_repairs": 0,
                    "price_repairs": 0,
                }
            output = self.graph.invoke(payload, config)
            result = EstimateResult.model_validate(output["result"])
            if output.get("__interrupt__"):
                result.status = "awaiting_review"
                result.pending = output["__interrupt__"][0].value
                if result.design:
                    # Provide reviewable artifacts without pricing or a misleading complete total.
                    self.compiler.compile(result)
            self.repo.save_result(result, token)
            self.repo.audit(
                identity,
                "workflow_finished",
                revision_id,
                {"status": result.status, "checkpoint": result.checkpoint},
            )
        except Exception:
            logger.exception("Estimate workflow failed: %s", revision_id)
            row = self.repo.get_revision(revision_id, identity.tenant)
            result = EstimateResult.model_validate(row.result)
            result.status = "failed"
            finding(
                result,
                "workflow_failure",
                max(1, result.checkpoint),
                "The workflow stopped unexpectedly. Correct the cause and resume this revision; completed checkpoints are preserved.",
            )
            self.repo.save_result(result, token)
        finally:
            try:
                row = self.repo.get_revision(revision_id, identity.tenant)
                write_evaluation_workbook(
                    EstimateResult.model_validate(row.result), self.repo.settings.outputs_dir
                )
            except Exception:
                logger.exception("Evaluation workbook failed: %s", revision_id)
            self.repo.release(revision_id, token)

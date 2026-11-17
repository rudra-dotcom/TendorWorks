# Tenderworks final evaluation methodology and viva guide

## What we evaluate and why

Tenderworks combines stochastic model outputs with deterministic geometry, rate matching, rules and money arithmetic. One LLM confidence score cannot measure all these responsibilities. We use a layered, reference-based evaluation architecture: independent code assertions for numerical/structural claims, source-grounding checks for citations, and engineer review for judgments without reliable automated truth.

The implementation uses **LangSmith's Python SDK**, `pytest`, and custom Tenderworks evaluators. LangSmith manages execution and evaluation records; it does not make reference answers correct. Local experiments use `upload_results=False`, and nested graph cloud tracing is disabled. No LangSmith key is needed locally. `--upload` publishes the curated examples/results to the configured LangSmith workspace and requires a valid `LANGSMITH_API_KEY`. Hosted upload was not validated without credentials.

## Files and storage

| File/directory | Purpose |
|---|---|
| `src/tender/benchmarks.py` | Isolated targets, reference scorers, LangSmith runner, aggregate metrics, failure exit codes |
| `eval/datasets/final-v3.json` | Versioned developer-labelled cases and expected outcomes |
| `eval/results/<experiment>/runs.json` | Individual inputs, reference labels, outputs, errors and scores |
| `eval/results/<experiment>/summary.json` | Aggregates, timing, model metadata, source/package fingerprints and limitations |
| `tests/` | Deterministic engine, access, ingestion, source integrity, schema, guardrail and retry regressions |
| `src/tender/evaluation.py` | Retained legacy whole-workflow reference evaluator |
| `eval/*_probe.py` and `eval/README.md` | Existing diagnostic probes; not a replacement for a held-out benchmark |
| `outputs/` | Existing per-revision evaluation/review workbooks and demo result |
| `var/logs/` | Tenant/revision-separated raw node/model event logs; excluded from Git |
| `.github/workflows/evaluation.yml` | Automated deterministic regression gates and artifact upload |

## Levels

1. **Tools/engines:** pytest validates Decimal arithmetic, restricted formulas, units, source-integrity failures, retrieval isolation, ingestion deduplication, web redirect controls and review permissions.
2. **Agents:** five intake examples measure expected-field precision/recall and exact-quote grounding. Every live specialist role has a controlled defect example; a clean critic example measures spurious findings. Quantity generation is deterministic and is tested through engine tests and CP1.
3. **Checkpoints:** CP1 starts from a brief; CP2 receives a deterministic quantity baseline; CP3 receives a deterministic priced baseline. Only the checkpoint under test uses the selected model. A corrupted evidence-parent test checks that CP3 refuses a complete total.
4. **Workflow:** the full CPWD example, an unrelated request and an unsupported-authority case test correct draft production and correct abstention. Live benchmarks exercise the selected Ollama model; offline CI tests do not claim LLM quality.
5. **Retrieval and guardrails:** gold-source retrieval at k and reciprocal rank; labelled allow/block decisions. Additional adversarial/security scenarios live in pytest.

## Metrics

- `execution_success`: target completed without an uncaught error. This alone is not correctness.
- `reference_correctness`: all explicitly supplied reference assertions passed; missing values count as failures.
- `field_precision`, `field_recall`, `quote_grounding`: intake extraction against labelled fields/quotes.
- `citation_grounding`: cited ID exists and the quote appears in its excerpt. This does **not** prove semantic entailment.
- `defect_recall_proxy`, `false_positive_free`: whether critic warnings cite the injected defect's evidence and avoid extraneous evidence. These are intentionally named proxies; a human must judge whether the explanation identifies the actual error.
- `arithmetic_exact`: priced line amount equals rounded Decimal quantity × rate. Absent priced rows produce vacuous arithmetic success; reference correctness and coverage must be considered alongside it.
- `model_availability`: non-offline specialist calls that did not fall back. A correct deterministic estimate is not proof the LLM worked.
- `evidence_coverage`: structural linkage coverage, separate from citation correctness.
- Retrieval recall@k and reciprocal rank; p50/p95 target wall-clock latency.
- A descriptive Wilson interval for per-run reference success. Repetitions of one project are correlated, so this is not a population accuracy guarantee.

Raw model token usage and model tag/digest/quantization are retained. Local Ollama has no API token invoice; cost must be estimated from hardware/runtime and cannot be invented from token counts. Checkpoint timing includes deterministic fixture preparation; this is recorded target latency, not pure model inference latency.

## Commands

Run from `btp2/TendorWorks` (the directory containing this file):

```sh
uv sync --frozen
uv run pytest -q
uv run python -m tender.benchmarks --provider offline --model offline --layer workflow
uv run python -m tender.benchmarks --provider offline --model offline --layer checkpoint
uv run python -m tender.benchmarks --provider offline --model offline --layer retrieval
uv run python -m tender.benchmarks --model qwen2.5:3b
uv run python -m tender.benchmarks --model gemma3:latest
# Repeat stochastic measurements (slower):
uv run python -m tender.benchmarks --model qwen2.5:3b --layer agent --repetitions 3
# Optional hosted experiment; only use approved test data:
uv run python -m tender.benchmarks --model qwen2.5:3b --layer agent --upload
```

The runner uses temporary isolated databases, not live project state. HTTP calls are sequential to avoid competing for the Mac's RAM/GPU. Web is disabled during benchmark cases; frozen downloaded snapshots make runs reproducible. The separate demo enables live official-index search. Every target failure is retained and scored as failure. A nonzero exit signals a reference or model-availability gate failure; keep the result files for analysis rather than deleting failed runs.

## Interpretation and release gates

The committed dataset is a small development benchmark, not an independent engineer-reviewed production test set. Tests were designed around known failure modes; do not claim general accuracy from their pass rate. The local benchmark is suitable as a reproducible BTech evaluation artifact and a foundation for production evaluation, not certification that this system can issue tenders.

Before deployment, add reviewed projects across authority, building type, scope and rate editions; split by project family so related revisions do not leak into test data. Freeze a held-out test set. Require exact arithmetic, no cross-tenant leaks, preserved blockers, and applicable sources for every priced item. Agree quantity/rate tolerances with engineers. Use repeated paired comparisons and project-level bootstrap intervals on a sufficiently large set. Add reviewer-calibrated semantic judges if needed; no uncalibrated LLM-as-judge score should override arithmetic or applicability failures.

The current harness does not claim learned confidence calibration, automatic model training, an exhaustive security audit, a load benchmark, or a proven improvement caused by critics. Model confidence and retrieval similarity are not used as substitutes for reference truth. Historical claims about better results after critics/checkpoints are project-development observations unless matched ablation experiments are supplied.

## Short viva answers

- **Why isolate agents?** To identify which responsibility failed independently of upstream errors.
- **Why checkpoints too?** To test artifact contracts and interactions across roles.
- **Why end-to-end?** A collection of passing agents does not prove the user receives a usable, traceable result.
- **Why LangSmith?** It provides dataset-driven experiments and common tracing/evaluator interfaces; custom scorers preserve domain-specific truth.
- **Why not only confidence?** Confidence is a prediction; reference evaluation checks correctness. Calibration requires labelled held-out outcomes.
- **Does feedback train the model?** No. Reviewed feedback becomes candidate regression cases and proposed package/prompt changes; a new evaluation is required before release.
- **What is still missing?** Independent engineering labels, broad real-project coverage, structural/CAD design, mature deployment controls and stronger semantic/adversarial evaluations.

References: [LangSmith local evaluations](https://docs.langchain.com/langsmith/local), [SDK evaluate parameters](https://reference.langchain.com/python/langsmith/evaluation/_runner/evaluate).

## Dataset and prompt revisions

The initial `final.json` has 25 development cases; `model-comparison.json` contains its 12 model-role cases. V3 uses `final-v3.json` (27 cases) and `model-comparison-v3.json` (14 model-role cases). One intake label was corrected: the text explicitly supplied Delhi as a location, not as a named state. Two additional intake cases cover another authority and a fully specified office. Older datasets and failed runs are preserved. Do not attribute a change in overall pass rate solely to a prompt change when labels/case counts also changed. Each within-version two-model comparison uses identical data and settings.

V3 restricts intake field names to the application's accepted contract and requests unit-free numeric strings. Reviews allow one finding per category, with a configurable `TENDER_MODEL_OUTPUT_TOKENS` budget (default 900). This addresses observed output truncation without accepting malformed JSON. The model-role benchmark calls the raw model adapter; checkpoint/workflow tests measure the combined deterministic-plus-model agents.

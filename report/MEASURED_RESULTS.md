# Measured evaluation results

These figures are generated from saved experiment results, not manually invented. Single-run development cases are not population accuracy estimates. The bounded-review two-model comparison is a separate experiment from the earlier full Qwen run.

| Experiment | Model | Cases / runs | Reference passes | p50 target seconds | p95 target seconds |
|---|---|---|---|---|---|
| final-gemma-agents | gemma3:latest | 12 / 12 | 7 / 12 | 10.75 | 23.08 |
| final-qwen-agents | qwen2.5:3b | 12 / 12 | 5 / 12 | 15.55 | 21.44 |
| offline-checkpoints | offline | 4 / 4 | 4 / 4 | 0.49 | 0.62 |
| offline-retrieval | offline | 1 / 1 | 1 / 1 | 0.35 | 0.35 |
| offline-workflow | offline | 3 / 3 | 3 / 3 | 0.08 | 0.51 |
| qwen2.5-3b | qwen2.5:3b | 25 / 25 | 19 / 25 | 9.68 | 373.14 |
| v3-gemma-agents | gemma3:latest | 14 / 14 | 9 / 14 | 10.02 | 14.74 |
| v3-offline-workflow | offline | 3 / 3 | 3 / 3 | 0.11 | 0.62 |
| v3-qwen-agents | qwen2.5:3b | 14 / 14 | 5 / 14 | 13.17 | 16.73 |

## final-gemma-agents

Prompt version: `2026-11-17-bounded-review-v2`. Dataset SHA-256: `b6a14ab18494189988de38ed827569c4b89ef53bafe5aa4be4d93239ddaa26ed`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| agent | 7/12 | 0 |

Failed reference cases:
- `intake-0`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-1`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-2`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `evidence_audit-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `critic-clean`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.

Selected metrics:
- `citation_grounding`: 0.8889
- `defect_recall_proxy`: 0.7778
- `execution_success`: 1.0000
- `false_positive_free`: 0.8889
- `field_precision`: 0.0000
- `field_recall`: 0.0000
- `quote_grounding`: 1.0000
- `reference_correctness`: 0.5833

## final-qwen-agents

Prompt version: `2026-11-17-bounded-review-v2`. Dataset SHA-256: `b6a14ab18494189988de38ed827569c4b89ef53bafe5aa4be4d93239ddaa26ed`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| agent | 5/12 | 0 |

Failed reference cases:
- `intake-0`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-1`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-2`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `design-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `rate_estimator-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `pricing_verifier-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `critic-clean`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.

Selected metrics:
- `citation_grounding`: 0.6296
- `defect_recall_proxy`: 0.6667
- `execution_success`: 1.0000
- `false_positive_free`: 1.0000
- `field_precision`: 0.0000
- `field_recall`: 0.0000
- `quote_grounding`: 1.0000
- `reference_correctness`: 0.4167

## offline-checkpoints

Prompt version: `2026-11-llm-review-v1`. Dataset SHA-256: `8b26ee1093a3accf96ee880f989535bfc9a44d67b5ddfdf4fd41905f398e41b0`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| checkpoint | 4/4 | 0 |

Failed reference cases:
- None in this run. This does not establish general correctness.

Selected metrics:
- `arithmetic_exact`: 1.0000
- `evidence_coverage`: 0.5000
- `execution_success`: 1.0000
- `model_availability`: 1.0000
- `reference_correctness`: 1.0000

## offline-retrieval

Prompt version: `2026-11-llm-review-v1`. Dataset SHA-256: `8b26ee1093a3accf96ee880f989535bfc9a44d67b5ddfdf4fd41905f398e41b0`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| retrieval | 1/1 | 0 |

Failed reference cases:
- None in this run. This does not establish general correctness.

Selected metrics:
- `execution_success`: 1.0000
- `recall_at_k`: 1.0000
- `reciprocal_rank`: 1.0000
- `reference_correctness`: 1.0000

## offline-workflow

Prompt version: `2026-11-llm-review-v1`. Dataset SHA-256: `8b26ee1093a3accf96ee880f989535bfc9a44d67b5ddfdf4fd41905f398e41b0`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| workflow | 3/3 | 0 |

Failed reference cases:
- None in this run. This does not establish general correctness.

Selected metrics:
- `arithmetic_exact`: 1.0000
- `evidence_coverage`: 0.3333
- `execution_success`: 1.0000
- `model_availability`: 1.0000
- `reference_correctness`: 1.0000

## qwen2.5-3b

Prompt version: `2026-11-llm-review-v1`. Dataset SHA-256: `8b26ee1093a3accf96ee880f989535bfc9a44d67b5ddfdf4fd41905f398e41b0`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| agent | 6/12 | 0 |
| guardrail | 5/5 | 0 |
| retrieval | 1/1 | 0 |
| checkpoint | 4/4 | 0 |
| workflow | 3/3 | 0 |

Failed reference cases:
- `intake-0`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-1`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-2`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `rate_estimator-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `pricing_verifier-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `critic-clean`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.

Selected metrics:
- `arithmetic_exact`: 1.0000
- `citation_grounding`: 0.7778
- `defect_recall_proxy`: 0.6667
- `evidence_coverage`: 0.4286
- `execution_success`: 1.0000
- `false_positive_free`: 0.8889
- `field_precision`: 0.0000
- `field_recall`: 0.0000
- `model_availability`: 0.7841
- `quote_grounding`: 1.0000
- `recall_at_k`: 1.0000
- `reciprocal_rank`: 1.0000
- `reference_correctness`: 0.7600

## v3-gemma-agents

Prompt version: `2026-11-17-bounded-review-v3`. Dataset SHA-256: `bdea3aac8b9b30e7fa40efb01ee4fc9323ec2bc84f09a31150da6d70ab15b8c6`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| agent | 9/14 | 0 |

Failed reference cases:
- `intake-0`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-2`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `evidence_audit-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `critic-clean`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-unseen-office`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.

Selected metrics:
- `citation_grounding`: 0.8889
- `defect_recall_proxy`: 0.7778
- `execution_success`: 1.0000
- `false_positive_free`: 0.8889
- `field_precision`: 0.8000
- `field_recall`: 0.8000
- `quote_grounding`: 0.6000
- `reference_correctness`: 0.6429

## v3-offline-workflow

Prompt version: `2026-11-17-bounded-review-v3`. Dataset SHA-256: `12012e282297ec4909ecb2dbc99f377e1ffb4a3f2f6d5693ab0d9900ddf4b484`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| workflow | 3/3 | 0 |

Failed reference cases:
- None in this run. This does not establish general correctness.

Selected metrics:
- `arithmetic_exact`: 1.0000
- `evidence_coverage`: 0.3333
- `execution_success`: 1.0000
- `model_availability`: 1.0000
- `reference_correctness`: 1.0000

## v3-qwen-agents

Prompt version: `2026-11-17-bounded-review-v3`. Dataset SHA-256: `bdea3aac8b9b30e7fa40efb01ee4fc9323ec2bc84f09a31150da6d70ab15b8c6`.

| Layer | Reference passes | Execution failures |
|---|---|---|
| agent | 5/14 | 0 |

Failed reference cases:
- `intake-0`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-1`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-2`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `rules-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `rate_estimator-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `pricing_verifier-defect`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `critic-clean`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-unseen-railway`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.
- `intake-unseen-office`: One or more labelled reference assertions or evidence-grounding proxies failed; inspect runs.json.

Selected metrics:
- `citation_grounding`: 0.6111
- `defect_recall_proxy`: 0.5556
- `execution_success`: 1.0000
- `false_positive_free`: 0.8889
- `field_precision`: 0.6143
- `field_recall`: 0.5000
- `quote_grounding`: 0.8000
- `reference_correctness`: 0.3571

## Persisted CPWD demonstration

- Revision: `8690eaa8-fe78-49f8-9770-620f440f110e`; status: `draft`.
- Defined-scope total: INR 11028540.00.
- Retrieved excerpts: 12.
- Ollama specialist traces: 9; model-unavailable findings: 0.
- Structural evidence coverage: 1.0.
- This confirms a scoped software execution, not engineering approval.

## Interpretation

Do not average expected abstentions with complete estimates to claim low/high source coverage. Coverage is meaningful on priced rows. A workflow can pass deterministic reference checks even when the model fails: inspect model_availability separately. Agent reference scores are deliberately stricter than schema validity and critic citation proxies do not prove semantic correctness.

Two-model observations apply only to this developer-authored dataset and installed quantizations. No statistically defensible model superiority or causal benefit from critique loops is claimed. For release decisions use multiple repetitions, engineer adjudication, independent project-family test splits and a substantially larger benchmark.

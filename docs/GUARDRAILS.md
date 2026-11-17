# Tenderworks guardrails and trust policy

Version: 2026-11-17-v1. This is an implemented control policy, not certification of government compliance.

## Boundaries and criteria

| Boundary | Criterion and implementation | Failure behavior |
|---|---|---|
| Intake scope | `guardrails.assess_brief`: public-works vocabulary, explicit off-topic patterns, instruction-override and secret-disclosure patterns | `needs_input`, blocking finding; no intake LLM call |
| Supported project | Domain package must match authority, state, work category and estimate date; geometry must support building type | Visible blocker; no invented applicable schedule |
| Model output | JSON schema validation in `ModelAdapter.run`; bounded response tokens and HTTP timeout | Failed call recorded; deterministic workflow continues with `model_unavailable` warning |
| Evidence citations | Review suggestions must cite an existing retrieved evidence ID and exact source substring | Unsupported suggestions discarded and counted; stored raw output remains auditable |
| Numeric authority | Only structured schedule rows or supported resource analyses set rates; specification and unit must match | Missing price stays unresolved; no general web-text-to-price conversion |
| Source trust | Both local RAG and web material can be unverified. Storage location and official hostname do not constitute engineering approval | Candidate/demo status and unverified-retrieval warning; no automatic promotion |
| Web retrieval | HTTPS, hostname allowlist, public DNS addresses, redirect revalidation, response-size limit, timeout and block-page detection | Visible unavailable/gap status; local sources remain usable |
| Arithmetic | Decimal calculations, restricted formula syntax, inclusion/double-count checks, independent line-amount checks | Blocking finding; complete total withheld |
| Review | Human package approval and final estimate review are separate from model advice | Demo cannot be marked reviewed; formal engineering sanction remains external |
| Retry limits | 0–5 attempts per checkpoint; default 2. User may skip remaining attempts mid-run | Current step finishes, subsequent retries skipped; unresolved findings are preserved |
| Access | Existing tenant-scoped identity/role checks protect project, review and retry-control endpoints | Unauthorized request rejected |

## What is and is not verified

- `approved` means an authorized application reviewer accepted applicability and extracted data. It is not a claim that CPWD approved the generated estimate.
- A downloaded CPWD PDF has an official publication URL and recorded byte hash. The PDF's applicability to a particular project still needs review.
- The supplied CPWD PAR demo intentionally remains `demo`: its numeric rates are transcribed from an official publication, but its geometric and fire-system assumptions are academic scenarios.
- Web content remains `candidate` even on official sites. Unverifiable applicability is stated in findings and source records, and never silently used for numeric pricing.
- RAG is retrieval, not verification. A high similarity score is not confidence in correctness.

## Web modes

`TENDER_WEB_ENABLED=true` enables research. `TENDER_WEB_PROVIDER=official` searches a fixed official Railway Board publication index for PAR 2025; it is key-free, deliberately narrow, and not a general-purpose search engine. `TENDER_WEB_PROVIDER=brave` uses Brave Search and requires `TENDER_WEB_SEARCH_KEY`. Both use the same allowlist and candidate-evidence policy. Queries contain authority/catalog categories, not project addresses or uploaded confidential text. Successful discoveries are cached for 24 hours, separately per tenant. Offline benchmark cases disable live web to preserve reproducibility; live web is exercised in the demo separately.

## Logs

`var/logs/<tenant-sha256-prefix>/<revision-sha256-prefix>.jsonl` contains node inputs/outputs, model inputs/outputs, failures, role, elapsed time and token usage. Revision ID is present inside each event; only emitted answers are logged, not hidden chain-of-thought. Files are created with owner-only permissions. API credentials are not included in recorded configuration. Inputs may contain sensitive project text, so restrict access to `var/`.

`TENDER_LOGS_REDACT_TEXT=true` replaces input/output bodies with hashes (replay becomes unavailable). Cloud upload is not enabled for application logs. Benchmark `--upload` is an explicit separate opt-in for curated test examples. `uv run tender purge-logs` deletes local trace files older than `TENDER_LOGS_RETENTION_DAYS` (default 30); schedule that command operationally. No automatic retention service is claimed.

## Advisory context budget

LLM reviews receive at most four retrieved excerpts (800 characters each), eight findings and ten assumptions. Full artifacts are retained and checked deterministically. This bounds latency but means an LLM review is not exhaustive. The supplied 8 GB Mac configuration uses a 4096-token context; agent-comparison experiments use the same 8192-token configuration for both models.

## Limits

The lexical scope guard is a transparent baseline: it can reject valid multilingual/ambiguous descriptions and miss sophisticated disguised requests. It does not solve prompt injection. Source isolation, schema validation, non-executable formulas and keeping prices outside model control limit damage when classification fails. DNS validation is not a substitute for a production outbound proxy (DNS-rebinding protection, network policy and host pinning remain deployment work). Authentication, HTTPS termination, secrets management, database backups and independent security review are still deployment responsibilities.

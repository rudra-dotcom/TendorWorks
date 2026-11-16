# Tenderworks

A runnable government works estimation workspace: project brief → concept drawings → quantities → rates → evidence-backed BOQ.

The application includes a FastAPI web interface, a persistent LangGraph workflow, deterministic geometry and decimal calculation engines, source ingestion, review and feedback, and PDF/XLSX/DOCX/SVG/DXF/JSON exports.

## Run locally

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync --frozen
uv run tender serve
```

Open **http://127.0.0.1:8000**. Choose **Explore a sample estimate** to try the complete workflow. API documentation is at `/docs`.

The default configuration needs no API keys or external services. It uses SQLite, local content-addressed object storage, keyword retrieval, and deterministic templates. The CPWD, railway-building and Maharashtra PWD demonstration packages contain **synthetic prices and quantity norms**, labelled in the interface and every export. They are not official schedules. Only rectangular concept layouts for schools, offices and community halls are bundled.

For a particular Python installation:

```sh
uv sync --frozen --python /path/to/python3.12
```

## Add your own database files

Place PDFs, DOCX, TXT/Markdown, CSV, XLSX or JSON files in **[`database/`](database/README.md)**.

1. On startup, and before an estimate runs, the application scans this folder.
2. SHA-256 hashes cover each file's bytes and optional metadata sidecar.
3. Unchanged files are skipped. New and changed files are extracted, snapshotted, chunked and indexed.
4. Old source versions remain available to earlier estimates; only the current inbox version is searched by default.
5. Failed extractions stay visible and are retried. Scanned PDFs need an OCR text layer; their values are not guessed.

You can also select **Scan database folder** or upload documents in the knowledge library. To scan without the web server:

```sh
uv run tender ingest
```

Searchable documents and approved numeric rate records are separate. Raw tables are retained as source evidence; a **domain package** connects verified rows to specifications, units, measurement recipes, design defaults and applicability rules. This prevents a semantically similar PDF passage from silently becoming a price.

See [the ingestion guide](docs/ingestion.md) for metadata, package formats, revision handling and semantic retrieval configuration.

## What the application does

- **Checkpoint 1:** extracts explicit brief facts, routes to an applicable package, identifies components, generates a concept model and drawings, calculates quantities, and verifies scope. Optional design review pauses are durable across restart.
- **Checkpoint 2:** matches exact specifications and units against applicable rate records, supports resource-built non-scheduled rates, applies sourced adjustments, prevents overlapping additions, and checks arithmetic and normalized historical comparisons.
- **Checkpoint 3:** audits evidence and calculation links, verifies source snapshot integrity, and compiles the report and BOQ. Unsupported required items leave the estimate incomplete with a known subtotal.
- **Revisions:** edits create a new revision. Geometry, quantities, prices and exports are recomputed; older reports and their source versions remain available.
- **Feedback:** corrections enter a review queue. Accepted corrections are candidates for offline evaluation; they never directly overwrite official rules or rates.

The structured concept model is shared by geometry and quantity calculations. Foundation, reinforcement and service-capacity quantities remain explicit template allowances until actual engineering inputs are available. Concept output is not a construction drawing or technical sanction.

## Optional live services

Copy `.env.example` to `.env` and configure only the services you need.

| Capability | Configuration |
|---|---|
| Live specialist reasoning | `TENDER_MODEL_PROVIDER=anthropic`, explicit `TENDER_MODEL_NAME`, `TENDER_MODEL_API_KEY` |
| NVIDIA RAG + specialist reviews | `TENDER_MODEL_PROVIDER=nvidia`, `TENDER_NVIDIA_API_KEY`, chat/embedding/rerank model names; optional `TENDER_NVIDIA_BASE_URL` for a self-hosted NIM, plus `TENDER_RAG_ENABLED=true` |
| Legacy hybrid retrieval | `TENDER_EMBEDDING_URL` and optional `TENDER_EMBEDDING_KEY` |
| Public-source research | `TENDER_WEB_ENABLED=true`, `TENDER_WEB_SEARCH_KEY` for Brave Search, allowed official hosts |
| PostgreSQL + pgvector | `TENDER_DATABASE_URL=postgresql+psycopg://...` |
| S3 object storage | `TENDER_OBJECT_BACKEND=s3`, `TENDER_S3_BUCKET`, optional endpoint; use the standard AWS credential chain |
| Authenticated deployment | `TENDER_MODE=production`, `TENDER_SEED_DEMO=false`, `TENDER_API_KEYS` |

NVIDIA RAG indexes searchable PDFs page-by-page with NVIDIA passage embeddings, retrieves with query embeddings, then reranks a bounded hybrid candidate pool. Retrieved passages are advisory data: only exact quoted citations may become Checkpoint 1 warnings, findings, or proposed assumptions. They cannot change quantities, rates or totals. If NVIDIA is unavailable, indexing retains text for keyword search and the workflow continues.

Live agents have a bounded, read-only tool loop. They can search the tenant's knowledge but cannot write rates, execute arbitrary code, approve estimates or override deterministic calculations. Without credentials, the interface explicitly identifies local template/rule operation. Embeddings are optional; without them RAG uses keyword retrieval rather than claiming semantic search.

## PostgreSQL development deployment

```sh
docker compose up --build
```

The compose configuration starts PostgreSQL with pgvector and binds the application to localhost. It is a **local demo configuration**, not a production deployment. The database and artifact stores use persistent volumes; `database/` is mounted read-only.

For production, use approved hosting, set strong database credentials, configure tenant-scoped API keys, terminate HTTPS at the ingress, and disable demo seeding. In the UI, set the session API key under workspace settings. Engineer, viewer, reviewer and administrator permissions are enforced server-side. The shared on-disk inbox belongs to `TENDER_DATABASE_TENANT`; other tenants upload their own documents. Use one app worker for the SQLite development configuration.

The first run creates relational tables and LangGraph checkpoint tables. PostgreSQL setup needs permission to install `vector` or a DBA must install it first. Subsequent schema changes require migrations; this initial release does not silently transform an existing external database.

## Test and evaluate

## Evaluation reports

Every completed, failed, or paused estimate writes a read-only checkpoint evaluation workbook to `outputs/`. It contains trace timing, retrieval/evidence and pricing detail, findings, and reviewer feedback columns. Workbook feedback is imported into the existing review queue only; it never edits an estimate, rate, or package directly.

```sh
uv run tender evaluation-report <revision-id>
```

## Database migrations and tracing

Run `uv run tender db upgrade` at deployment and create an Alembic migration for every SQLAlchemy model change (`uv run tender db revision --message "..."`). Existing pre-Alembic application databases are stamped at the baseline without recreating tables; LangGraph checkpoint tables remain LangGraph-managed.

Optional self-hosted Langfuse tracing uses `TENDER_TRACING_ENABLED`, host, public/secret keys, and `TENDER_TRACING_REDACT_TEXT`. Tracing failures are non-fatal and credentials are never included in trace metadata.

```sh
uv run pytest -q
uv run ruff check src tests
uv run tender evaluate examples/evaluation-cases.json
```

Evaluation creates separate project revisions and compares them with supplied reference labels. The included cases use synthetic data to check workflow behavior. Add engineer-reviewed historical cases before evaluating actual quantity or price accuracy. The evaluator reports omissions, numeric errors, evidence coverage, token usage and latency. Model pricing is not hardcoded; cost per run should be calculated from the organization's contracted model rates.

Optional browser verification, with the app already running:

```sh
uv run python tests/browser_smoke.py
```

The browser script uses an installed Chrome or Playwright Chromium and writes screenshots under `test-results/`.

## Project structure

```text
database/                 Your source document inbox
src/tender/
  app.py                  API, access control and static workspace
  workflow.py             Persistent checkpoints, routing and review interrupts
  agents.py               Specialist responsibilities and verification
  engines.py              Geometry, measurements and Decimal arithmetic
  knowledge.py            Exact rate lookups and hybrid retrieval
  ingestion.py            Incremental source indexing and version history
  providers.py            Bounded model-provider adapter
  research.py             Controlled web discovery and candidate storage
  db.py / storage.py      Relational state and immutable snapshots
  exports.py              BOQ, reports and concept drawings
  evaluation.py           Offline reference-case evaluation
  static/                 Browser workspace
tests/                    Behavioral, integration and browser checks
examples/                 Reference cases and generated package examples
var/                      Local databases and artifacts (gitignored)
```

Read [architecture and operational behavior](docs/architecture.md) for the data contracts, retry policy and remaining integration boundaries.

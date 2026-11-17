# Presentation checklist and known-good example

Run everything from this folder: `/Users/rudragupta/Desktop/BTP/btp2/TendorWorks`.

## Start

```sh
uv sync --frozen
# Fresh clone only: copy .env.ollama.example to .env if .env does not exist.
ollama list
# Only if the Ollama app/server is not already running:
ollama serve
```

In a second terminal:

```sh
cd /Users/rudragupta/Desktop/BTP/btp2/TendorWorks
uv run tender ingest
uv run tender serve --port 8000
```

If `uv` is not on PATH on this Mac, use `/Users/rudragupta/.local/bin/uv` instead. Stop an older server with Ctrl+C before binding the same port. The assistant's preview server uses port 8001 to avoid taking over an existing 8000 process.

## Browser demonstration

1. Open `http://127.0.0.1:8000` and choose **CPWD official-rate demo**.
2. Leave the prefilled authority, scope, office type, Delhi location, 300 m², single floor, 3.60 m height, and 2025 dates unchanged.
3. Set correction attempts to 2. Optionally enable the design-review pause to demonstrate human review.
4. Submit. Local model reviews can take several minutes; the workflow UI polls progress.
5. Show scope/quantity, pricing and evidence checkpoints; open the source register and basic drawing.
6. Show the defined-scope total **INR 11,028,540** and export the BOQ. Explain the exclusions rather than calling it a complete construction budget.
7. To show interruption control, click **Skip remaining retries** during a run; it does not terminate a current model call or remove blockers.

The JSON version of the exact brief is `examples/cpwd-office-demo.json`. The original **Explore a sample estimate** demonstrates a synthetic CPWD school; railway-building and Maharashtra PWD synthetic packages also remain available. Downloaded real railway/PWD references are intentionally not indexed.

## Repeatable command-line demonstration

```sh
uv run python scripts/run_demo.py
```

This preserves the project in the local database, prints a revision URL, saves `outputs/demo-result.json`, creates exports and logs agent answers. Exit code 2 means a live model failed even if deterministic pricing completed; do not present that as successful LLM execution.

For a fast fallback presentation explicitly labelled **deterministic mode**:

```sh
uv run python scripts/run_demo.py --offline
```

## Show evaluations

```sh
uv run pytest -q
uv run python -m tender.benchmarks --provider offline --model offline --layer workflow
uv run python -m tender.benchmarks --dataset eval/datasets/model-comparison-v3.json --model qwen2.5:3b
```

Saved measurements and two-model comparisons are in `eval/results/` and `report/MEASURED_RESULTS.md`. `evals_final.md` explains metric definitions and limits. The revised academic report is authored in LaTeX and compiled to PDF; build instructions are in `report/BUILD.md`. The earlier Word edition is archived.

## Troubleshooting

- **Skipped files:** expected when their bytes and metadata have not changed.
- **Missing domain package:** use the matching CPWD preliminary scope and Delhi/office fields; the demo package is excluded in production mode.
- **PAR basis mismatch:** this example is at the fixed 2025 basis and 3.60 m floor height; current-year escalation is not guessed.
- **Model unavailable:** verify `ollama list`, the exact model tag in `.env`, and the server at port 11434. Restart Tenderworks after changing `.env`.
- **Web unavailable:** publisher/network failure is reported; the downloaded local CPWD snapshot still supports the demonstration. The app does not pretend failed web calls succeeded.
- **LangSmith key missing:** local experiments need no key. Only `--upload` requires credentials.

A tested scenario cannot guarantee execution on every machine or during every service failure. The offline check separates data/calculation failures from model/runtime failures.

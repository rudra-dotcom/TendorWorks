# Academic report build

`FINAL_REPORT.tex` is the canonical revised report; `FINAL_REPORT.pdf` is compiled from it using Tectonic. The previous Markdown/Word edition is retained in `archive/` and is not the revised submission. The historical `MEASURED_RESULTS.md` is an experiment inventory, not the narrative report.

## Prerequisites

Run from the repository root, with the application environment installed:

```sh
uv sync --frozen
uv pip install -r report/requirements-report.txt
npm install --prefix .cache/report-tools @mermaid-js/mermaid-cli@12.2.0
```

The tested renderer is the version recorded in `tool_versions.json`; use that exact version if it differs from the illustrative npm command above. Install Tectonic 0.17.0 using its official release for your platform or an appropriate package manager. The build finds `tectonic` on PATH or at `.cache/report-tools/bin/tectonic`. `TECTONIC` and `MMDC` environment variables may override executable paths.

Mermaid CLI requires a working Chromium installation. `PUPPETEER_CONFIG` can point to a Puppeteer JSON configuration. The local Mac build uses Google Chrome through `.cache/report-tools/puppeteer.json`; that machine-specific file is not required on another machine if the CLI's managed browser works.

## Build

```sh
.venv/bin/python scripts/build_final_report.py
```

The build performs these ordered steps:

1. Recompute stored per-case scores, verify macro means/counts/latency summaries, check matched experiment hashes and downloaded document fingerprints.
2. Write `evaluation_audit.json`, generated LaTeX tables and Matplotlib vector figures.
3. Render the editable Mermaid diagrams in `diagrams/` to vector PDF.
4. Compile `FINAL_REPORT.tex`, including its contents list, figures, tables and cross-links, into `FINAL_REPORT.pdf`.

No model requests, dataset edits or new experiments occur during this build. The primary comparison selects `v3-qwen-agents` and `v3-gemma-agents`; other experiment directories are audited but are not pooled into the primary sample. PNG chart previews accompany vector PDF figures.

The audit verifies numerical consistency against the current evaluator, not independent correctness of engineering labels. Compilation requires network access on the first Tectonic run to populate its TeX package cache. Generated TeX logs are diagnostic artifacts and may contain harmless underfull-box warnings; overfull boxes should be resolved before submission.

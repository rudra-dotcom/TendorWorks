# Source document inbox

Put your source PDFs, TXT/Markdown, DOCX, CSV, XLSX, JSON, or validated `*.pack.json`
domain packages here. This README is ignored by ingestion.

The app scans this directory at startup and before an estimate starts. A SHA-256
digest of file bytes **and metadata** identifies its version. Unchanged files are
skipped; new or changed files are extracted, snapshotted, chunked and indexed.
Earlier versions stay available for estimates that already reference them.

For `rates.pdf`, optionally add `rates.pdf.meta.json`:

```json
{
  "title": "Your schedule title",
  "authority": "cpwd",
  "state": "Delhi",
  "discipline": "civil",
  "version": "2026",
  "effective_from": "2026-01-01",
  "url": "https://the-official-source.example/document.pdf",
  "kind": "schedule"
}
```

Files without metadata are still indexed as unclassified candidates. Searchable
text does not become an approved official rate automatically. Import a structured
domain package to connect verified source rows to measurement recipes and rates;
then review it through the knowledge screen. Scanned PDFs without extractable text
are reported as requiring OCR; the app does not guess their contents.

See `examples/` and `docs/ingestion.md` for structured formats. Do not place API keys
or other secrets in this directory. In production, configure this folder for one
named tenant using `TENDER_DATABASE_TENANT`; uploaded sources stay tenant-scoped.

## Included final CPWD scenario

`cpwd/PAR_2025.pdf` is a downloaded CPWD publication hosted by the official Railway Board. Its metadata preserves the source URL. `cpwd/office-preliminary.pack.json` contains a deliberately limited, demonstration-only office preliminary estimate using transcribed PAR rates. It is not an approved government package. Select the **CPWD official-rate demo** in the UI, or use `examples/cpwd-office-demo.json`.

Railway and Maharashtra PWD references live under `reference_documents/`, outside ingestion. The original large DAR volume was preserved there under `cpwd/` to avoid the inbox size/extraction limits. See `docs/DATA_SOURCES.md` for provenance and exact coverage.

# Source ingestion and domain packages

## Incremental RAG ingestion

`database/` is the inbox. The application scans it before any estimation node runs. Each file version is identified by a hash of **file bytes plus the exact metadata bytes**. Changing metadata therefore triggers re-indexing as well as changing a file's content.

The document bytes are stored under a content-addressed object key. Extracted text preserves PDF page markers, document tables, spreadsheet headers and row numbers. Overlapping chunks keep nearby qualifiers together. Previous inbox versions stay in storage but cease to be current retrieval candidates. An ingestion error is recorded rather than silently marked as indexed.

Source files are not deleted or rewritten by the application. PDFs without usable text need OCR before ingestion. XLSX cells are read as stored values; spreadsheet formulas are never executed.

## Review-only PDF draft packs

When a new or changed PDF has `kind` `schedule`, `specification`, `rule`, or `norms`, TenderWorks can create a candidate package only when `TENDER_NVIDIA_API_KEY` and `TENDER_NVIDIA_CHAT_MODEL` are configured. It uses page-aware table extraction and ChatNVIDIA to propose rows, then rejects rows whose item code, value, or quoted source text is absent from the cited page. Generated `*.pack.json` and `*.review.xlsx` files go to `drafts/`, never `database/`, and remain `candidate` status.

The spreadsheet lists rejected, conflicting, unmapped, and OCR-failed pages. Check the **approved** column, then rebuild a package containing only approved rows:

```sh
uv run tender draft-packs
uv run tender draft-packs --rebuild drafts/example.review.xlsx --pack drafts/example.pack.json
```

Measurement formulas are copied from the template and explicitly marked as needing review. A generated package must still be imported and approved through the existing admin flow; draft generation never approves or imports it.

## Optional metadata

For `cpwd-rates.pdf`, create `cpwd-rates.pdf.meta.json`:

```json
{
  "title": "Verified schedule title",
  "authority": "cpwd",
  "state": "Delhi",
  "discipline": "civil",
  "version": "edition-and-correction-identifier",
  "effective_from": "2026-01-01",
  "effective_to": null,
  "kind": "schedule",
  "url": "https://official-source.example/schedule.pdf"
}
```

Allowed authorities are `cpwd`, `railway`, `state_pwd`, and `unknown`. A document without metadata remains a searchable, unclassified candidate. Its date placeholder is explicitly not evidence of legal applicability. Raw metadata cannot self-approve a source.

## Structured rate packages

A package binds a particular authority, location/state, work category and period to:

- complete source documents and versions;
- supported concept templates and explicit design defaults;
- component descriptions, exact specifications and units;
- measurement recipes and quantity-basis labels;
- scheduled rates or non-scheduled resource analyses;
- scope requirements and adjustment rules;
- optionally, normalized historical comparables.

Generate a full example and the machine-readable schema:

```sh
uv run tender demo-package examples/synthetic-building.pack.json
uv run tender schema > examples/domain-package.schema.json
```

The generated example is synthetic, not a source of government prices. Replace it with verified data under a new package ID. Import a real `*.pack.json` by placing it in the inbox or uploading it as an administrator. Imported packages enter `candidate` status. Inspect and approve them through the knowledge library after checking their source rows, rules, dates and recipes.

Exact rate records require:

```json
{
  "id": "schedule-row-unique-id",
  "item_code": "preserve-the-original-code-as-text",
  "component_key": "masonry",
  "description": "Complete item description including parent qualifications",
  "unit": "m3",
  "specification": {"material": "the-verified-material", "grade": "the-verified-grade"},
  "value": "123.456789",
  "basis": "scheduled",
  "cost_behavior": "quantity",
  "source_id": "source-document-id-in-this-package",
  "locator": "Volume, page, table, row and original item code",
  "effective_from": "2026-01-01",
  "inclusions": ["materials", "labour"],
  "exclusions": ["tax"]
}
```

The numeric value above illustrates the format only. Amounts use `Decimal`; rate matching requires equality of the entire specification dictionary and unit. A revised grade therefore cannot reuse a similar-looking rate.

A non-scheduled rate uses `basis: "non_scheduled"` and a `resources` array. Every resource contains consumption, unit, unit rate, source ID and locator. The rate engine sums the resource amounts and records each calculation. Unsupported resources leave the item unresolved.

## Measurement recipes

`measurement` accepts only names, decimal numbers, `+`, `-`, `*`, `/`, unary minus and parentheses. Calls, attributes and executable code are rejected. Available geometry metrics are:

`gross_floor_area`, `net_floor_area`, `roof_area`, `footprint`, `wall_volume`, `wall_finish_area`, `door_area`, `window_area`, `room_count`, `perimeter`, `floors`, `height`, `duration_months`, `capacity`, `site_area`, `wet_area`.

Recipes distinguish `concept_derived` from `template_allowance`. The bundled geometric measurements use net opening deductions; these are demonstration conventions, not universal CPWD measurement rules. A domain expert must verify imported measurement conventions against the applicable source. Supplied quantities override recipe quantities for that component and retain their user-input provenance.

## Versions and adoption

A package's ID and version identify immutable content. Re-importing identical content is harmless; changing an existing version fails with an instruction to increment the version. Package supersession uses `supersedes: "old-package-id@old-version"`; rate correction supersession uses the old rate record ID. Two applicable, unsuperseded matches are treated as a conflict, never averaged.

Represent a composite project through an authority-specific package containing the adopted sources and an explicit adoption rule. Sources can come from different authorities, while their applicability is determined by the reviewed project package. Unconfigured combinations are reported as missing or conflicting packages. A package containing prices for a bridge does not automatically enable bridge geometry generation.

## Retrieval and embeddings

Without an embedding service, retrieval uses BM25-style keyword scoring over current, tenant-accessible chunks. Configure `TENDER_EMBEDDING_URL` to add semantic retrieval. The adapter sends:

```json
{"texts": ["first chunk", "second chunk"]}
```

It expects:

```json
{"vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
```

The actual vector dimension is provider-defined and must be consistent. PostgreSQL stores vectors in pgvector; SQLite stores arrays for local testing. The gateway merges keyword and cosine rankings with reciprocal rank fusion after tenant/date/authority filtering. Enabling embeddings does not retroactively embed unchanged files; reindex the documents under a new metadata version, or import a new package version. Large deployments should replace the in-process ranker with indexed database/search queries while keeping the same gateway contract.

## Failed, changed and deleted files

Failed files are retried on the next scan. Changed files are stored as new source versions. Removing an inbox file does not delete knowledge or revoke an approved package; source withdrawal must be a deliberate version/review action so historical estimates remain reproducible. The knowledge screen shows the indexed source versions and their status.

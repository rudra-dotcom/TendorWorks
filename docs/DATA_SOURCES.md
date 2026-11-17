# Data provenance and demonstrated coverage

Downloaded/checked on 17 November 2026. `reference_documents/download_manifest.json` records exact URLs, file sizes and SHA-256 hashes. `scripts/download_sources.py` reuses local PDF snapshots or downloads missing files with TLS and PDF-byte checks.

| Document | Publisher / access route | Stored path | Indexed? |
|---|---|---|---|
| CPWD Plinth Area Rates 2025 | CPWD publication hosted by official Railway Board | `database/cpwd/PAR_2025.pdf` | Yes |
| Adoption of CPWD DSR 2023, 13 November 2025 | Railway Board | `reference_documents/railway/CPWD_adoption_2025.pdf` | No |
| Maharashtra State Schedule of Rates 2022–23 | Maharashtra PWD official government CDN | `reference_documents/state_pwd/Maharashtra_SSR_2022_23.pdf` | No |
| DAR Vol. I updated December 2021 | Existing user-provided file; origin not independently downloaded here | `reference_documents/cpwd/DAR_Vol1_UPDATE_DEC_2021.pdf` | No; preserved from original inbox |

Official links:
- [CPWD PAR 2025 PDF](https://rb.indianrailways.gov.in/uploads/directorate/civil_engg/2025/PLINTH_AREA_RATES_2025%20%281%29.pdf)
- [Railway Board publication index and adoption notice](https://rb.indianrailways.gov.in/show-directorate/preview/169)
- [Maharashtra PWD SSR publication page](https://pwd.maharashtra.gov.in/en/publication/state-schedule-of-rate-2022-2023/)

The direct CPWD endpoint returned an HTML rejection instead of a PDF. The official Railway Board copy was fetched successfully without disabling TLS verification. Earlier regional railway URLs returned 403; the Board adoption notice was downloaded instead. These failures are availability problems, not reasons to label an arbitrary mirror authoritative.

## CPWD demo basis

`office-preliminary.pack.json` deliberately covers a narrow **preliminary, scope-limited office estimate**, not a complete detailed tender or DSR item take-off. PAR is an area-rate method. It is incorrect to call its composite shell amount a measured reinforcement/foundation BOQ.

The example uses a 300 m² single-storey Delhi office, a 3.60 m storey, 2025 base rates, and explicitly assumed fire systems. The shell rate is PAR item 1.1.1 (offices), with separate 1.5.1 and 1.6.1 provisions; internal water and electric additions follow 2.1 and 2.3 on shell cost only. PDF-page locators are stored per value. The table transcriptions are checked by the preparation script against extracted page content.

The resulting defined-scope arithmetic is:

- Shell: 300 × 30,920 = INR 9,276,000.
- Assumed downcomer: 300 × 460 = INR 138,000.
- Assumed manual alarm: 300 × 280 = INR 84,000.
- Internal water: 4% × 9,276,000 = INR 371,040.
- Internal electricity: 12.5% × 9,276,000 = INR 1,159,500.
- **Defined-scope preliminary total: INR 11,028,540 (1.102854 crore).**

External connections/development, local approvals, land, lifts, HVAC, solar, TPQA, consultancy and escalation are outside this example's scope. No extra tax is inferred; commercial tax treatment needs review. The assumed fire-system selection is not a fire-compliance decision. Gross floor area is a provisional plinth-area measurement and requires checking against Annexure V. Changing execution year or storey height produces a visible applicability finding rather than pretending to calculate a supported adjustment.

## Ingestion

Startup and workflow ingestion hashes file bytes plus metadata; unchanged files are skipped. PDFs are extracted with pypdf, split into retrievable chunks, and stored with immutable snapshots. Keyword/BM25 retrieval works without an embedding server. Optional embedding integrations remain available; this measured demonstration does not claim semantic-vector retrieval. No OCR is performed. The original 19 MB DAR volume was archived intact because the inbox has a 15 MB upload limit and a 500,000-character extraction limit; it was not silently truncated or deleted.

Only `database/` is scanned. Reference documents for other authorities stay outside it, as requested. Existing synthetic railway/PWD fixtures may still be used for clearly labelled sample runs; this is not evidence of real-data coverage for those authorities.

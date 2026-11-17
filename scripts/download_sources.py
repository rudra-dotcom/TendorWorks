"""Download official source snapshots with TLS checks, PDF validation and provenance.
Other-authority files stay outside database/. Re-running reuses verified local files.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    (
        "database/cpwd/PAR_2025.pdf",
        "https://rb.indianrailways.gov.in/uploads/directorate/civil_engg/2025/PLINTH_AREA_RATES_2025%20(1).pdf",
        True,
    ),
    (
        "reference_documents/railway/CPWD_adoption_2025.pdf",
        "https://rb.indianrailways.gov.in/uploads/directorate/civil_engg/2025/2025_11_13%20Adoption%20of%20CPWD%20Delhi%20Schedules%20of%20Rates-%202023%20(DSR-Vol_%20I,%20DSR-Vol_%20II,%20Analysis%20of%20Rates%20for%20DSR%20(AOR-Vol_I,%20AOR-Vol_II)_pdf.pdf",
        False,
    ),
    (
        "reference_documents/state_pwd/Maharashtra_SSR_2022_23.pdf",
        "https://cdnbbsr.s3waas.gov.in/s3ea80421fc06a2ed5c7adc1018e0026df/uploads/2025/07/202507031303590066.pdf",
        False,
    ),
]


def main():
    records = []
    for relative, url, ingest in SOURCES:
        path = ROOT / relative
        if not path.is_file() or not path.read_bytes().startswith(b"%PDF"):
            response = httpx.get(url, timeout=90, follow_redirects=True)
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError(f"{url} did not return PDF bytes")
            if len(raw) > 30_000_000:
                raise ValueError("Source too large")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".download").write_bytes(raw)
            path.with_suffix(".download").replace(path)
        records.append(
            {
                "path": relative,
                "url": url,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
                "in_ingestion_folder": ingest,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    (ROOT / "reference_documents/download_manifest.json").write_text(json.dumps(records, indent=2))
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()

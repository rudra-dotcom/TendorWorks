"""Build a reproducible, source-backed PRELIMINARY demo package, never approve official data."""

import hashlib
import json
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from tender.schemas import (
    Adjustment,
    ComponentRecipe,
    DomainPack,
    RateRecord,
    RuleRequirement,
    SourceDocument,
)

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "database/cpwd/PAR_2025.pdf"
URL = "https://rb.indianrailways.gov.in/uploads/directorate/civil_engg/2025/PLINTH_AREA_RATES_2025%20(1).pdf"


def build():
    reader = PdfReader(PDF)
    texts = {i + 1: p.extract_text() for i, p in enumerate(reader.pages)}
    # Independent transcription checks: refuse to build from a different/block-page PDF.
    for page, values in {
        13: ["1.1.1", "30,920", "3.60"],
        14: ["1.5.1", "460", "1.6.1", "280", "4%"],
        15: ["2.3", "12.5%"],
    }.items():
        assert all(v in texts[page] for v in values), f"Expected source row missing on page {page}"
    source = SourceDocument(
        id="cpwd-par-2025",
        title="CPWD PAR 2025, official Railway Board hosted copy",
        version="2025-base-2025-04-01",
        kind="schedule",
        authority="cpwd",
        effective_from=date(2025, 4, 1),
        url=URL,
        text="\n\n".join(f"[PDF page {n}]\n{t}" for n, t in texts.items()),
        locator="PDF pages 12-15; printed pages 2-5",
        trust="demo",
    )
    assumptions = SourceDocument(
        id="academic-scope-v1",
        title="Academic demonstration scope and geometry assumptions; not official design",
        version="1",
        kind="template",
        authority="cpwd",
        effective_from=date(2025, 4, 1),
        trust="demo",
        text="Restricted demonstration: office, rectangular layout, up to three floors, height 3.60 m, normal foundation. "
        "Gross floor area is assumed equal to measured plinth area; engineer must verify Annexure V. "
        "Scope includes civil building shell, assumed downcomer and manual alarm, internal water and electrical services. "
        "Excludes external connections, local approval charges, external development, land, lifts, HVAC, solar, TPQA, consultancy and escalation. "
        "No tax added: commercial tax basis requires review. Fire system selection is a scenario assumption, not a compliance determination.",
    )
    records = [
        ("building_shell", "1.1.1", "Office RCC framed building, 3.60 m floor height", "30920", 13),
        ("fire_safety", "1.5.1", "Downcomer system, assumed scenario", "460", 14),
        ("fire_alarm", "1.6.1", "Manual fire alarm, assumed scenario", "280", 14),
    ]
    components = []
    rates = []
    for key, code, desc, value, page in records:
        components.append(
            ComponentRecipe(
                key=key,
                category="Preliminary CPWD building scope",
                description=desc,
                unit="m2",
                use="Whole office building; scenario assumptions require review",
                measurement="gross_floor_area",
                quantity_basis="template_allowance",
                allowance_reason="Gross floor area used as provisional plinth area; not certified measurement",
                source_id=assumptions.id,
                locator="Academic scope v1",
                specification={"basis": "PAR2025-office-3.6m"},
            )
        )
        rates.append(
            RateRecord(
                id="par-" + code,
                item_code=code,
                component_key=key,
                description=desc,
                unit="m2",
                value=value,
                specification={"basis": "PAR2025-office-3.6m"},
                source_id=source.id,
                locator=f"PDF page {page}; item {code}; offices column",
                effective_from=date(2025, 4, 1),
                inclusions=["PAR composite item"],
                exclusions=["separately listed services"],
            )
        )
    pack = DomainPack(
        id="cpwd-par-office-demo",
        version="1.0",
        name="CPWD PAR 2025 office preliminary scope - academic demonstration",
        authority="cpwd",
        states=["Delhi"],
        work_categories=["preliminary_cpwd"],
        supported_buildings=["office"],
        effective_from=date(2025, 4, 1),
        trust="demo",
        documents=[source, assumptions],
        components=components,
        rates=rates,
        default_source_id=assumptions.id,
        design_defaults={
            "floor_area": "300",
            "floors": "1",
            "height": "3.6",
            "aspect_ratio": "1.5",
            "wall_thickness": "0.23",
            "partition_thickness": "0.115",
            "corridor_width": "2",
        },
        rules=[
            RuleRequirement(
                id="preliminary-only",
                text=assumptions.text,
                source_id=assumptions.id,
                locator="Scope v1",
                required_components=["building_shell", "fire_safety", "fire_alarm"],
            )
        ],
        adjustments=[
            Adjustment(
                id="water",
                label="PAR 2.1 internal water and sanitary installations",
                kind="other",
                percent="4",
                component_keys=["building_shell"],
                source_id=source.id,
                locator="PDF page 14, item 2.1, offices 4%",
                effective_from=date(2025, 4, 1),
                group="water",
            ),
            Adjustment(
                id="electrical",
                label="PAR 2.3 internal electric installations",
                kind="other",
                percent="12.5",
                component_keys=["building_shell"],
                source_id=source.id,
                locator="PDF page 15, item 2.3, offices 12.5%",
                effective_from=date(2025, 4, 1),
                group="electrical",
            ),
        ],
    )
    (ROOT / "database/cpwd/office-preliminary.pack.json").write_text(pack.model_dump_json(indent=2))
    PDF.with_name(PDF.name + ".meta.json").write_text(
        json.dumps(
            {
                "title": source.title,
                "authority": "cpwd",
                "version": source.version,
                "kind": "schedule",
                "effective_from": "2025-04-01",
                "url": URL,
            },
            indent=2,
        )
    )
    # Existing user-supplied large DAR is preserved outside the active inbox. Index page-bounded excerpts.
    dar = ROOT / "database/DAR_Vol1_UPDATE_DEC_2021.pdf"
    archive = ROOT / "reference_documents/cpwd/DAR_Vol1_UPDATE_DEC_2021.pdf"
    if dar.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        dar.rename(archive)
    manifest = []
    for path in [
        PDF,
        ROOT / "reference_documents/railway/CPWD_adoption_2025.pdf",
        ROOT / "reference_documents/state_pwd/Maharashtra_SSR_2022_23.pdf",
        archive,
    ]:
        if path.exists():
            assert path.read_bytes().startswith(b"%PDF"), str(path)
            manifest.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                    "ingested": path == PDF,
                    "retrieval_date": "2026-11-17",
                    "url": URL
                    if path == PDF
                    else (
                        "user-supplied; original download not verified"
                        if path == archive
                        else "See docs/DATA_SOURCES.md"
                    ),
                }
            )
    (ROOT / "reference_documents/manifest.json").write_text(json.dumps(manifest, indent=2))
    brief = {
        "title": "CPWD office preliminary demo",
        "description": "Prepare a CPWD preliminary estimate for a 300 m2 single-storey office in New Delhi. RCC frame, 3.60 m height, downcomer and manual alarm scenario, internal water and electrical services only. Exclude external works, land, lifts, HVAC, consultancy, TPQA and escalation.",
        "authority": "cpwd",
        "state": "Delhi",
        "location": "New Delhi",
        "work_category": "preliminary_cpwd",
        "building_type": "office",
        "floor_area": "300",
        "length": "20",
        "width": "15",
        "floors": 1,
        "height": "3.6",
        "capacity": 30,
        "duration_months": "12",
        "estimate_date": "2025-07-31",
        "execution_year": 2025,
        "correction_limit": 2,
        "allow_demo": True,
    }
    (ROOT / "examples/cpwd-office-demo.json").write_text(json.dumps(brief, indent=2))
    print("Created CPWD source-backed demonstration package and project brief.")


if __name__ == "__main__":
    build()

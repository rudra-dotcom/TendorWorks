from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from tender.drafts import DraftPackGenerator
from tender.schemas import DomainPack


def test_draft_generation_rejects_fabrication_and_rebuilds_approved_rows(settings, monkeypatch, tmp_path):
    settings.nvidia_api_key = "fake"
    settings.nvidia_chat_model = "fake-model"
    settings.drafts_dir = tmp_path / "drafts"
    generator = DraftPackGenerator(settings)
    monkeypatch.setattr(
        "tender.drafts.pdf_pages",
        lambda _: [(1, "MASONRY\n1.01 Brick masonry m3 6000", None), (2, "", "No extractable text; OCR required")],
    )
    generator.extract_rows = lambda _: [
        {"item_code": "1.01", "description": "MASONRY Brick masonry", "unit": "m3", "value": "6000", "page": 1, "source_text": "1.01 Brick masonry m3 6000"},
        {"item_code": "9.99", "description": "Invented row", "unit": "m3", "value": "9000", "page": 1, "source_text": "not on page"},
    ]
    path = tmp_path / "rates.pdf"
    result = generator.generate(
        path,
        {"kind": "schedule", "authority": "cpwd", "effective_from": date(2026, 1, 1)},
        b"small synthetic pdf",
    )
    pack = DomainPack.model_validate_json(Path(result["pack"]).read_text())
    assert result["status"] == "drafted"
    assert len(pack.rates) == 1 and pack.rates[0].item_code == "1.01"
    book = load_workbook(result["review"])
    rows = list(book["Review"].iter_rows(min_row=2, values_only=True))
    assert any(str(row[0]).startswith("rejected") for row in rows)
    assert book["Extraction issues"].max_row == 2
    book["Review"].cell(2, 2).value = True
    book.save(result["review"])
    approved = generator.rebuild_approved(Path(result["review"]), Path(result["pack"]))
    assert len(DomainPack.model_validate_json(approved.read_text()).rates) == 1

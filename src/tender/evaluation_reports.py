"""Read-only per-revision evaluation workbooks and feedback import."""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from tender.schemas import EstimateResult

FEEDBACK = ["correct", "corrected value", "comment"]


def _sheet(book, name, headers, rows):
    ws = book.create_sheet(name)
    ws.append(headers + FEEDBACK)
    for row in rows:
        ws.append(row + ["", "", ""])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="183E39")
        cell.font = Font(color="FFFFFF", bold=True)
    validation = DataValidation(type="list", formula1='"Y,N"')
    ws.add_data_validation(validation)
    validation.add(f"{chr(64 + len(headers) + 1)}2:{chr(64 + len(headers) + 1)}1048576")
    ws.conditional_formatting.add(
        f"{chr(64 + len(headers) + 1)}2:{chr(64 + len(headers) + 1)}1048576",
        CellIsRule(operator="equal", formula=['"N"'], fill=PatternFill("solid", fgColor="FFC7CE")),
    )
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width = min(
            55, max(12, max(len(str(c.value or "")) for c in column) + 2)
        )
    return ws


def write_evaluation_workbook(result: EstimateResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.remove(book.active)
    trace = result.agent_trace
    _sheet(
        book,
        "Summary",
        ["stable ID", "field", "value"],
        [
            ["revision", "project", result.project_id],
            ["revision", "revision", result.revision],
            ["revision", "status", result.status],
            ["revision", "pack", f"{result.pack_id or ''}@{result.pack_version or ''}"],
            ["revision", "total", str(result.base_total)],
            ["revision", "retrieval", str(result.metrics.get("retrieved_chunks", 0))],
        ]
        + [
            [f"trace:{i}", t["role"], f"{t.get('duration_ms', 0)}ms; {t.get('usage', {})}"]
            for i, t in enumerate(trace)
        ],
    )
    _sheet(
        book,
        "CP1 - Intake",
        ["stable ID", "field", "value", "method", "quote"],
        [[f"brief:{k}", k, str(v), "explicit", ""] for k, v in result.brief.model_dump(mode="json").items()],
    )
    _sheet(
        book,
        "CP1 - Retrieval",
        ["stable ID", "document", "page", "score", "confidence", "cited"],
        [
            [
                e.id,
                e.title,
                e.locator,
                "",
                "high" if e.kind == "retrieved" else "",
                "yes" if e.id in {x for b in result.boq for x in b.evidence_ids} else "no",
            ]
            for e in result.evidence
            if e.kind == "retrieved"
        ],
    )
    _sheet(
        book,
        "CP1 - Scope & Design",
        ["stable ID", "kind", "value", "source", "status"],
        [
            [
                b.id,
                "component",
                f"selected={b.selected}; {b.description}",
                ", ".join(b.evidence_ids),
                b.status,
            ]
            for b in result.boq
        ]
        + [[a.id, "assumption", a.value, ", ".join(a.source_ids), a.status] for a in result.assumptions]
        + [
            [f"metric:{k}", "design metric", str(v), "design:model", ""]
            for k, v in (result.design.metrics.items() if result.design else [])
        ],
    )
    calcs = {c.id: c for c in result.calculations}
    _sheet(
        book,
        "CP1 - Quantities",
        ["stable ID", "formula", "inputs", "quantity", "basis"],
        [
            [
                b.id,
                calcs[b.quantity_calculation_id].formula if b.quantity_calculation_id in calcs else "",
                str(calcs[b.quantity_calculation_id].inputs) if b.quantity_calculation_id in calcs else "",
                str(b.quantity),
                b.quantity_basis,
            ]
            for b in result.boq
        ],
    )
    _sheet(
        book,
        "CP2 - Pricing",
        ["stable ID", "rate", "item code", "source page", "status"],
        [[b.id, str(b.unit_rate), b.item_code or "", ", ".join(b.evidence_ids), b.status] for b in result.boq]
        + [
            [a.id, str(a.amount), "adjustment", ", ".join(a.evidence_ids), a.scenario]
            for a in result.adjustments
        ],
    )
    _sheet(
        book,
        "CP3 - Evidence",
        ["stable ID", "kind", "chain", "audit", "confidence"],
        [[e.id, e.kind, ", ".join(e.parent_ids), "present", e.trust] for e in result.evidence],
    )
    _sheet(
        book,
        "Findings",
        ["stable ID", "checkpoint", "severity", "code", "message", "item"],
        [
            [f"finding:{i}", f.checkpoint, f.severity, f.code, f.message, f.item_id or ""]
            for i, f in enumerate(result.findings)
        ],
    )
    path = (
        output_dir
        / f"{result.project_id}-rev{result.revision}-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    )
    book.save(path)
    return path


def import_feedback(path: Path, revision_id: str, create):
    book = load_workbook(path, data_only=True)
    count = 0
    for sheet in book.worksheets:
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) < 4 or row[-3] not in {"Y", "N"} or not (row[-2] or row[-1]):
                continue
            category = (
                "price"
                if "Pricing" in sheet.title
                else "quantity"
                if "Quantities" in sheet.title
                else "source"
                if "Evidence" in sheet.title
                else "scope"
            )
            create(
                category,
                str(row[0]),
                str(row[-1] or "Workbook correction"),
                str(row[-2]) if row[-2] is not None else None,
            )
            count += 1
    return count

"""Reports are rendered from validated artifacts, never written independently by a model."""

import io
import json
import zipfile
from html import escape

import ezdxf
from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from tender.engines import drawing_svg
from tender.schemas import EstimateResult
from tender.storage import ObjectStore


def status_line(result: EstimateResult) -> str:
    if result.brief.work_category == "preliminary_cpwd":
        return "SCOPE-LIMITED PRELIMINARY ESTIMATE • ENGINEERING REVIEW REQUIRED"
    return (
        "ILLUSTRATIVE RATE DATA — " if result.demo else ""
    ) + "CONCEPT-BASED DRAFT • ENGINEERING REVIEW REQUIRED"


def total_label(result: EstimateResult) -> str:
    return (
        (
            "Defined-scope preliminary total"
            if result.brief.work_category == "preliminary_cpwd"
            else "Estimated total"
        )
        + f": INR {result.base_total:,.2f}"
        if result.base_total is not None
        else f"Incomplete estimate — known line-item subtotal: INR {result.known_subtotal:,.2f}"
    )


def sheet_rows(result: EstimateResult):
    headers = [
        "Item",
        "Category",
        "Description",
        "Use / location",
        "Unit",
        "Quantity",
        "Quantity basis",
        "Rate (INR)",
        "Amount (INR)",
        "Selected",
        "Classification",
        "Rate basis",
        "Item code",
        "Specification",
        "Elements",
        "Evidence",
        "Status",
    ]
    rows = [
        [
            b.id,
            b.category,
            b.description,
            b.use,
            b.unit,
            b.quantity,
            b.quantity_basis,
            b.unit_rate,
            b.amount,
            b.selected,
            b.classification,
            b.rate_basis,
            b.item_code,
            json.dumps(b.specification),
            ", ".join(b.element_ids),
            ", ".join(b.evidence_ids),
            b.status,
        ]
        for b in result.boq
    ]
    return headers, rows


def workbook_bytes(result: EstimateResult) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)

    def sheet(name, headers, rows):
        ws = workbook.create_sheet(name)
        ws.append([result.brief.title])
        ws.append([status_line(result)])
        ws.append([total_label(result)])
        ws.append(headers)
        for row in rows:
            ws.append(row)
        for row in ws:
            for cell in row:
                # User text must never become an Excel formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in ws[4]:
            cell.fill, cell.font = PatternFill("solid", fgColor="183E39"), Font(color="FFFFFF", bold=True)
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = min(
                70, max(16, len(str(column[3].value)) + 3)
            )
        ws.freeze_panes = "F5"
        ws.auto_filter.ref = f"A4:{ws.cell(ws.max_row, ws.max_column).coordinate}"
        return ws

    headers, rows = sheet_rows(result)
    boq = sheet("BOQ", headers, rows)
    for row in boq.iter_rows(min_row=5):
        for i in (5, 7, 8):
            row[i].number_format = "#,##0.00" if i != 5 else "#,##0.000"
    sheet(
        "Sources",
        ["ID", "Kind", "Title", "Version", "Locator", "URL", "Snapshot", "Hash", "Value", "Parents", "Trust"],
        [
            [
                e.id,
                e.kind,
                e.title,
                e.version,
                e.locator,
                e.url,
                e.snapshot_ref,
                e.content_hash,
                e.value[:30000],
                ", ".join(e.parent_ids),
                e.trust,
            ]
            for e in result.evidence
        ],
    )
    sheet(
        "Calculations",
        ["ID", "Formula", "Inputs", "Result", "Unit", "Evidence"],
        [
            [c.id, c.formula, json.dumps(c.inputs), c.result, c.unit, ", ".join(c.evidence_ids)]
            for c in result.calculations
        ],
    )
    sheet(
        "Assumptions",
        ["Field", "Value", "Reason", "Status", "Sources"],
        [[a.field, a.value, a.reason, a.status, ", ".join(a.source_ids)] for a in result.assumptions],
    )
    sheet(
        "Findings",
        ["Checkpoint", "Severity", "Code", "Item", "Finding"],
        [[f.checkpoint, f.severity, f.code, f.item_id, f.message] for f in result.findings],
    )
    sheet(
        "Adjustments",
        ["Label", "Kind", "Scenario", "Percent", "Base", "Amount", "Sources"],
        [
            [a.label, a.kind, a.scenario, a.percent, a.base, a.amount, ", ".join(a.evidence_ids)]
            for a in result.adjustments
        ],
    )
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def report_pdf(result: EstimateResult) -> bytes:
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    story = []

    def p(text, style="BodyText"):
        return Paragraph(escape(str(text)), styles[style])

    story.extend(
        [
            p(result.brief.title, "Title"),
            p(status_line(result)),
            Spacer(1, 12),
            p(total_label(result), "Heading2"),
            p(
                f"Revision {result.revision} | {result.brief.authority.upper()} | {result.brief.location} | Valuation date {result.brief.estimate_date}"
            ),
            p(result.brief.description),
            Spacer(1, 14),
        ]
    )
    if result.design:
        story.append(
            p(
                f"Concept: {result.design.length} × {result.design.width} m, {result.design.floors} floors; gross floor area {result.design.metrics['gross_floor_area']} m²."
            )
        )
    data = [[p(c) for c in ["Item / description", "Unit", "Quantity", "Rate INR", "Amount INR", "Basis"]]]
    for b in result.boq:
        data.append(
            [
                p(b.description + (" [OPTIONAL, NOT SELECTED]" if not b.selected else "")),
                p(b.unit),
                p(b.quantity if b.quantity is not None else "Unresolved"),
                p(b.unit_rate if b.unit_rate is not None else "Unresolved"),
                p(b.amount if b.amount is not None else "Unresolved"),
                p(b.quantity_basis),
            ]
        )
    table = LongTable(data, colWidths=[175, 32, 62, 65, 70, 95], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DFEEE8")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CDD8D3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story += [table, Spacer(1, 12), p("Assumptions and exclusions", "Heading2")]
    story.extend(p(f"{a.field}: {a.value}. {a.reason}") for a in result.assumptions)
    story += [p("Verification findings", "Heading2")]
    story.extend(p(f"{f.severity.upper()} — {f.message}") for f in result.findings)
    story += [p("Source register", "Heading2")]
    story.extend(
        p(f"{e.id} | {e.title} | {e.version} | {e.locator} | {e.url or e.snapshot_ref}")
        for e in result.evidence
        if e.kind == "document"
    )
    story += [p("Item evidence references", "Heading2")]
    story.extend(
        p(f"{b.id}: {', '.join(b.evidence_ids)}; amount calculation {b.amount_calculation_id}")
        for b in result.boq
    )
    SimpleDocTemplate(
        output, pagesize=A4, leftMargin=28, rightMargin=28, topMargin=32, bottomMargin=32
    ).build(story)
    return output.getvalue()


def report_docx(result: EstimateResult) -> bytes:
    doc = Document()
    doc.add_heading(result.brief.title, 0)
    doc.add_paragraph(status_line(result))
    doc.add_heading(total_label(result), 1)
    doc.add_paragraph(
        f"Revision {result.revision}; {result.brief.authority}; {result.brief.location}; {result.brief.estimate_date}"
    )
    doc.add_paragraph(result.brief.description)
    table = doc.add_table(rows=1, cols=6)
    table.style = "Light Shading Accent 1"
    for c, v in zip(
        table.rows[0].cells, ["Description", "Unit", "Quantity", "Rate INR", "Amount INR", "Quantity basis"]
    ):
        c.text = v
    for item in result.boq:
        values = [
            item.description + (" (optional)" if not item.selected else ""),
            item.unit,
            item.quantity,
            item.unit_rate,
            item.amount,
            item.quantity_basis,
        ]
        for c, v in zip(table.add_row().cells, values):
            c.text = str(v) if v is not None else "Unresolved"
    for title, rows in [
        ("Assumptions", [f"{a.field}: {a.value}. {a.reason}" for a in result.assumptions]),
        ("Findings", [f"{f.severity}: {f.message}" for f in result.findings]),
        (
            "Sources",
            [
                f"{e.id}: {e.title}, {e.version}, {e.locator}; {e.url or e.snapshot_ref}"
                for e in result.evidence
                if e.kind == "document"
            ],
        ),
        (
            "Quantity and rate analyses",
            [
                f"{c.id}: {c.formula}; {c.inputs} = {c.result} {c.unit}; sources {c.evidence_ids}"
                for c in result.calculations
            ],
        ),
    ]:
        doc.add_heading(title, 1)
        for text in rows:
            doc.add_paragraph(text)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def drawing_pdf(result: EstimateResult) -> bytes:
    out = io.BytesIO()
    page_width, page_height = landscape(A3)
    c = canvas.Canvas(out, pagesize=(page_width, page_height))
    design = result.design
    scale = min((page_width - 160) / float(design.width), (page_height - 190) / float(design.length))
    for floor in range(design.floors):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, page_height - 45, result.brief.title[:90])
        c.setFont("Helvetica", 10)
        c.drawString(50, page_height - 65, status_line(result))
        c.drawString(
            50,
            page_height - 85,
            f"Floor {floor + 1} | Revision {result.revision} | {design.width} x {design.length} m",
        )
        for kind in ("room", "circulation", "wall", "partition", "door", "window", "exit"):
            for e in design.elements:
                if e.floor != floor or e.kind != kind:
                    continue
                c.setFillColor(
                    colors.HexColor(
                        "#244944"
                        if kind in ("wall", "partition")
                        else "#DDEBE5"
                        if kind == "room"
                        else "#FFFFFF"
                    )
                )
                x, y = (
                    80 + float(e.x) * scale,
                    65 + (float(design.length) - float(e.y) - float(e.length)) * scale,
                )
                w, h = float(e.width) * scale, float(e.length) * scale
                c.rect(x, y, w, h, stroke=0, fill=1)
                if kind == "room":
                    c.setFillColor(colors.HexColor("#183A38"))
                    c.setFont("Helvetica", 9)
                    c.drawCentredString(x + w / 2, y + h / 2, e.label)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 10)
        c.drawString(
            80, 43, f"Width {design.width} m | Length {design.length} m | Storey height {design.height} m"
        )
        c.drawString(
            80,
            28,
            "Concept only. Layout, access, egress, structure and services require engineering validation.",
        )
        c.showPage()
    c.save()
    return out.getvalue()


def drawing_dxf(result: EstimateResult) -> bytes:
    doc = ezdxf.new("R2010")
    doc.units = 6  # metres
    space = doc.modelspace()
    design = result.design
    for e in design.elements:
        if e.kind in {"slab", "roof"}:
            continue
        layer = f"F{e.floor + 1}_{e.kind.upper()}"
        if layer not in doc.layers:
            doc.layers.add(layer)
        x, y = float(e.x) + e.floor * (float(design.width) + 5), -float(e.y)
        w, length = float(e.width), float(e.length)
        space.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y - length), (x, y - length)],
            close=True,
            dxfattribs={"layer": layer},
        )
        if e.kind == "room":
            space.add_text(
                e.label + " [" + e.id + "]",
                dxfattribs={"height": 0.22, "insert": (x + 0.3, y - 0.5), "layer": layer},
            )
    space.add_text("CONCEPT ONLY - NOT FOR CONSTRUCTION", dxfattribs={"height": 0.5, "insert": (0, 3)})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


class ReportCompiler:
    def __init__(self, objects: ObjectStore):
        self.objects = objects

    def compile(self, result: EstimateResult):
        files = {
            "boq.xlsx": workbook_bytes(result),
            "estimate.pdf": report_pdf(result),
            "estimate.docx": report_docx(result),
        }
        if result.design:
            files.update(
                {
                    "concept.svg": drawing_svg(
                        result.design, result.brief.title, result.revision, result.demo
                    ),
                    "concept.pdf": drawing_pdf(result),
                    "concept.dxf": drawing_dxf(result),
                }
            )
        for name, content in files.items():
            result.artifacts[name] = self.objects.put(content)
        files["estimate.json"] = result.model_dump_json(indent=2).encode()
        result.artifacts["estimate.json"] = self.objects.put(files["estimate.json"])
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        result.artifacts["estimate-bundle.zip"] = self.objects.put(bundle.getvalue())

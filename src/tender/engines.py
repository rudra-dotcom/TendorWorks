"""Deterministic geometry and decimal arithmetic. No model executes code or does arithmetic."""

import ast
import operator
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from html import escape

from tender.schemas import Assumption, DesignElement, DesignRevision, DomainPack, ProjectBrief

D = Decimal
MONEY = D("0.01")
MEASURE = D("0.001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def measure(value: Decimal) -> Decimal:
    return value.quantize(MEASURE, rounding=ROUND_HALF_UP)


def formula(expression: str, inputs: dict[str, Decimal]) -> Decimal:
    """Small arithmetic DSL. No eval(), attributes, calls, powers or arbitrary Python."""
    if len(expression) > 600:
        raise ValueError("Measurement expression is too long")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 120:
        raise ValueError("Measurement expression is too complex")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return D(ast.get_source_segment(expression, node))
        if isinstance(node, ast.Name) and node.id in inputs:
            return inputs[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise ValueError("Unknown measurement variable or unsupported expression")

    try:
        with localcontext() as ctx:
            ctx.prec = 32
            result = walk(tree)
        if not result.is_finite() or result < 0 or result > D("1000000000000"):
            raise ValueError("Measurement is negative, non-finite, or outside supported bounds")
        return measure(result)
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("Invalid measurement arithmetic") from exc


def generate_design(brief: ProjectBrief, pack: DomainPack) -> DesignRevision:
    assumptions = []
    defaults = pack.design_defaults

    def choose(field: str, supplied, fallback: str) -> Decimal:
        if supplied is not None:
            return D(str(supplied))
        value = D(defaults.get(field, fallback))
        assumptions.append(
            Assumption(
                id=f"assumption-{field}",
                field=field,
                value=str(value),
                reason="Concept template default; replace with measured project information.",
                source_ids=[pack.default_source_id],
            )
        )
        return value

    floors = int(choose("floors", brief.floors, "1"))
    if floors > pack.max_concept_floors:
        raise ValueError(f"This design template supports at most {pack.max_concept_floors} floors")
    height = choose("height", brief.height, "3.3")
    thickness = D(defaults.get("wall_thickness", "0.23"))
    partition = D(defaults.get("partition_thickness", "0.115"))
    corridor = D(defaults.get("corridor_width", "2"))
    assumptions.append(
        Assumption(
            id="assumption-layout",
            field="layout",
            value=f"Rectangular footprint; {thickness} m exterior walls; {partition} m partitions; {corridor} m corridor",
            reason="Illustrative concept geometry; wall construction, circulation and structural design need validation.",
            source_ids=[pack.default_source_id],
        )
    )
    if brief.length and brief.width:
        length, width = brief.length, brief.width
        if brief.floor_area and abs(length * width * floors - brief.floor_area) > brief.floor_area * D(
            "0.01"
        ):
            raise ValueError(
                "Supplied length × width × floors conflicts with total floor area by more than 1%"
            )
    else:
        area = choose("floor_area", brief.floor_area, "600") / floors
        if brief.length:
            length, width = brief.length, area / brief.length
        elif brief.width:
            width, length = brief.width, area / brief.width
        else:
            ratio = D(defaults.get("aspect_ratio", "1.5"))
            length = (area * ratio).sqrt()
            width = area / length
        length, width = measure(length), measure(width)
        assumptions.append(
            Assumption(
                id="assumption-footprint",
                field="footprint",
                value=f"{length} m × {width} m per floor",
                reason="Footprint inferred from floor area and template proportions.",
                source_ids=[pack.default_source_id],
            )
        )
    if min(length, width) < 8 or max(length, width) > 120 or not D("2.4") <= height <= D("6"):
        raise ValueError(
            "Dimensions fall outside the validated rectangular concept template (8–120 m, height 2.4–6 m)"
        )
    inner_length, inner_width = length - 2 * thickness, width - 2 * thickness
    room_width = (inner_width - corridor - 2 * partition) / 2
    rows = max(1, min(12, int(inner_length / D("5"))))
    room_length = (inner_length - (rows - 1) * partition) / rows
    corridor_x = thickness + room_width + partition
    elements = []

    def element(id_, kind, floor, label, x, y, w, span, h=height):
        elements.append(
            DesignElement(
                id=id_,
                kind=kind,
                floor=floor,
                label=label,
                x=x.quantize(D("0.000001")),
                y=y.quantize(D("0.000001")),
                width=w.quantize(D("0.000001")),
                length=span.quantize(D("0.000001")),
                height=h.quantize(D("0.000001")),
            )
        )

    for floor in range(floors):
        prefix = f"F{floor + 1:02}"
        element(f"{prefix}-SLAB", "slab", floor, "Floor plate", D(0), D(0), width, length, D("0.15"))
        element(
            f"{prefix}-C", "circulation", floor, "Corridor", corridor_x, thickness, corridor, inner_length
        )
        element(f"{prefix}-WN", "wall", floor, "North wall", D(0), D(0), width, thickness)
        element(f"{prefix}-WS", "wall", floor, "South wall", D(0), length - thickness, width, thickness)
        element(f"{prefix}-WW", "wall", floor, "West wall", D(0), thickness, thickness, inner_length)
        element(
            f"{prefix}-WE", "wall", floor, "East wall", width - thickness, thickness, thickness, inner_length
        )
        for side in range(2):
            x = thickness if side == 0 else corridor_x + corridor + partition
            px = corridor_x - partition if side == 0 else corridor_x + corridor
            element(
                f"{prefix}-P{side}",
                "partition",
                floor,
                "Corridor partition",
                px,
                thickness,
                partition,
                inner_length,
            )
            for row in range(rows):
                y = thickness + row * (room_length + partition)
                label = (
                    "Services / WC"
                    if side == 1 and row == rows - 1
                    else "Stair reserve"
                    if floors > 1 and side == 0 and row == rows - 1
                    else f"{'Classroom' if brief.building_type == 'school' else 'Room'} {side * rows + row + 1}"
                )
                element(f"{prefix}-R{side}{row:02}", "room", floor, label, x, y, room_width, room_length)
                element(
                    f"{prefix}-D{side}{row:02}",
                    "door",
                    floor,
                    "Door opening",
                    px,
                    y + D("0.6"),
                    partition,
                    D("0.9"),
                    D("2.1"),
                )
                wx = D(0) if side == 0 else width - thickness
                element(
                    f"{prefix}-V{side}{row:02}",
                    "window",
                    floor,
                    "Window opening",
                    wx,
                    y + room_length / 2 - D("0.75"),
                    thickness,
                    D("1.5"),
                    D("1.2"),
                )
                if row:
                    element(
                        f"{prefix}-P{side}{row:02}",
                        "partition",
                        floor,
                        "Room partition",
                        x,
                        y - partition,
                        room_width,
                        partition,
                    )
        if floor == 0:
            for index, y in enumerate((D(0), length - thickness)):
                element(
                    f"{prefix}-EXIT{index}",
                    "exit",
                    floor,
                    "Concept entry / exit",
                    corridor_x + (corridor - D("1.5")) / 2,
                    y,
                    D("1.5"),
                    thickness,
                    D("2.1"),
                )
    element("ROOF-01", "roof", floors, "Roof", D(0), D(0), width, length, D("0.15"))
    building_elements = [e for e in elements if e.kind in {"wall", "partition"}]
    wall_volume = sum(e.width * e.length * e.height for e in building_elements)
    # Opening deductions reference actual element geometry. Rates may require a different measurement
    # convention: that convention belongs in a reviewed package recipe.
    opening_volume = sum(
        e.width * e.length * e.height for e in elements if e.kind in {"door", "window", "exit"}
    )
    door_area = sum(
        (e.length if e.kind == "door" else e.width) * e.height for e in elements if e.kind in {"door", "exit"}
    )
    window_area = sum(e.length * e.height for e in elements if e.kind == "window")
    wall_area = sum((e.width if e.width > e.length else e.length) * e.height * 2 for e in building_elements)
    net = inner_length * inner_width * floors - sum(
        e.width * e.length for e in elements if e.kind == "partition"
    )
    metrics = {
        "gross_floor_area": length * width * floors,
        "net_floor_area": net,
        "roof_area": length * width,
        "footprint": length * width,
        "wall_volume": wall_volume - opening_volume,
        "wall_finish_area": wall_area - 2 * (door_area + window_area),
        "door_area": door_area,
        "window_area": window_area,
        "room_count": D(2 * rows * floors),
        "perimeter": 2 * (length + width),
        "floors": D(floors),
        "height": height,
        "duration_months": choose("duration_months", brief.duration_months, "12"),
        "capacity": choose("capacity", brief.capacity, "100"),
        "site_area": choose("site_area", brief.site_area, str(measure(length * width * D("1.5")))),
        "wet_area": room_width * room_length * floors,
    }
    if metrics["site_area"] < metrics["footprint"]:
        raise ValueError("Site area is smaller than the proposed footprint")
    return DesignRevision(
        template=pack.design_template,
        length=length,
        width=width,
        floors=floors,
        height=height,
        wall_thickness=thickness,
        elements=elements,
        metrics={k: measure(v) for k, v in metrics.items()},
        assumptions=assumptions,
        limitations=[
            "Concept drawing only; not approved for construction.",
            "Setbacks, access, occupancy, egress, accessibility and site conditions require engineering review.",
            "Foundations, reinforcement and service capacities are allowances until detailed engineering is supplied.",
            "Stair reserves indicate space only; stair geometry and structural design are not generated.",
        ],
    )


def drawing_svg(design: DesignRevision, title: str, revision: int, demo: bool) -> bytes:
    scale = min(24.0, 600 / float(design.length), 460 / float(design.width))
    panel = float(design.width) * scale + 100
    svg_width = max(720, panel * min(design.floors, 3))
    svg_height = float(design.length) * scale + 190
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_width} {svg_height}" role="img" aria-label="Concept floor plans">',
        "<style>text{font-family:Arial,sans-serif;fill:#183a38}.dim{font-size:10px;fill:#547571}</style>",
        '<rect width="100%" height="100%" fill="#f5faf7"/>',
        f'<text x="30" y="32" font-size="18" font-weight="bold">{escape(title)}</text>',
        f'<text x="30" y="53" font-size="11">CONCEPT ONLY · REVISION {revision}'
        + (" · ASSUMED GEOMETRY" if demo else "")
        + "</text>",
    ]
    for floor in range(min(design.floors, 3)):
        ox, oy = 50 + floor * panel, 100
        out.append(f'<text x="{ox}" y="{oy - 24}" font-size="12">FLOOR {floor + 1}</text>')
        kinds = ["room", "circulation", "wall", "partition", "door", "window", "exit"]
        for kind in kinds:
            for e in design.elements:
                if e.floor != floor or e.kind != kind:
                    continue
                x, y, w, h = (
                    ox + float(e.x) * scale,
                    oy + float(e.y) * scale,
                    float(e.width) * scale,
                    float(e.length) * scale,
                )
                color = {
                    "room": "#e5efeb",
                    "circulation": "#f9f4df",
                    "wall": "#244944",
                    "partition": "#57726c",
                    "door": "#fffdf2",
                    "window": "#51b9b0",
                    "exit": "#fffdf2",
                }[kind]
                out.append(
                    f'<rect data-element-id="{escape(e.id)}" x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"><title>{escape(e.id + ": " + e.label)}</title></rect>'
                )
                if kind == "room":
                    out.append(
                        f'<text x="{x + w / 2}" y="{y + h / 2}" text-anchor="middle" font-size="9">{escape(e.label)}</text>'
                    )
        w, h = float(design.width) * scale, float(design.length) * scale
        out.append(f'<path d="M {ox} {oy + h + 15} h {w}" stroke="#75918b"/>')
        out.append(
            f'<text class="dim" x="{ox + w / 2}" y="{oy + h + 30}" text-anchor="middle">{design.width} m</text>'
        )
        out.append(
            f'<text class="dim" transform="translate({ox - 12},{oy + h / 2}) rotate(-90)" text-anchor="middle">{design.length} m</text>'
        )
    out.append(
        f'<text x="30" y="{svg_height - 16}" font-size="10">Dimensions in metres. Layout, quantities and allowances require engineer validation.</text></svg>'
    )
    return "".join(out).encode()

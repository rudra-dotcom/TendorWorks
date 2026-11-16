"""Specialist responsibilities. All accepted numeric values come from evidence or deterministic tools."""

import hashlib
import re
from decimal import Decimal

from tender.engines import formula, generate_design, money
from tender.knowledge import KnowledgeGateway, in_period
from tender.providers import INTAKE_SCHEMA, ModelAdapter
from tender.research import ResearchWorker
from tender.schemas import (
    AdjustmentResult,
    Assumption,
    BOQItem,
    CalculationRecord,
    DomainPack,
    EstimateResult,
    EvidenceRecord,
    Finding,
    ProjectBrief,
)

D = Decimal


def finding(
    result: EstimateResult,
    code: str,
    checkpoint: int,
    message: str,
    severity: str = "blocking",
    item_id: str | None = None,
):
    if not any(f.code == code and f.item_id == item_id and f.message == message for f in result.findings):
        result.findings.append(
            Finding(code=code, checkpoint=checkpoint, severity=severity, message=message, item_id=item_id)
        )


def source_evidence(result: EstimateResult, pack: DomainPack, source_id: str, locator: str = "") -> str:
    document = next(d for d in pack.documents if d.id == source_id)
    eid = f"source:{document.id}:{document.version}"
    if not any(e.id == eid for e in result.evidence):
        result.evidence.append(
            EvidenceRecord(
                id=eid,
                kind="document",
                title=document.title,
                source_id=document.id,
                version=document.version,
                locator=locator or document.locator,
                url=document.url,
                snapshot_ref=document.snapshot_ref,
                content_hash=document.content_hash,
                trust=document.trust,
                value=document.text[:2000],
            )
        )
    # Every use retains its own exact locator; a document can supply many different rates or clauses.
    if locator:
        import hashlib

        claim_id = f"{eid}:{hashlib.sha256(locator.encode()).hexdigest()[:12]}"
        if not any(e.id == claim_id for e in result.evidence):
            result.evidence.append(
                EvidenceRecord(
                    id=claim_id,
                    kind="document",
                    title=document.title,
                    source_id=document.id,
                    version=document.version,
                    locator=locator,
                    url=document.url,
                    snapshot_ref=document.snapshot_ref,
                    content_hash=document.content_hash,
                    trust=document.trust,
                    parent_ids=[eid],
                )
            )
        return claim_id
    return eid


def valid_source(pack: DomainPack, source_id: str, result: EstimateResult) -> bool:
    document = next((d for d in pack.documents if d.id == source_id), None)
    return bool(
        document
        and document.trust in (["approved", "demo"] if result.demo else ["approved"])
        and in_period(document.effective_from, document.effective_to, result.brief.estimate_date)
    )


def calculation(
    result: EstimateResult,
    id_: str,
    expression: str,
    inputs: dict,
    value: Decimal,
    unit: str,
    evidence_ids: list[str],
) -> str:
    result.calculations = [c for c in result.calculations if c.id != id_]
    result.evidence = [e for e in result.evidence if e.id != id_]
    result.calculations.append(
        CalculationRecord(
            id=id_,
            formula=expression,
            inputs={k: str(v) for k, v in inputs.items()},
            result=str(value),
            unit=unit,
            evidence_ids=evidence_ids,
        )
    )
    result.evidence.append(
        EvidenceRecord(
            id=id_, kind="calculation", title=expression, value=f"{value} {unit}", parent_ids=evidence_ids
        )
    )
    return id_


class Specialists:
    def __init__(self, gateway: KnowledgeGateway, models: ModelAdapter):
        self.gateway, self.models = gateway, models
        self.research = ResearchWorker(gateway)

    def model_review(self, role: str, result: EstimateResult, tenant: str, context: dict | None = None):
        try:
            retrieved = [
                {"evidence_id": e.id, "locator": e.locator, "text": e.value}
                for e in result.evidence
                if e.kind == "retrieved"
            ]
            review_context = context or {
                "authority": result.brief.authority,
                "brief": result.brief.model_dump(mode="json"),
                "rules": [r.model_dump(mode="json") for r in result.rules],
                "assumptions": [a.model_dump(mode="json") for a in result.assumptions],
                "boq": [b.model_dump(mode="json") for b in result.boq],
                "findings": [f.model_dump(mode="json") for f in result.findings],
            }
            if retrieved:
                review_context = {**review_context, "retrieved_context": retrieved}
            output, usage = self.models.run(
                role,
                review_context,
                tenant,
            )
            evidence = {e.id: e for e in result.evidence if e.kind == "retrieved"}

            def cited(item: dict) -> tuple[str, str] | None:
                evidence_id, quote = item.get("evidence_id", ""), item.get("quote", "")
                if not isinstance(quote, str) or not quote or evidence_id not in evidence or quote not in evidence[evidence_id].value:
                    result.metrics["retrieval_citation_drops"] = result.metrics.get("retrieval_citation_drops", 0) + 1
                    return None
                return evidence_id, quote

            for concern in output.get("concerns", [])[:15]:
                if isinstance(concern, str):
                    finding(result, f"{role}_concern", max(1, result.checkpoint), concern[:1200], "warning")
                elif isinstance(concern, dict) and cited(concern):
                    finding(result, f"{role}_concern", max(1, result.checkpoint), concern["message"][:1200], "warning")
            for missing in output.get("missing_components", [])[:15]:
                if isinstance(missing, dict) and cited(missing):
                    finding(result, f"{role}_missing_component", max(1, result.checkpoint), missing["message"][:1200], "warning")
            for proposed in output.get("proposed_assumptions", [])[:10]:
                citation = cited(proposed) if isinstance(proposed, dict) else None
                if citation:
                    evidence_id, quote = citation
                    identity = hashlib.sha256(
                        f"{role}|{proposed['field']}|{proposed['value']}|{evidence_id}|{quote}".encode()
                    ).hexdigest()[:16]
                    if not any(a.id == f"rag:{identity}" for a in result.assumptions):
                        result.assumptions.append(
                            Assumption(
                                id=f"rag:{identity}", field=proposed["field"][:200], value=proposed["value"][:500],
                                reason=proposed["reason"][:1000], source_ids=[evidence_id], status="proposed"
                            )
                        )
            return usage
        except Exception:
            finding(
                result,
                "model_unavailable",
                max(1, result.checkpoint),
                f"{role}: live specialist unavailable; deterministic checks continued.",
                "warning",
            )
            return {"provider": self.models.settings.model_provider, "status": "unavailable"}

    def intake(self, result: EstimateResult, tenant: str) -> dict:
        brief = result.brief.model_dump(mode="json")
        text = result.brief.description
        lower = text.lower()
        if brief["authority"] == "unknown":
            matches = []
            if re.search(r"\bcpwd\b", lower):
                matches.append("cpwd")
            if re.search(r"\brailways?\b", lower):
                matches.append("railway")
            if re.search(r"\bstate pwd\b|\bpwd\b", lower):
                matches.append("state_pwd")
            if len(matches) == 1:
                brief["authority"] = matches[0]
        if not brief["building_type"]:
            for name, aliases in {
                "school": ["school", "classroom"],
                "office": ["office"],
                "community_hall": ["community hall"],
                "hospital": ["hospital"],
            }.items():
                if any(word in lower for word in aliases):
                    brief["building_type"] = name
                    break
        if re.search(r"\bbridge\b|\bpermanent way\b|\btrack renewal\b", lower):
            brief["work_category"] = "bridge" if "bridge" in lower else "permanent_way"
        patterns = {
            "floor_area": r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m(?:et(?:er|re)s?)?|m2|m²|square\s+met(?:er|re)s?)\b",
            "floors": r"(\d+)\s*[- ]?(?:storey|story|floors?)\b",
            "capacity": r"(\d+)\s*(?:students?|people|occupants?|seats?)\b",
            "duration_months": r"(\d+(?:\.\d+)?)\s*months?\b",
        }
        for field, pattern in patterns.items():
            if brief[field] is None:
                match = re.search(pattern, lower)
                if match:
                    brief[field] = match.group(1)
        for option, pattern in {"hvac": r"\bhvac\b|air.condition", "solar": r"\bsolar\b"}.items():
            if re.search(pattern, lower) and not re.search(
                r"(?:no|without|exclude)\s+(?:\w+\s+){0,2}" + pattern, lower
            ):
                if option not in brief["selected_options"]:
                    brief["selected_options"].append(option)
        usage = {"provider": "offline", "mode": "explicit_text_extraction"}
        if self.models.enabled:
            try:
                facts, usage = self.models.run("intake", {"description": text}, tenant, INTAKE_SCHEMA)
                allowed = {
                    "authority",
                    "building_type",
                    "state",
                    "location",
                    "floor_area",
                    "capacity",
                    "floors",
                    "duration_months",
                }
                for fact in facts.get("facts", []):
                    field, value, quote = fact.get("field"), fact.get("value"), fact.get("quote", "")
                    if field not in allowed or not quote or quote.casefold() not in lower:
                        continue
                    if brief.get(field) not in (None, "", "unknown"):
                        continue
                    candidate = {**brief, field: value}
                    try:
                        brief = ProjectBrief.model_validate(candidate).model_dump(mode="json")
                    except ValueError:
                        continue
            except Exception:
                finding(
                    result,
                    "model_unavailable",
                    1,
                    "Live intake failed; explicit fields and local text extraction used.",
                    "warning",
                )
        result.brief = ProjectBrief.model_validate(brief)
        result.evidence = [
            EvidenceRecord(
                id="input:brief",
                kind="user_input",
                title="Project brief",
                version=str(result.revision),
                value=result.brief.model_dump_json(),
                trust="supplied",
            )
        ]
        return usage

    def route(self, result: EstimateResult, tenant: str) -> tuple[str, DomainPack] | None:
        brief = result.brief
        missing = []
        if brief.authority == "unknown":
            missing.append("procuring authority")
        if not brief.location:
            missing.append("location")
        if brief.authority == "state_pwd" and not brief.state:
            missing.append("state")
        if not brief.building_type:
            missing.append("building type")
        if missing:
            finding(
                result, "routing_inputs", 1, "Specify " + ", ".join(missing) + " to select applicable data."
            )
            return None
        candidates = []
        for id_, pack in self.gateway.packs(tenant, include_candidates=False):
            if pack.authority != brief.authority or (pack.trust == "demo" and not brief.allow_demo):
                continue
            if not in_period(pack.effective_from, pack.effective_to, brief.estimate_date):
                continue
            if pack.states and brief.state.casefold() not in [s.casefold() for s in pack.states]:
                continue
            if brief.work_category not in pack.work_categories:
                continue
            candidates.append((id_, pack))
        # An approved package takes precedence over demonstration fixtures, never vice versa.
        if any(pack.trust == "approved" for _, pack in candidates):
            candidates = [(id_, p) for id_, p in candidates if p.trust == "approved"]
        superseded = {p.supersedes for _, p in candidates if p.supersedes}
        candidates = [(id_, p) for id_, p in candidates if f"{p.id}@{p.version}" not in superseded]
        if len(candidates) != 1:
            finding(
                result,
                "routing_conflict" if candidates else "missing_domain_pack",
                1,
                "Multiple applicable packages require an explicit supersession/adoption decision."
                if candidates
                else "No reviewed domain package covers this authority, location, date and work category. Add source documents and a validated package.",
            )
            return None
        id_, pack = candidates[0]
        result.pack_id, result.pack_version, result.demo = id_, pack.version, pack.trust == "demo"
        if result.demo:
            finding(
                result,
                "synthetic_demo",
                1,
                "All demonstration prices and quantity norms are synthetic. Do not use this estimate for procurement.",
                "warning",
            )
        return id_, pack

    def rules(self, result: EstimateResult, pack: DomainPack):
        result.rules = pack.rules
        if not pack.rules:
            finding(
                result,
                "missing_rule_coverage",
                1,
                "This package has no reviewed applicability or scope rules.",
            )
        for rule in pack.rules:
            if not valid_source(pack, rule.source_id, result):
                finding(
                    result, "invalid_rule_source", 1, f"Rule {rule.id} has no applicable reviewed source."
                )
            source_evidence(result, pack, rule.source_id, rule.locator)

    def scope(self, result: EstimateResult, pack: DomainPack):
        required = {c for rule in pack.rules for c in rule.required_components}
        result.boq = []
        for recipe in pack.components:
            specification = dict(recipe.specification)
            for name, value in result.brief.specifications.items():
                if name.startswith(recipe.key + "."):
                    specification[name[len(recipe.key) + 1 :]] = value
            selected = (
                recipe.classification != "optional"
                or recipe.key in result.brief.selected_options
                or recipe.key in required
            )
            result.boq.append(
                BOQItem(
                    id=f"boq:{recipe.key}",
                    key=recipe.key,
                    category=recipe.category,
                    description=recipe.description,
                    unit=recipe.unit,
                    use=recipe.use,
                    classification="mandatory" if recipe.key in required else recipe.classification,
                    selected=selected,
                    specification=specification,
                    evidence_ids=[source_evidence(result, pack, recipe.source_id, recipe.locator)],
                )
            )
        unknown_options = set(result.brief.selected_options) - {c.key for c in pack.components}
        for option in unknown_options:
            finding(
                result, "unsupported_option", 1, f"Requested component '{option}' is absent from the package."
            )
        for field in result.brief.specifications:
            if not any(field.startswith(recipe.key + ".") for recipe in pack.components):
                finding(
                    result,
                    "unmapped_specification",
                    1,
                    f"Specification '{field}' does not map to a component.",
                )

    def design(self, result: EstimateResult, pack: DomainPack):
        if pack.design_template == "none" or result.brief.building_type not in pack.supported_buildings:
            finding(
                result,
                "unsupported_design",
                1,
                "Rates may exist, but this package has no validated concept template for this building type.",
            )
            return
        try:
            result.design = generate_design(result.brief, pack)
        except ValueError as exc:
            finding(result, "design_inputs", 1, str(exc))
            return
        result.assumptions = result.design.assumptions
        source = source_evidence(result, pack, pack.default_source_id)
        if not valid_source(pack, pack.default_source_id, result):
            finding(
                result,
                "invalid_design_template",
                1,
                "Concept template source is not applicable to the estimate date.",
            )
        result.evidence = [e for e in result.evidence if e.kind not in {"design", "assumption"}]
        for assumption in result.assumptions:
            result.evidence.append(
                EvidenceRecord(
                    id=assumption.id,
                    kind="assumption",
                    title=assumption.reason,
                    value=f"{assumption.field}: {assumption.value}",
                    parent_ids=[source, "input:brief"],
                )
            )
        result.evidence.append(
            EvidenceRecord(
                id="design:model",
                kind="design",
                title="Dimensioned concept model",
                version=str(result.revision),
                value=result.design.model_dump_json(),
                parent_ids=["input:brief", source] + [a.id for a in result.assumptions],
            )
        )

    def quantities(self, result: EstimateResult, pack: DomainPack):
        recipes = {r.key: r for r in pack.components}
        for item in result.boq:
            recipe = recipes[item.key]
            if not valid_source(pack, recipe.source_id, result):
                if item.selected:
                    finding(
                        result,
                        "invalid_measurement_source",
                        1,
                        "The component measurement source is not applicable to the estimate date.",
                        item_id=item.id,
                    )
                continue
            if item.key in result.brief.supplied_quantities:
                item.quantity = result.brief.supplied_quantities[item.key]
                item.quantity_basis = "supplied"
                item.quantity_calculation_id = calculation(
                    result,
                    f"quantity:{item.key}",
                    "supplied_quantity",
                    {"supplied_quantity": item.quantity},
                    item.quantity,
                    item.unit,
                    ["input:brief"],
                )
            elif result.design and recipe.measurement:
                try:
                    item.quantity = formula(recipe.measurement, result.design.metrics)
                    item.quantity_basis = recipe.quantity_basis
                    refs = ["design:model", source_evidence(result, pack, recipe.source_id, recipe.locator)]
                    variables = set(re.findall(r"\b[a-zA-Z_]\w*\b", recipe.measurement))
                    inputs = {k: v for k, v in result.design.metrics.items() if k in variables}
                    item.quantity_calculation_id = calculation(
                        result,
                        f"quantity:{item.key}",
                        recipe.measurement,
                        inputs,
                        item.quantity,
                        item.unit,
                        refs,
                    )
                except ValueError as exc:
                    finding(result, "measurement_error", 1, str(exc), item_id=item.id)
            if result.design:
                kinds = {recipe.element_kind}
                if recipe.element_kind == "wall":
                    kinds.add("partition")
                if recipe.element_kind == "door":
                    kinds.add("exit")
                item.element_ids = [e.id for e in result.design.elements if e.kind in kinds]
                if recipe.element_kind == "building":
                    item.element_ids = [e.id for e in result.design.elements if e.kind == "slab"]
            if item.quantity_calculation_id:
                item.evidence_ids.append(item.quantity_calculation_id)
            if item.quantity is None and item.selected:
                finding(
                    result,
                    "unresolved_quantity",
                    1,
                    f"{item.description}: no defensible quantity is available.",
                    item_id=item.id,
                )

    def verify_quantities(self, result: EstimateResult, pack: DomainPack):
        keys = [b.key for b in result.boq if b.selected]
        if len(keys) != len(set(keys)):
            finding(
                result, "duplicate_component", 1, "The component register contains duplicate selected items."
            )
        for rule in result.rules:
            for name in set(rule.required_components) - set(keys):
                finding(
                    result, "missing_required_component", 1, f"{name} is required by {rule.id} but absent."
                )
        valid_elements = {e.id for e in result.design.elements} if result.design else set()
        for item in result.boq:
            if item.quantity_basis == "concept_derived" and (
                not item.element_ids or not set(item.element_ids) <= valid_elements
            ):
                finding(
                    result,
                    "unmapped_quantity",
                    1,
                    "Concept quantity has no valid drawing element link.",
                    item_id=item.id,
                )
            if item.selected and item.quantity == 0:
                finding(
                    result,
                    "zero_quantity",
                    1,
                    "Included item has a zero quantity; verify its applicability.",
                    "warning",
                    item.id,
                )
        selected = set(keys)
        for recipe in pack.components:
            if recipe.key in selected and set(recipe.excludes_components) & selected:
                finding(
                    result, "overlapping_scope", 1, f"{recipe.key} overlaps with another selected component."
                )

    def prices(self, result: EstimateResult, pack: DomainPack, tenant: str):
        research_count = 0
        for item in result.boq:
            candidates = self.gateway.rate_candidates(result.pack_id, item.key, tenant)
            # Package versions are immutable; source trust and dates come from the revision's pinned snapshot.
            applicable = [
                r
                for r in candidates
                if r.unit == item.unit
                and r.specification == item.specification
                and in_period(r.effective_from, r.effective_to, result.brief.estimate_date)
                and valid_source(pack, r.source_id, result)
            ]
            superseded = {r.supersedes for r in applicable if r.supersedes}
            applicable = [r for r in applicable if r.id not in superseded]
            if len(applicable) != 1:
                item.status = "unresolved_rate"
                if item.selected:
                    finding(
                        result,
                        "ambiguous_rate" if applicable else "missing_rate",
                        2,
                        "Multiple exact rate matches need a reviewed supersession decision."
                        if applicable
                        else "No applicable rate matches this specification and unit exactly.",
                        item_id=item.id,
                    )
                if not applicable and item.selected and research_count < 2:
                    try:
                        research = self.research.discover(result.brief.authority, item.key, tenant)
                        if research["candidates"]:
                            finding(
                                result,
                                "research_candidates",
                                2,
                                "New sources were cached as candidates and require review before pricing.",
                                "warning",
                                item.id,
                            )
                    except Exception:
                        finding(
                            result,
                            "research_unavailable",
                            2,
                            "Web research was unavailable; missing rate remains unresolved.",
                            "warning",
                            item.id,
                        )
                    research_count += 1
                continue
            rate = applicable[0]
            refs = [source_evidence(result, pack, rate.source_id, rate.locator)]
            value = rate.value
            if rate.basis == "non_scheduled":
                if any(not valid_source(pack, r.source_id, result) for r in rate.resources):
                    finding(
                        result,
                        "invalid_resource_source",
                        2,
                        "Rate analysis contains an unsupported resource price.",
                        item_id=item.id,
                    )
                    continue
                resource_amounts = []
                for n, resource in enumerate(rate.resources):
                    reference = source_evidence(result, pack, resource.source_id, resource.locator)
                    amount = resource.consumption * resource.unit_rate
                    resource_amounts.append(amount)
                    refs.append(
                        calculation(
                            result,
                            f"resource:{item.key}:{n}",
                            "consumption * unit_rate",
                            {"consumption": resource.consumption, "unit_rate": resource.unit_rate},
                            amount,
                            "INR/" + item.unit,
                            [reference],
                        )
                    )
                value = sum(resource_amounts, D(0))
                refs = [
                    calculation(
                        result,
                        f"rate:{item.key}",
                        "sum(resource_amounts)",
                        {f"resource_{n}": amount for n, amount in enumerate(resource_amounts)},
                        value,
                        "INR/" + item.unit,
                        refs,
                    )
                ]
            item.unit_rate = value.quantize(D("0.000001"))
            item.rate_id, item.item_code, item.rate_basis = rate.id, rate.item_code, rate.basis
            item.cost_behavior = rate.cost_behavior
            item.inclusions, item.exclusions = rate.inclusions, rate.exclusions
            item.evidence_ids.extend(refs)
            item.status = "priced" if item.quantity is not None else "unresolved_quantity"

    def calculate(self, result: EstimateResult, pack: DomainPack):
        result.known_subtotal, result.optional_subtotal = D(0), D(0)
        result.category_totals, result.adjustments, result.scenario_totals = {}, [], {}
        for item in result.boq:
            if item.quantity is None or item.unit_rate is None:
                continue
            item.amount = money(item.quantity * item.unit_rate)
            item.amount_calculation_id = calculation(
                result,
                f"amount:{item.key}",
                "quantity * unit_rate",
                {"quantity": item.quantity, "unit_rate": item.unit_rate},
                item.amount,
                "INR",
                item.evidence_ids,
            )
            if item.selected:
                result.known_subtotal += item.amount
                result.category_totals[item.category] = (
                    result.category_totals.get(item.category, D(0)) + item.amount
                )
            elif item.classification == "optional":
                result.optional_subtotal += item.amount
        applied = set()
        for adjustment in pack.adjustments:
            if not in_period(adjustment.effective_from, adjustment.effective_to, result.brief.estimate_date):
                continue
            if adjustment.execution_year and adjustment.execution_year != result.brief.execution_year:
                continue
            if not valid_source(pack, adjustment.source_id, result):
                finding(result, "invalid_adjustment_source", 2, f"{adjustment.label} has no valid source.")
                continue
            eligible = []
            for item in result.boq:
                if (
                    not item.selected
                    or item.amount is None
                    or (adjustment.component_keys and item.key not in adjustment.component_keys)
                ):
                    continue
                if adjustment.kind in item.inclusions:
                    finding(
                        result,
                        "adjustment_already_included",
                        2,
                        f"{adjustment.label} already included in {item.description}; not applied again.",
                        "warning",
                        item.id,
                    )
                    continue
                dedup = (item.id, adjustment.group, adjustment.scenario)
                if dedup in applied:
                    finding(
                        result,
                        "overlapping_adjustments",
                        2,
                        f"Multiple {adjustment.group} adjustments target {item.description}.",
                    )
                    continue
                applied.add(dedup)
                eligible.append(item)
            base = sum((b.amount for b in eligible), D(0))
            amount = money(base * adjustment.percent / 100)
            ref = source_evidence(result, pack, adjustment.source_id, adjustment.locator)
            calculation(
                result,
                f"adjustment:{adjustment.id}",
                "base * percent / 100",
                {"base": base, "percent": adjustment.percent},
                amount,
                "INR",
                [ref] + [b.amount_calculation_id for b in eligible],
            )
            result.adjustments.append(
                AdjustmentResult(
                    id=adjustment.id,
                    label=adjustment.label,
                    kind=adjustment.kind,
                    scenario=adjustment.scenario,
                    percent=adjustment.percent,
                    base=base,
                    amount=amount,
                    item_ids=[b.id for b in eligible],
                    evidence_ids=[ref],
                )
            )
        base_additions = sum((a.amount for a in result.adjustments if a.scenario == "base"), D(0))
        total = money(result.known_subtotal + base_additions)
        incomplete = any(b.selected and b.amount is None for b in result.boq) or any(
            f.severity == "blocking" for f in result.findings
        )
        result.base_total = None if incomplete else total
        if not incomplete:
            for name in {a.scenario for a in result.adjustments if a.scenario != "base"}:
                result.scenario_totals[name] = money(
                    total + sum((a.amount for a in result.adjustments if a.scenario == name), D(0))
                )
        if result.brief.execution_year != result.brief.estimate_date.year and not any(
            a.kind == "escalation" for a in result.adjustments
        ):
            finding(
                result,
                "future_cost_unadjusted",
                2,
                "No approved execution-year escalation was available. Values remain at the stated rate basis dates.",
                "warning",
            )
        if not any(a.kind == "tax" for a in result.adjustments) and any(
            "tax" in b.exclusions for b in result.boq if b.selected
        ):
            finding(
                result,
                "tax_excluded",
                2,
                "Tax is excluded where indicated by rate sources; no unsupported tax percentage has been added.",
                "warning",
            )

    def verify_prices(self, result: EstimateResult, pack: DomainPack):
        for item in result.boq:
            if item.selected and item.cost_behavior == "fixed" and item.quantity not in (None, D(1)):
                finding(
                    result,
                    "fixed_charge_quantity",
                    2,
                    "A fixed project charge must have quantity one; review the supplied quantity or rate classification.",
                    item_id=item.id,
                )
            if item.amount is not None and item.amount != money(item.quantity * item.unit_rate):
                finding(
                    result,
                    "arithmetic_mismatch",
                    2,
                    "Item amount does not equal quantity × unit rate.",
                    item_id=item.id,
                )
            if item.unit_rate is not None and item.rate_id is None:
                finding(
                    result,
                    "unattributed_rate",
                    2,
                    "A numeric rate has no selected rate record.",
                    item_id=item.id,
                )
            # Only explicitly normalized comparables with matching scope are used.
            comparables = [
                h
                for h in pack.historical_rates
                if h.component_key == item.key
                and h.unit == item.unit
                and h.specification == item.specification
                and h.location.casefold() == result.brief.location.casefold()
                and h.normalized_to == result.brief.estimate_date
                and h.normalized_value is not None
                and set(h.inclusions) == set(item.inclusions)
                and h.normalization_source_id
                and valid_source(pack, h.normalization_source_id, result)
            ]
            if item.unit_rate is not None and comparables:
                values = sorted(h.normalized_value for h in comparables)
                # Flag outside observed range; never replace schedule rates automatically.
                if item.unit_rate < values[0] or item.unit_rate > values[-1]:
                    finding(
                        result,
                        "outside_comparables",
                        2,
                        f"Rate lies outside the matched, normalized historical range {values[0]}–{values[-1]} INR/{item.unit}.",
                        "warning",
                        item.id,
                    )

    def audit_evidence(self, result: EstimateResult, pack: DomainPack):
        ids = {e.id for e in result.evidence}
        calculations = {c.id: c for c in result.calculations}
        for evidence in result.evidence:
            if not set(evidence.parent_ids) <= ids:
                finding(
                    result, "broken_evidence_link", 3, f"Evidence {evidence.id} references a missing parent."
                )
            if evidence.kind in {"document", "retrieved"}:
                if not evidence.snapshot_ref or not evidence.content_hash:
                    finding(
                        result, "missing_snapshot", 3, f"Source {evidence.title} lacks a source snapshot."
                    )
                else:
                    try:
                        self.gateway.objects.get(evidence.snapshot_ref)
                    except (OSError, ValueError):
                        finding(
                            result,
                            "unreadable_snapshot",
                            3,
                            f"Source {evidence.title} failed its integrity check.",
                        )
        covered = 0
        for item in result.boq:
            if item.amount is None:
                continue
            if (
                item.quantity_calculation_id not in calculations
                or item.amount_calculation_id not in calculations
            ):
                finding(
                    result,
                    "missing_calculation",
                    3,
                    "Priced row has incomplete calculation evidence.",
                    item_id=item.id,
                )
            elif not set(item.evidence_ids) <= ids:
                finding(
                    result,
                    "missing_item_evidence",
                    3,
                    "Priced row has a broken source reference.",
                    item_id=item.id,
                )
            else:
                covered += 1
        priced = sum(b.amount is not None for b in result.boq)
        result.metrics.update(
            {
                "priced_rows": priced,
                "total_rows": len(result.boq),
                "evidence_coverage": covered / priced if priced else 0,
                "unresolved_selected_rows": sum(b.selected and b.amount is None for b in result.boq),
                "blocking_findings": sum(f.severity == "blocking" for f in result.findings),
            }
        )
        if any(f.severity == "blocking" for f in result.findings):
            result.base_total = None
        result.status = "incomplete" if result.base_total is None else "draft"

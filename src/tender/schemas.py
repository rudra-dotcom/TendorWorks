"""Shared contracts. Money and quantities serialize as decimal strings, never binary floats."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]
Positive = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
Authority = Literal["cpwd", "railway", "state_pwd", "unknown"]
Trust = Literal["candidate", "approved", "demo", "rejected"]
Basis = Literal["supplied", "concept_derived", "template_allowance", "unresolved"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class Identity(Contract):
    tenant: str = "demo"
    user: str = "local-engineer"
    role: Literal["viewer", "engineer", "reviewer", "admin"] = "admin"


class ProjectBrief(Contract):
    title: str = Field(default="Untitled estimate", max_length=180)
    description: str = Field(min_length=10, max_length=16000)
    authority: Authority = "unknown"
    state: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=160)
    building_type: str = Field(default="", max_length=80)
    work_category: str = "building"
    estimate_date: date = Field(default_factory=date.today)
    execution_year: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)
    floor_area: Positive | None = None
    length: Positive | None = None
    width: Positive | None = None
    floors: int | None = Field(default=None, ge=1, le=20)
    height: Positive | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    duration_months: Positive | None = None
    site_area: Positive | None = None
    selected_options: list[str] = Field(default_factory=list, max_length=30)
    specifications: dict[str, str] = Field(default_factory=dict)
    supplied_quantities: dict[str, Number] = Field(default_factory=dict)
    review_design: bool = False
    allow_demo: bool = True


class SourceDocument(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,120}$")
    title: str
    version: str
    kind: Literal["schedule", "rule", "specification", "template", "quote", "historical", "web"]
    authority: Authority
    state: str = ""
    discipline: str = "all"
    effective_from: date
    effective_to: date | None = None
    url: str = ""
    text: str = Field(min_length=1, max_length=500000)
    locator: str = ""
    supersedes: str | None = None
    trust: Trust = "candidate"
    snapshot_ref: str = ""
    content_hash: str = ""
    retrieved_at: str = Field(default_factory=now)

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Source effective_to precedes effective_from")
        return self


class ResourceInput(Contract):
    description: str
    consumption: Positive
    unit: str
    unit_rate: Number
    source_id: str
    locator: str


class RateRecord(Contract):
    id: str
    item_code: str
    component_key: str
    description: str
    unit: str
    specification: dict[str, str] = Field(default_factory=dict)
    value: Number | None = None
    basis: Literal["scheduled", "non_scheduled"] = "scheduled"
    cost_behavior: Literal["quantity", "fixed", "time"] = "quantity"
    source_id: str
    locator: str
    effective_from: date
    effective_to: date | None = None
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    resources: list[ResourceInput] = Field(default_factory=list)
    supersedes: str | None = None

    @model_validator(mode="after")
    def rate_basis(self):
        if self.basis == "scheduled" and self.value is None:
            raise ValueError("Scheduled rates require a value")
        if self.basis == "non_scheduled" and not self.resources:
            raise ValueError("Non-scheduled rates require supported resource inputs")
        if set(self.inclusions) & set(self.exclusions):
            raise ValueError("A rate cannot include and exclude the same cost")
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Rate validity dates are inverted")
        return self


class ComponentRecipe(Contract):
    key: str
    category: str
    description: str
    unit: str
    classification: Literal["mandatory", "functional", "optional"] = "functional"
    use: str
    measurement: str | None = None
    quantity_basis: Basis = "concept_derived"
    source_id: str
    locator: str
    specification: dict[str, str] = Field(default_factory=dict)
    element_kind: str = "building"
    excludes_components: list[str] = Field(default_factory=list)
    allowance_reason: str = ""


class RuleRequirement(Contract):
    id: str
    text: str
    source_id: str
    locator: str
    required_components: list[str] = Field(default_factory=list)
    blocking: bool = True


class Adjustment(Contract):
    id: str
    label: str
    kind: Literal["tax", "location", "escalation", "overhead", "contingency", "other"]
    percent: Number
    component_keys: list[str] = Field(default_factory=list)
    source_id: str
    locator: str
    effective_from: date
    effective_to: date | None = None
    execution_year: int | None = None
    group: str
    scenario: str = "base"


class HistoricalRate(Contract):
    id: str
    component_key: str
    specification: dict[str, str]
    unit: str
    value: Number
    outcome: Literal["sanctioned_estimate", "accepted_tender", "actual_completion"]
    location: str
    date: date
    source_id: str
    inclusions: list[str] = Field(default_factory=list)
    # Explicit, reviewed normalization; never inferred from a generic inflation number.
    normalized_to: date | None = None
    normalized_value: Number | None = None
    normalization_source_id: str | None = None


class DomainPack(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,120}$")
    version: str
    name: str
    authority: Authority
    states: list[str] = Field(default_factory=list)
    work_categories: list[str] = Field(default_factory=lambda: ["building"])
    supported_buildings: list[str] = Field(default_factory=list)
    design_template: Literal["rectangular_concept_v1", "none"] = "rectangular_concept_v1"
    effective_from: date
    effective_to: date | None = None
    trust: Trust = "candidate"
    documents: list[SourceDocument]
    components: list[ComponentRecipe]
    rates: list[RateRecord]
    rules: list[RuleRequirement] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    historical_rates: list[HistoricalRate] = Field(default_factory=list)
    design_defaults: dict[str, str] = Field(default_factory=dict)
    default_source_id: str
    max_concept_floors: int = Field(default=3, ge=1, le=20)
    supersedes: str | None = None

    @model_validator(mode="after")
    def references(self):
        ids = {d.id for d in self.documents}
        if len(ids) != len(self.documents):
            raise ValueError("Duplicate document IDs")
        for collection in (self.components, self.rates, self.rules, self.adjustments):
            for item in collection:
                if item.source_id not in ids:
                    raise ValueError(f"Unknown source {item.source_id}")
        if self.default_source_id not in ids:
            raise ValueError("Design defaults require a source")
        for collection, key in ((self.components, "key"), (self.rates, "id"), (self.rules, "id")):
            values = [getattr(item, key) for item in collection]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {key} in domain package")
        for rate in self.rates:
            for resource in rate.resources:
                if resource.source_id not in ids:
                    raise ValueError("Resource price has no source")
        for record in self.historical_rates:
            if record.source_id not in ids or (
                record.normalization_source_id and record.normalization_source_id not in ids
            ):
                raise ValueError("Historical rate references an unknown source")
        if self.authority == "state_pwd" and not self.states:
            raise ValueError("State PWD packages must name their applicable states")
        return self


class Assumption(Contract):
    id: str
    field: str
    value: str
    reason: str
    source_ids: list[str] = Field(default_factory=list)
    status: Literal["proposed", "accepted", "supplied"] = "proposed"


class DesignElement(Contract):
    id: str
    kind: str
    floor: int
    label: str
    x: Decimal
    y: Decimal
    width: Positive
    length: Positive
    height: Number = Decimal("0")


class DesignRevision(Contract):
    template: str
    length: Positive
    width: Positive
    floors: int
    height: Positive
    wall_thickness: Positive
    elements: list[DesignElement]
    metrics: dict[str, Decimal]
    assumptions: list[Assumption]
    limitations: list[str]


class EvidenceRecord(Contract):
    id: str
    kind: Literal["document", "retrieved", "user_input", "design", "assumption", "calculation"]
    title: str
    source_id: str | None = None
    version: str = ""
    locator: str = ""
    url: str = ""
    snapshot_ref: str = ""
    content_hash: str = ""
    value: str = ""
    trust: str = ""
    parent_ids: list[str] = Field(default_factory=list)


class CalculationRecord(Contract):
    id: str
    formula: str
    inputs: dict[str, str]
    result: str
    unit: str
    evidence_ids: list[str]


class Finding(Contract):
    code: str
    checkpoint: int
    severity: Literal["info", "warning", "blocking"]
    message: str
    item_id: str | None = None


class BOQItem(Contract):
    id: str
    key: str
    category: str
    description: str
    unit: str
    use: str
    classification: Literal["mandatory", "functional", "optional", "excluded"]
    selected: bool = True
    specification: dict[str, str]
    element_ids: list[str] = Field(default_factory=list)
    quantity: Number | None = None
    quantity_basis: Basis = "unresolved"
    quantity_calculation_id: str | None = None
    unit_rate: Number | None = None
    rate_basis: str = "unresolved"
    rate_id: str | None = None
    item_code: str | None = None
    cost_behavior: str = "quantity"
    amount: Number | None = None
    amount_calculation_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    status: str = "unpriced"


class AdjustmentResult(Contract):
    id: str
    label: str
    kind: str
    scenario: str
    percent: Decimal
    base: Decimal
    amount: Decimal
    item_ids: list[str]
    evidence_ids: list[str]


class EstimateResult(Contract):
    project_id: str
    revision_id: str
    revision: int
    brief: ProjectBrief
    pack_id: str | None = None
    pack_version: str | None = None
    demo: bool = False
    status: str = "queued"
    checkpoint: int = 0
    design: DesignRevision | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    rules: list[RuleRequirement] = Field(default_factory=list)
    boq: list[BOQItem] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    adjustments: list[AdjustmentResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    known_subtotal: Decimal = Decimal("0")
    base_total: Decimal | None = None
    optional_subtotal: Decimal = Decimal("0")
    category_totals: dict[str, Decimal] = Field(default_factory=dict)
    scenario_totals: dict[str, Decimal] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    pending: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=now)


class ReviewRequest(Contract):
    decision: Literal["accept_design", "request_changes", "mark_reviewed"]
    note: str = Field(min_length=3, max_length=4000)


class FeedbackRequest(Contract):
    category: Literal["scope", "quantity", "specification", "source", "price", "design"]
    item_id: str | None = None
    comment: str = Field(min_length=5, max_length=4000)
    proposed_value: str | None = Field(default=None, max_length=500)


class FeedbackDecision(Contract):
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=5, max_length=4000)

"""Engine probe: geometry invariants, area fidelity, evidence-coverage blind spot, and the work-type scope guard."""

import itertools
import random
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from tender.config import Settings
from tender.db import Repository
from tender.demo import demo_pack, seed
from tender.engines import generate_design
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.schemas import Identity, ProjectBrief
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow

D = Decimal
SCRATCH = Path(sys.argv[1])
SCRATCH.mkdir(parents=True, exist_ok=True)


def env(tag):
    root = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=SCRATCH))
    s = Settings(
        _env_file=None, data_dir=root / "var", database_dir=root / "db", database_url=f"sqlite:///{root}/s.db"
    )
    repo = Repository(s)
    gw = KnowledgeGateway(repo, ObjectStore(s), s)
    return repo, gw, FolderIngestor(gw)


def run(repo, gw, ing, brief):
    wf = EstimationWorkflow(repo, gw, ing)
    try:
        actor = Identity(tenant="demo", user="probe")
        b = ProjectBrief.model_validate(brief)
        b.review_design = False
        created = repo.create_project(b, actor)
        token = repo.claim(created.revision_id, actor.tenant)
        wf.execute(created.revision_id, actor, token)
        return repo.get_revision(created.revision_id, actor.tenant).result
    finally:
        wf.close()


base = {
    "description": "Build a CPWD primary school with standard classrooms and toilets.",
    "authority": "cpwd",
    "state": "Delhi",
    "location": "New Delhi",
    "building_type": "school",
    "estimate_date": "2026-09-26",
    "execution_year": 2026,
}

# ------------------------------------------------------------------ G1 geometry sweep (explicit L x W x floors)
pack = demo_pack()
n = errors = viol = 0
viol_kinds = {}
for L, W, fl in itertools.product(
    (8, 10, 12, 15, 20, 30, 50, 80, 120), (8, 10, 12, 15, 20, 30, 50, 60, 100), (1, 2, 3)
):
    n += 1
    try:
        d = generate_design(
            ProjectBrief.model_validate(
                {**base, "length": str(L), "width": str(W), "floors": fl, "floor_area": str(L * W * fl)}
            ),
            pack,
        )
    except ValueError as e:
        errors += 1
        viol_kinds["ValueError: " + str(e)[:60]] = viol_kinds.get("ValueError: " + str(e)[:60], 0) + 1
        continue
    m = d.metrics
    checks = {
        "gross != L*W*floors": m["gross_floor_area"] != D(L * W * fl),
        "net not in (0, gross)": not (0 < m["net_floor_area"] < m["gross_floor_area"]),
        "wall_volume <= 0": m["wall_volume"] <= 0,
        "negative metric": any(v < 0 for v in m.values()),
        "element outside footprint": any(
            e.x < 0
            or e.y < 0
            or e.x + e.width > d.width + D("0.001")
            or e.y + e.length > d.length + D("0.001")
            for e in d.elements
        ),
    }
    for k, bad in checks.items():
        if bad:
            viol += 1
            viol_kinds[k] = viol_kinds.get(k, 0) + 1
print(
    "G1  geometry sweep: %d configs, %d rejected by validation, %d invariant violations" % (n, errors, viol)
)
print("G1  breakdown:", viol_kinds or "none")

# ------------------------------------------------------------------ G2 area fidelity when only floor_area given
random.seed(7)
rel, rejected, tot = [], 0, 0
for _ in range(300):
    area = D(random.randint(150, 6000))
    fl = random.choice((1, 2, 3))
    tot += 1
    try:
        d = generate_design(
            ProjectBrief.model_validate({**base, "floor_area": str(area), "floors": fl}), pack
        )
        rel.append(float(abs(d.metrics["gross_floor_area"] - area) / area))
    except ValueError:
        rejected += 1
print(
    "G2  floor_area-only inputs: %d tried, %d rejected, max relative area error %.5f, mean %.6f"
    % (tot, rejected, max(rel), sum(rel) / len(rel))
)

# ------------------------------------------------------------------ V1 evidence-coverage blind spot
repo, gw, ing = env("v1")
seed(gw)
honest = run(repo, gw, ing, {**base, "floor_area": "600", "floors": 2})
repo2, gw2, ing2 = env("v1b")
tampered_pack = demo_pack()
for r in tampered_pack.rates:
    if r.component_key == "rcc":
        r.value = D("99999")
gw2.import_pack(tampered_pack, Identity(tenant="demo", user="probe"), internal_demo=True)
tamper = run(repo2, gw2, ing2, {**base, "floor_area": "600", "floors": 2})


def rcc(res):
    row = next(b for b in res["boq"] if b["key"] == "rcc")
    return row["unit_rate"], row["amount"]


print(
    "V1  honest  : status=%s evidence_coverage=%s rcc(rate,amount)=%s base_total=%s"
    % (honest["status"], honest["metrics"]["evidence_coverage"], rcc(honest), honest["base_total"])
)
print(
    "V1  tampered: status=%s evidence_coverage=%s rcc(rate,amount)=%s base_total=%s"
    % (tamper["status"], tamper["metrics"]["evidence_coverage"], rcc(tamper), tamper["base_total"])
)
src = next(d for d in tampered_pack.documents if d.id == "demo-cpwd-rates")
print(
    "V1  cited source text contains '99999'? %s | contains '7800'? %s | blocking findings in tampered run: %s"
    % (
        "99999" in src.text,
        "7800" in src.text,
        [f["code"] for f in tamper["findings"] if f["severity"] == "blocking"],
    )
)

# ------------------------------------------------------------------ S1 work-type scope guard on a real tender title
repo3, gw3, ing3 = env("s1")
seed(gw3)
nia = run(
    repo3,
    gw3,
    ing3,
    {
        "title": "NIA Jaipur Shalakya works",
        "description": "Renovation of 1 Room & construction of 1 room on roof with shade for Shalakya Department including Electrical Work at NIA Jaipur.",
        "authority": "cpwd",
        "state": "Rajasthan",
        "location": "Jaipur",
        "building_type": "office",
        "estimate_date": "2026-04-17",
        "execution_year": 2026,
    },
)
print(
    "S1  renovation tender text routed as new-build 'office': status=%s base_total=%s priced_rows=%s"
    % (nia["status"], nia["base_total"], nia["metrics"].get("priced_rows"))
)
print("S1  findings:", [(f["severity"], f["code"]) for f in nia["findings"]])
print(
    "S1  assumptions:",
    [
        (a["field"], a["value"])
        for a in nia["assumptions"]
        if a["field"] in ("floor_area", "floors", "footprint")
    ],
)

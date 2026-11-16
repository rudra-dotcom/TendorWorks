"""Verification: seeded bundled evaluation, workflow-level effect of intake failures, exact arithmetic on real documents."""

import sys
import tempfile
from decimal import Decimal as D
from pathlib import Path

from tender.config import Settings
from tender.db import Repository
from tender.demo import seed
from tender.evaluation import evaluate_cases
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.schemas import Identity, ProjectBrief
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow

SCRATCH, CASES = Path(sys.argv[1]), Path(sys.argv[2])
SCRATCH.mkdir(parents=True, exist_ok=True)


def env(tag):
    root = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=SCRATCH))
    s = Settings(
        _env_file=None, data_dir=root / "var", database_dir=root / "db", database_url=f"sqlite:///{root}/s.db"
    )
    repo = Repository(s)
    gw = KnowledgeGateway(repo, ObjectStore(s), s)
    return repo, gw, FolderIngestor(gw)


# 1. bundled evaluator, exactly as the CLI calls it, but WITH demo packs seeded
repo, gw, ing = env("ev")
seed(gw)
rep = evaluate_cases(CASES, gw, ing)
print(
    "1. seeded evaluate_cases -> overall passed =",
    rep["passed"],
    "|",
    [(c["name"][:32], c["passed"]) for c in rep["cases"]],
)

# 2. workflow-level effect of two intake failures
repo, gw, ing = env("wf")
seed(gw)
wf = EstimationWorkflow(repo, gw, ing)


def run(desc, **extra):
    actor = Identity(tenant="demo", user="probe")
    b = ProjectBrief.model_validate(
        {
            "description": desc,
            "authority": "cpwd",
            "state": "Delhi",
            "location": "New Delhi",
            "building_type": "office",
            "estimate_date": "2026-09-26",
            "execution_year": 2026,
            **extra,
        }
    )
    c = repo.create_project(b, actor)
    t = repo.claim(c.revision_id, actor.tenant)
    wf.execute(c.revision_id, actor, t)
    return repo.get_revision(c.revision_id, actor.tenant).result


r22 = run("Built-up area 12,000 sq m office building for CPWD.")
print(
    "2a. '12,000 sq m' -> status=%s | findings=%s"
    % (r22["status"], [(f["code"], f["message"][:95]) for f in r22["findings"]])
)
r_good = run("Construction of CPWD office building of 1200 sq m with 3 floors.")
r_comma = run("Construction of CPWD office building of 1,200 sq m with 3 floors.")
print(
    "2b. '1200 sq m' -> floor_area=%s total=%s | '1,200 sq m' -> floor_area=%s total=%s"
    % (
        r_good["brief"]["floor_area"],
        r_good["base_total"],
        r_comma["brief"]["floor_area"],
        r_comma["base_total"],
    )
)
wf.close()

# 3. arithmetic on the real documents (values as read by the fetch tool; verify against the PDFs)
rows = [
    ("1.1", 1, "2060.20", "2060.20"),
    ("2.1", 2, "367.20", "734.40"),
    ("3.1", 60, "73.40", "4404.00"),
    ("4", 1, "112.05", "112.05"),
    ("5", 320, "19.75", "6320.00"),
    ("6.1", 200, "142.80", "28560.00"),
    ("7.1", 120, "160.60", "19272.00"),
    ("8.1", 2, "2199.11", "4398.234"),
    ("9.1", D("5.2"), "2172.10", "11294.92"),
    ("10.1", D("10.4"), "897.30", "9331.92"),
    ("11", D("5.2"), "462.35", "2404.22"),
    ("12.1", 14, "90.45", "1266.30"),
    ("13.1", 22, "350.00", "7700.00"),
    ("14.1", 2, "72.35", "144.70"),
    ("15", 320, "156.05", "49936.00"),
]
bad = [(i, D(q) * D(r), D(a)) for i, q, r, a in rows if abs(D(q) * D(r) - D(a)) > D("0.005")]
print(
    "3a. NIA civil BOQ rows read: %d | rows where qty*rate != printed amount (tol 0.005): %s"
    % (len(rows), bad)
)
print(
    "3b. sum of the %d readable rows = %s (civil estimate is 12,33,955 -> these rows are %.1f%% of it; items 16+ not read)"
    % (len(rows), sum(D(a) for *_, a in rows), 100 * float(sum(D(a) for *_, a in rows)) / 1233955)
)
print(
    "3c. civil+electrical = %s ; 2%% of 15,61,391 = %s ; 2%% of 15,61,691 = %s ; printed EMD = 31,228"
    % (D(1233955) + D(327436), D("0.02") * 1561391, D("0.02") * 1561691)
)
est, acc = D("4072497.00"), D("1833030.87")
print(
    "3d. DDA award: accepted/estimate = %.5f -> %.2f%% below estimate"
    % (float(acc / est), float((1 - acc / est) * 100))
)
print(
    "3e. MoSPI Aug-2024 anticipated vs original cost: %.2f%%" % (100 * (3304696.35 - 2738539.25) / 2738539.25)
)

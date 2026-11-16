"""Intake probe: accuracy of the offline (regex) brief extraction. Gold labels are mine, from the plain meaning of each sentence."""

import sys
import tempfile
from pathlib import Path

from tender.agents import Specialists
from tender.config import Settings
from tender.db import Repository
from tender.knowledge import KnowledgeGateway
from tender.providers import ModelAdapter
from tender.schemas import EstimateResult, ProjectBrief
from tender.storage import ObjectStore

scratch = Path(sys.argv[1])
scratch.mkdir(parents=True, exist_ok=True)
root = Path(tempfile.mkdtemp(prefix="intake-", dir=scratch))
s = Settings(
    _env_file=None, data_dir=root / "var", database_dir=root / "db", database_url=f"sqlite:///{root}/s.db"
)
gw = KnowledgeGateway(Repository(s), ObjectStore(s), s)
agents = Specialists(gw, ModelAdapter(s, gw))


def C(**k):
    return k


CASES = [
    (
        "c01 baseline",
        "Construct a CPWD primary school for 180 students, 600 sq m, 2 floors, 12 months.",
        C(
            authority="cpwd",
            building_type="school",
            floor_area=600,
            floors=2,
            capacity=180,
            duration_months=12,
            options=set(),
        ),
    ),
    (
        "c02 thousands comma",
        "Construction of CPWD office building of 1,200 sq m with 3 storey.",
        C(authority="cpwd", building_type="office", floor_area=1200, floors=3),
    ),
    (
        "c03 railways",
        "New community hall for Railways, 450 sqm, 1 floor, 8 months.",
        C(authority="railway", building_type="community_hall", floor_area=450, floors=1, duration_months=8),
    ),
    (
        "c04 storeys",
        "State PWD school building, 800 square metres, 3 storeys.",
        C(authority="state_pwd", building_type="school", floor_area=800, floors=3),
    ),
    (
        "c05 stories",
        "Office block, 2 stories, 500 m2, for CPWD.",
        C(authority="cpwd", building_type="office", floor_area=500, floors=2),
    ),
    (
        "c06 G+2",
        "Proposed G+2 school building for CPWD, 900 sq.m total built-up area.",
        C(authority="cpwd", building_type="school", floor_area=900, floors=3),
    ),
    (
        "c07 ground plus two",
        "CPWD office, ground plus two floors, 1500 sq m.",
        C(authority="cpwd", building_type="office", floor_area=1500, floors=3),
    ),
    (
        "c08 sq ft",
        "CPWD school, built-up area 5,000 sq ft, 2 floors.",
        C(authority="cpwd", building_type="school", floor_area=464.5, floors=2),
    ),
    (
        "c09 Central PWD spelled",
        "Central Public Works Department: new office building of 700 sq m.",
        C(authority="cpwd", building_type="office", floor_area=700),
    ),
    (
        "c10 PWD (B&R)",
        "Public Works Department (B&R) community hall, 300 sq m, 6 months.",
        C(authority="state_pwd", building_type="community_hall", floor_area=300, duration_months=6),
    ),
    (
        "c11 options yes",
        "CPWD school of 600 sq m with solar rooftop and HVAC.",
        C(authority="cpwd", building_type="school", floor_area=600, options={"hvac", "solar"}),
    ),
    (
        "c12 options negated",
        "CPWD school, 600 sq m, without HVAC and no solar.",
        C(authority="cpwd", building_type="school", floor_area=600, options=set()),
    ),
    (
        "c13 air conditioning",
        "Office building with air conditioning for CPWD, 800 sq m.",
        C(authority="cpwd", building_type="office", floor_area=800, options={"hvac"}),
    ),
    (
        "c14 air-conditioned",
        "CPWD office, 800 sq m, air-conditioned throughout.",
        C(authority="cpwd", building_type="office", floor_area=800, options={"hvac"}),
    ),
    (
        "c15 no air conditioning",
        "CPWD office 800 sq m. No air conditioning required.",
        C(authority="cpwd", building_type="office", floor_area=800, options=set()),
    ),
    (
        "c16 18 months",
        "Construct CPWD school, 2400 sq m, 3 floors, completion in 18 months.",
        C(authority="cpwd", building_type="school", floor_area=2400, floors=3, duration_months=18),
    ),
    (
        "c17 people",
        "Office for 250 people, CPWD, 400 sq metre, 1 floor.",
        C(authority="cpwd", building_type="office", floor_area=400, floors=1, capacity=250),
    ),
    (
        "c18 students",
        "CPWD school, capacity of 300 students, 900 sqm, 2 floors.",
        C(authority="cpwd", building_type="school", floor_area=900, floors=2, capacity=300),
    ),
    (
        "c19 seating capacity",
        "CPWD community hall with seating capacity 500, 350 sq m.",
        C(authority="cpwd", building_type="community_hall", floor_area=350, capacity=500),
    ),
    (
        "c20 one year",
        "CPWD office. Construction period of one year, 600 sq m.",
        C(authority="cpwd", building_type="office", floor_area=600, duration_months=12),
    ),
    (
        "c21 within 2 months",
        "CPWD community hall 400 sq m, to be completed within 2 months.",
        C(authority="cpwd", building_type="community_hall", floor_area=400, duration_months=2),
    ),
    (
        "c22 12,000 sq m",
        "Built-up area 12,000 sq m office building for CPWD.",
        C(authority="cpwd", building_type="office", floor_area=12000),
    ),
    (
        "c23 DLP before completion",
        "CPWD school 600 sq m; defect liability period 12 months; work to be completed in 6 months.",
        C(authority="cpwd", building_type="school", floor_area=600, duration_months=6),
    ),
    (
        "c24 two authorities mentioned",
        "Construction of school building at railway colony for state PWD, 600 sq m.",
        C(authority="state_pwd", building_type="school", floor_area=600),
    ),
]

FIELDS = ["authority", "building_type", "floor_area", "floors", "capacity", "duration_months", "options"]
tally = {f: {"correct": 0, "missed": 0, "wrong": 0, "crash": 0, "n": 0} for f in FIELDS}
details = []
for name, text, gold in CASES:
    result = EstimateResult(
        project_id="p", revision_id="r", revision=1, brief=ProjectBrief.model_validate({"description": text})
    )
    try:
        agents.intake(result, "demo")
        b = result.brief
        got = {
            "authority": b.authority if b.authority != "unknown" else None,
            "building_type": b.building_type or None,
            "floor_area": float(b.floor_area) if b.floor_area is not None else None,
            "floors": b.floors,
            "capacity": b.capacity,
            "duration_months": float(b.duration_months) if b.duration_months is not None else None,
            "options": set(b.selected_options),
        }
        crash = None
    except Exception as exc:  # noqa: BLE001 - we are measuring failures
        got, crash = None, type(exc).__name__
    for f in FIELDS:
        if f not in gold:
            continue
        tally[f]["n"] += 1
        if crash:
            tally[f]["crash"] += 1
            continue
        g_, v = gold[f], got[f]
        if f == "options":
            ok = v == g_
            kind = "correct" if ok else "wrong"
        elif v is None:
            ok, kind = False, "missed"
        elif f in ("floor_area",):
            ok = abs(v - g_) <= 0.01 * g_
            kind = "correct" if ok else "wrong"
        elif f in ("floors", "capacity", "duration_months"):
            ok = abs(v - g_) < 1e-9
            kind = "correct" if ok else "wrong"
        else:
            ok = v == g_
            kind = "correct" if ok else "wrong"
        tally[f][kind] += 1
        if not ok:
            details.append((name, f, "gold=%r got=%r (%s)" % (g_, v, kind)))
    if crash:
        details.append((name, "ALL", "run crashed: " + crash))

print("%-16s %5s %8s %7s %6s %6s" % ("field", "n", "correct", "missed", "WRONG", "crash"))
for f in FIELDS:
    t = tally[f]
    print("%-16s %5d %8d %7d %6d %6d" % (f, t["n"], t["correct"], t["missed"], t["wrong"], t["crash"]))
tot = {k: sum(tally[f][k] for f in FIELDS) for k in ("n", "correct", "missed", "wrong", "crash")}
print(
    "%-16s %5d %8d %7d %6d %6d"
    % ("TOTAL", tot["n"], tot["correct"], tot["missed"], tot["wrong"], tot["crash"])
)
print("\nFailures:")
for d in details:
    print("  %-30s %-16s %s" % d)

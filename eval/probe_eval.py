"""Probe: does evaluation behave differently when demo packs are seeded? Reports the findings behind each result."""

import json
import sys
import tempfile
from pathlib import Path

from tender.config import Settings
from tender.db import Repository
from tender.demo import seed
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.schemas import Identity, ProjectBrief
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow

seeded = sys.argv[1] == "seeded"
scratch = Path(sys.argv[2])
scratch.mkdir(parents=True, exist_ok=True)
root = Path(tempfile.mkdtemp(prefix="probe-", dir=scratch))
settings = Settings(
    _env_file=None,
    data_dir=root / "var",
    database_dir=root / "db",
    database_url=f"sqlite:///{root}/state.db",
)
repo = Repository(settings)
gateway = KnowledgeGateway(repo, ObjectStore(settings), settings)
ingestor = FolderIngestor(gateway)
if seeded:
    seed(gateway)

cases = json.loads(Path(sys.argv[3]).read_text())
workflow = EstimationWorkflow(repo, gateway, ingestor)
try:
    for case in cases:
        actor = Identity(tenant=case.get("tenant", "demo"), user="probe")
        brief = ProjectBrief.model_validate(case["brief"])
        brief.review_design = False
        created = repo.create_project(brief, actor)
        token = repo.claim(created.revision_id, actor.tenant)
        workflow.execute(created.revision_id, actor, token)
        result = repo.get_revision(created.revision_id, actor.tenant).result
        print(f"\n## {case['name']}  [seeded={seeded}]")
        print("status:", result["status"], "| base_total:", result["base_total"])
        for f in result["findings"]:
            print(f"  - [{f['severity']}] {f['code']}: {f['message'][:150]}")
        for b in result["boq"]:
            if b["key"] in ("rcc", "reinforcement", "waterproofing"):
                print(
                    f"  BOQ {b['key']}: qty={b['quantity']} rate={b['unit_rate']} amount={b['amount']} status={b['status']}"
                )
        print("metrics:", {k: v for k, v in result["metrics"].items() if k != "ingestion"})
finally:
    workflow.close()
    repo.engine.dispose()

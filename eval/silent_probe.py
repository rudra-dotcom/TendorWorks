"""Does a thousands separator corrupt an estimate silently (no warning, plausible total)?"""

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

scratch = Path(sys.argv[1])
scratch.mkdir(parents=True, exist_ok=True)
root = Path(tempfile.mkdtemp(prefix="silent-", dir=scratch))
s = Settings(
    _env_file=None, data_dir=root / "var", database_dir=root / "db", database_url=f"sqlite:///{root}/s.db"
)
repo = Repository(s)
gw = KnowledgeGateway(repo, ObjectStore(s), s)
seed(gw)
wf = EstimationWorkflow(repo, gw, FolderIngestor(gw))


def run(desc):
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
        }
    )
    c = repo.create_project(b, actor)
    t = repo.claim(c.revision_id, actor.tenant)
    wf.execute(c.revision_id, actor, t)
    return repo.get_revision(c.revision_id, actor.tenant).result


for label, text in (
    ("plain", "Construction of CPWD office building of 2400 sq m with 2 floors."),
    ("comma", "Construction of CPWD office building of 2,400 sq m with 2 floors."),
):
    r = run(text)
    print(
        "%-5s floor_area=%s status=%s base_total=%s blocking=%s warnings=%s"
        % (
            label,
            r["brief"]["floor_area"],
            r["status"],
            r["base_total"],
            [f["code"] for f in r["findings"] if f["severity"] == "blocking"],
            [f["code"] for f in r["findings"] if f["severity"] == "warning"],
        )
    )
wf.close()

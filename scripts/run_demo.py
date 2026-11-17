"""Run the documented CPWD scenario and preserve its artifacts and audit logs."""

import argparse
import json
from pathlib import Path

from tender.config import Settings
from tender.db import Repository
from tender.demo import seed
from tender.ingestion import FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.schemas import Identity, ProjectBrief
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow

parser = argparse.ArgumentParser()
parser.add_argument("--offline", action="store_true", help="Deterministic smoke test; not an LLM benchmark")
args = parser.parse_args()
settings = Settings()
if args.offline:
    settings.model_provider = "offline"
    settings.web_enabled = False
repo = Repository(settings)
gateway = KnowledgeGateway(repo, ObjectStore(settings), settings)
if settings.seed_demo:
    seed(gateway)
ingestor = FolderIngestor(gateway)
report = ingestor.scan()
if report["failed"]:
    raise RuntimeError(report)
brief = ProjectBrief.model_validate_json(Path("examples/cpwd-office-demo.json").read_text())
actor = Identity()
created = repo.create_project(brief, actor)
token = repo.claim(created.revision_id, actor.tenant)
workflow = EstimationWorkflow(repo, gateway, ingestor)
try:
    workflow.execute(created.revision_id, actor, token)
    result = repo.get_revision(created.revision_id, actor.tenant).result
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/demo-result.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "revision_id": created.revision_id,
                "status": result["status"],
                "base_total": result["base_total"],
                "retrieved_chunks": result["metrics"].get("retrieved_chunks"),
                "web_research": result["metrics"].get("web_research"),
                "model_failures": [f for f in result["findings"] if f["code"] == "model_unavailable"],
                "url": f"http://127.0.0.1:8000/#estimate/{created.revision_id}",
            },
            indent=2,
        )
    )
    if not args.offline and any(f["code"] == "model_unavailable" for f in result["findings"]):
        raise SystemExit(2)
    if result["status"] != "draft" or result["base_total"] != "11028540.00":
        raise SystemExit(1)
finally:
    workflow.close()
    repo.engine.dispose()

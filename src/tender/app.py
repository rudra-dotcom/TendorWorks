import hashlib
import json
import mimetypes
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from tender.config import Settings
from tender.db import AuditRow, DocumentRow, FeedbackRow, FileImport, PackRow, Project, Repository, Revision
from tender.demo import seed
from tender.ingestion import SUPPORTED, FolderIngestor
from tender.knowledge import KnowledgeGateway
from tender.schemas import (
    DomainPack,
    EstimateResult,
    FeedbackDecision,
    FeedbackRequest,
    Identity,
    ProjectBrief,
    ReviewRequest,
    now,
)
from tender.storage import ObjectStore
from tender.workflow import EstimationWorkflow


class Approval(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    authority: str | None = None
    approved_only: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        repo = Repository(settings)
        objects = ObjectStore(settings)
        gateway = KnowledgeGateway(repo, objects, settings)
        ingestor = FolderIngestor(gateway)
        if settings.seed_demo:
            seed(gateway)
        ingestor.scan()
        workflow = EstimationWorkflow(repo, gateway, ingestor)
        app.state.repo, app.state.objects, app.state.gateway = repo, objects, gateway
        app.state.ingestor, app.state.workflow = ingestor, workflow
        yield
        workflow.close()
        repo.engine.dispose()

    app = FastAPI(
        title="Tenderworks",
        version="0.1.0",
        lifespan=lifespan,
        description="Concept-based government works estimates with auditable BOQs.",
    )
    bearer = HTTPBearer(auto_error=False)

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Identity:
        if credentials:
            for token, actor in settings.api_keys.items():
                if secrets.compare_digest(credentials.credentials, token):
                    return Identity.model_validate(actor)
            raise HTTPException(401, "Invalid API key")
        if settings.mode == "demo":
            return Identity()
        raise HTTPException(401, "Authentication required")

    def writer(actor: Identity = Depends(identity)) -> Identity:
        if actor.role == "viewer":
            raise HTTPException(403, "An engineer role is required")
        return actor

    def reviewer(actor: Identity = Depends(identity)) -> Identity:
        if actor.role not in ("reviewer", "admin"):
            raise HTTPException(403, "A reviewer role is required")
        return actor

    def admin(actor: Identity = Depends(identity)) -> Identity:
        if actor.role != "admin":
            raise HTTPException(403, "An administrator role is required")
        return actor

    @app.exception_handler(LookupError)
    async def missing(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path not in ("/docs", "/redoc"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'none'"
            )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config(actor: Identity = Depends(identity)):
        return {
            "mode": settings.mode,
            "identity": actor.model_dump(),
            "model_provider": settings.model_provider,
            "model_name": settings.model_name,
            "web_enabled": settings.web_enabled,
            "retrieval": "hybrid" if settings.embedding_url else "keyword",
            "currency": "INR",
            "database_folder": "database/",
            "draft_only": True,
        }

    @app.get("/api/projects")
    def projects(actor: Identity = Depends(identity)):
        return app.state.repo.list_projects(actor.tenant)

    @app.post("/api/projects", status_code=201)
    def create_project(brief: ProjectBrief, actor: Identity = Depends(writer)):
        if settings.mode == "production":
            brief.allow_demo = False
        return app.state.repo.create_project(brief, actor)

    @app.get("/api/projects/{project_id}/revisions")
    def revisions(project_id: str, actor: Identity = Depends(identity)):
        with app.state.repo.session() as session:
            rows = session.scalars(
                select(Revision)
                .join(Project)
                .where(Project.id == project_id, Project.tenant == actor.tenant)
                .order_by(Revision.number.desc())
            ).all()
            if not rows:
                raise LookupError("Project not found")
            return [
                {
                    "id": r.id,
                    "number": r.number,
                    "status": r.status,
                    "created_at": r.created_at,
                    "total": r.result.get("base_total"),
                }
                for r in rows
            ]

    @app.post("/api/projects/{project_id}/revisions", status_code=201)
    def revise(project_id: str, brief: ProjectBrief, actor: Identity = Depends(writer)):
        if settings.mode == "production":
            brief.allow_demo = False
        return app.state.repo.revise(project_id, brief, actor)

    @app.get("/api/revisions/{revision_id}")
    def revision(revision_id: str, actor: Identity = Depends(identity)):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        result = {**row.result, "status": row.status}
        return result

    @app.post("/api/revisions/{revision_id}/run", status_code=202)
    def run(revision_id: str, tasks: BackgroundTasks, actor: Identity = Depends(writer)):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        if row.status == "awaiting_review":
            raise HTTPException(409, "This revision is waiting for an explicit design review")
        if row.status == "needs_input":
            raise HTTPException(409, "Create a new revision after supplying missing inputs or knowledge")
        token = app.state.repo.claim(revision_id, actor.tenant)
        if not token:
            raise HTTPException(409, "Revision is already running or complete")
        tasks.add_task(app.state.workflow.execute, revision_id, actor, token)
        return {"revision_id": revision_id, "status": "running"}

    @app.post("/api/revisions/{revision_id}/review")
    def review(
        revision_id: str, body: ReviewRequest, tasks: BackgroundTasks, actor: Identity = Depends(reviewer)
    ):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        result = EstimateResult.model_validate(row.result)
        if body.decision == "accept_design":
            if row.status != "awaiting_review":
                raise HTTPException(409, "Revision is not awaiting design review")
            token = app.state.repo.claim(revision_id, actor.tenant)
            if not token:
                raise HTTPException(409, "Revision is already being resumed")
            tasks.add_task(app.state.workflow.execute, revision_id, actor, token, body.model_dump())
        elif body.decision == "mark_reviewed":
            if result.demo:
                raise HTTPException(409, "Synthetic demo estimates cannot be marked reviewed")
            if (
                row.status != "draft"
                or result.base_total is None
                or any(f.severity == "blocking" for f in result.findings)
            ):
                raise HTTPException(
                    409, "Only complete draft estimates without blocking findings can be reviewed"
                )
            result.status = "reviewed"
            app.state.repo.save_result(result)
        else:
            if row.status == "running":
                raise HTTPException(409, "Wait for the active run before requesting a revision")
        app.state.repo.audit(actor, "estimate_review", revision_id, body.model_dump())
        return {
            "decision": body.decision,
            "message": "Create a new revision to apply corrections."
            if body.decision == "request_changes"
            else "Review recorded.",
        }

    @app.get("/api/revisions/{revision_id}/artifacts/{name}")
    def artifact(revision_id: str, name: str, actor: Identity = Depends(identity)):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        reference = row.result.get("artifacts", {}).get(name)
        if not reference:
            raise LookupError("Artifact not found")
        return Response(
            app.state.objects.get(reference),
            media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/revisions/{revision_id}/evidence/{evidence_id:path}")
    def evidence(revision_id: str, evidence_id: str, actor: Identity = Depends(identity)):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        record = next((e for e in row.result["evidence"] if e["id"] == evidence_id), None)
        if not record:
            raise LookupError("Evidence not found")
        return record

    @app.post("/api/revisions/{revision_id}/feedback", status_code=201)
    def feedback(revision_id: str, body: FeedbackRequest, actor: Identity = Depends(writer)):
        row = app.state.repo.get_revision(revision_id, actor.tenant)
        if body.item_id and body.item_id not in {b["id"] for b in row.result["boq"]}:
            raise ValueError("Feedback refers to an unknown BOQ item")
        with app.state.repo.session.begin() as session:
            entry = FeedbackRow(
                tenant=actor.tenant, revision_id=revision_id, author=actor.user, payload=body.model_dump()
            )
            session.add(entry)
            session.flush()
            entry_id = entry.id
        return {
            "id": entry_id,
            "status": "pending",
            "message": "Feedback is queued for review; source data is unchanged.",
        }

    @app.post("/api/revisions/{revision_id}/feedback/import", status_code=201)
    async def import_feedback(revision_id: str, file: UploadFile, actor: Identity = Depends(writer)):
        from tempfile import NamedTemporaryFile

        from tender.evaluation_reports import import_feedback as import_workbook

        row = app.state.repo.get_revision(revision_id, actor.tenant)
        with NamedTemporaryFile(suffix=".xlsx") as temporary:
            temporary.write(await file.read())
            temporary.flush()

            def create(category, item_id, comment, value):
                payload = {
                    "category": category,
                    "item_id": item_id if item_id in {b["id"] for b in row.result["boq"]} else None,
                    "comment": comment[:4000],
                    "proposed_value": value[:500] if value else None,
                    "workbook_row_id": item_id,
                }
                with app.state.repo.session.begin() as session:
                    session.add(
                        FeedbackRow(
                            tenant=actor.tenant, revision_id=revision_id, author=actor.user, payload=payload
                        )
                    )

            count = import_workbook(Path(temporary.name), revision_id, create)
        return {
            "status": "pending",
            "imported": count,
            "message": "Feedback is queued; results and source data are unchanged.",
        }

    @app.get("/api/feedback")
    def feedback_list(actor: Identity = Depends(identity)):
        with app.state.repo.session() as session:
            return [
                {
                    "id": r.id,
                    "revision_id": r.revision_id,
                    "status": r.status,
                    "author": r.author,
                    "payload": r.payload,
                    "decision": r.decision,
                    "created_at": r.created_at,
                }
                for r in session.scalars(
                    select(FeedbackRow)
                    .where(FeedbackRow.tenant == actor.tenant)
                    .order_by(FeedbackRow.created_at.desc())
                )
            ]

    @app.post("/api/feedback/{feedback_id}/review")
    def feedback_review(feedback_id: str, body: FeedbackDecision, actor: Identity = Depends(reviewer)):
        with app.state.repo.session.begin() as session:
            row = session.get(FeedbackRow, feedback_id)
            if not row or row.tenant != actor.tenant:
                raise LookupError("Feedback not found")
            if row.status != "pending":
                raise HTTPException(409, "Feedback already reviewed")
            row.status = body.decision
            row.decision = {**body.model_dump(), "reviewer": actor.user, "at": now()}
        app.state.repo.audit(actor, "feedback_reviewed", feedback_id, body.model_dump())
        return {
            "status": body.decision,
            "message": "Accepted feedback enters evaluation; rates and rules are not overwritten.",
        }

    @app.get("/api/knowledge")
    def knowledge(actor: Identity = Depends(identity)):
        with app.state.repo.session() as session:
            documents = [
                {
                    "id": d.id,
                    "title": d.payload["title"],
                    "version": d.payload["version"],
                    "trust": d.trust,
                    "authority": d.authority,
                    "active": d.active,
                    "locator": d.payload.get("locator"),
                    "hash": d.payload.get("content_hash"),
                    "effective_from": d.payload["effective_from"],
                }
                for d in session.scalars(select(DocumentRow).where(DocumentRow.tenant == actor.tenant))
            ]
            imports = [
                {
                    "path": f.path,
                    "status": f.status,
                    "digest": f.digest,
                    "error": f.error,
                    "updated_at": f.updated_at,
                }
                for f in session.scalars(select(FileImport).where(FileImport.tenant == actor.tenant))
            ]
        packs = [
            {
                "id": id_,
                "name": p.name,
                "version": p.version,
                "authority": p.authority,
                "states": p.states,
                "trust": p.trust,
                "rates": len(p.rates),
                "supported_buildings": p.supported_buildings,
            }
            for id_, p in app.state.gateway.packs(actor.tenant)
        ]
        return {
            "documents": documents,
            "packages": packs,
            "imports": imports,
            "retrieval": "hybrid" if settings.embedding_url else "keyword",
        }

    @app.post("/api/knowledge/scan")
    def scan(actor: Identity = Depends(writer)):
        report = app.state.ingestor.scan(actor.tenant)
        app.state.repo.audit(
            actor, "folder_scanned", "database", {k: v for k, v in report.items() if k != "files"}
        )
        return report

    @app.post("/api/knowledge/search")
    def search(body: SearchRequest, actor: Identity = Depends(identity)):
        return app.state.gateway.search(
            body.query, actor.tenant, body.authority, approved_only=body.approved_only
        )

    @app.post("/api/knowledge/packages", status_code=201)
    def import_pack(body: DomainPack, actor: Identity = Depends(admin)):
        pack_id = app.state.gateway.import_pack(body, actor)
        with app.state.repo.session() as session:
            status = session.get(PackRow, pack_id).trust
        return {"id": pack_id, "status": status}

    @app.get("/api/knowledge/packages/schema")
    def pack_schema(actor: Identity = Depends(identity)):
        return DomainPack.model_json_schema()

    @app.get("/api/knowledge/packages/{pack_id}")
    def get_pack(pack_id: str, actor: Identity = Depends(identity)):
        with app.state.repo.session() as session:
            row = session.get(PackRow, pack_id)
            if not row or row.tenant != actor.tenant:
                raise LookupError("Package not found")
            return row.payload

    @app.post("/api/knowledge/packages/{pack_id}/approve")
    def approve_pack(pack_id: str, body: Approval, actor: Identity = Depends(admin)):
        app.state.gateway.approve_pack(pack_id, actor, body.reason)
        return {"status": "approved"}

    @app.post("/api/knowledge/upload", status_code=201)
    async def upload(
        file: UploadFile = File(...), metadata: str = Form("{}"), actor: Identity = Depends(writer)
    ):
        name = Path(file.filename or "upload.txt").name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED or name.endswith(".meta.json"):
            raise ValueError("Unsupported source document format")
        content = await file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Source exceeds upload size limit")
        metadata_dict = json.loads(metadata)
        if not isinstance(metadata_dict, dict):
            raise ValueError("Metadata must be an object")
        if name.endswith(".pack.json") and actor.role != "admin":
            raise HTTPException(403, "Package ingestion requires administrator role")
        folder = settings.data_dir / "uploads" / hashlib.sha256(actor.tenant.encode()).hexdigest()[:16]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        with app.state.ingestor.lock:
            path.write_bytes(content)
            path.with_name(name + ".meta.json").write_text(json.dumps(metadata_dict))
            result = app.state.ingestor.ingest_file(path, folder, actor.tenant, namespace="uploads/")
        return result

    @app.get("/api/knowledge/documents/{document_id}/source")
    def source(document_id: str, actor: Identity = Depends(identity)):
        with app.state.repo.session() as session:
            row = session.get(DocumentRow, document_id)
            if not row or row.tenant != actor.tenant:
                raise LookupError("Source not found")
            doc = row.payload
        content = app.state.objects.get(doc["snapshot_ref"])
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="source-snapshot"'},
        )

    @app.get("/api/audit")
    def audit(actor: Identity = Depends(reviewer)):
        with app.state.repo.session() as session:
            return [
                {
                    "id": e.id,
                    "user": e.user,
                    "action": e.action,
                    "target": e.target,
                    "payload": e.payload,
                    "created_at": e.created_at,
                }
                for e in session.scalars(
                    select(AuditRow)
                    .where(AuditRow.tenant == actor.tenant)
                    .order_by(AuditRow.created_at.desc())
                    .limit(200)
                )
            ]

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    return app

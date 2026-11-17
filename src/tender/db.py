"""Relational state, append-only source versions, exact numeric rates, and job leases."""

import time
import uuid
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    select,
    text,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from tender.config import Settings
from tender.schemas import EstimateResult, Identity, ProjectBrief, now


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="queued")
    result: Mapped[dict] = mapped_column(JSON)
    pack_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    run_token: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)


class PackRow(Base):
    __tablename__ = "domain_packs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    authority: Mapped[str] = mapped_column(String, index=True)
    trust: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)


class DocumentRow(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    authority: Mapped[str] = mapped_column(String, index=True)
    trust: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChunkRow(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # Dimension is checked by the embedder. Unbounded pgvector permits configured providers.
    embedding: Mapped[list | None] = mapped_column(JSON().with_variant(Vector(), "postgresql"))
    embedding_model: Mapped[str] = mapped_column(String, default="")


class RateRow(Base):
    __tablename__ = "rates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    pack_id: Mapped[str] = mapped_column(ForeignKey("domain_packs.id"), index=True)
    component_key: Mapped[str] = mapped_column(String, index=True)
    item_code: Mapped[str] = mapped_column(String, index=True)
    unit: Mapped[str] = mapped_column(String)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    payload: Mapped[dict] = mapped_column(JSON)


class FileImport(Base):
    __tablename__ = "file_imports"
    __table_args__ = (UniqueConstraint("tenant", "path"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String)
    document_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, index=True)
    user: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)


class FeedbackRow(Base):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("revisions.id"))
    author: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    payload: Mapped[dict] = mapped_column(JSON)
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        sqlite = settings.database_url.startswith("sqlite")
        self.engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False, "timeout": 30} if sqlite else {},
            pool_pre_ping=True,
        )
        if sqlite:

            @event.listens_for(self.engine, "connect")
            def pragmas(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
        else:
            with self.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        self._migrate()
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self):
        """Upgrade app tables only; LangGraph owns its checkpoint tables."""
        from pathlib import Path

        from alembic.config import Config
        from sqlalchemy import inspect

        from alembic import command

        root = Path(__file__).resolve().parents[2]
        cfg = Config(str(root / "alembic.ini"))
        # Alembic resolves a relative script_location from the process CWD,
        # which is often eval/ for the diagnostic probes.
        cfg.set_main_option("script_location", str(root / "alembic"))
        cfg.set_main_option("sqlalchemy.url", self.settings.database_url)
        tables = set(inspect(self.engine).get_table_names())
        app_tables = set(Base.metadata.tables)
        if tables & app_tables and "alembic_version" not in tables:
            command.stamp(cfg, "head")
        command.upgrade(cfg, "head")

    def corrections_stopped(self, revision_id: str, tenant: str) -> bool:
        with self.session() as session:
            return (
                session.scalar(
                    select(AuditRow.id)
                    .where(
                        AuditRow.tenant == tenant,
                        AuditRow.target == revision_id,
                        AuditRow.action == "skip_corrections",
                    )
                    .limit(1)
                )
                is not None
            )

    def audit(self, identity: Identity, action: str, target: str, payload: dict):
        with self.session.begin() as session:
            session.add(
                AuditRow(
                    tenant=identity.tenant, user=identity.user, action=action, target=target, payload=payload
                )
            )

    def create_project(self, brief: ProjectBrief, identity: Identity) -> EstimateResult:
        with self.session.begin() as session:
            project = Project(tenant=identity.tenant, title=brief.title)
            session.add(project)
            session.flush()
            result = EstimateResult(project_id=project.id, revision_id=uid(), revision=1, brief=brief)
            session.add(
                Revision(
                    id=result.revision_id,
                    project_id=project.id,
                    number=1,
                    result=result.model_dump(mode="json"),
                )
            )
        self.audit(identity, "project_created", project.id, {"revision_id": result.revision_id})
        return result

    def get_revision(self, revision_id: str, tenant: str) -> Revision:
        with self.session() as session:
            row = session.scalar(
                select(Revision).join(Project).where(Revision.id == revision_id, Project.tenant == tenant)
            )
            if row is None:
                raise LookupError("Revision not found")
            return row

    def list_projects(self, tenant: str) -> list[dict]:
        with self.session() as session:
            rows = session.execute(
                select(Project, Revision)
                .join(Revision)
                .where(Project.tenant == tenant)
                .order_by(Project.created_at.desc(), Revision.number.desc())
            ).all()
            seen = set()
            results = []
            for project, revision in rows:
                if project.id in seen:
                    continue
                seen.add(project.id)
                result = revision.result
                results.append(
                    {
                        "id": project.id,
                        "title": result["brief"]["title"],
                        "revision_id": revision.id,
                        "revision": revision.number,
                        "status": revision.status,
                        "created_at": project.created_at,
                        "authority": result["brief"]["authority"],
                        "location": result["brief"]["location"],
                        "demo": result.get("demo", False),
                        "total": result.get("base_total"),
                        "known_subtotal": result.get("known_subtotal", "0"),
                    }
                )
            return results

    def revise(self, project_id: str, brief: ProjectBrief, identity: Identity) -> EstimateResult:
        with self.session.begin() as session:
            project = session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.tenant == identity.tenant)
                .with_for_update()
            )
            if not project:
                raise LookupError("Project not found")
            latest = session.scalar(
                select(Revision)
                .where(Revision.project_id == project_id)
                .order_by(Revision.number.desc())
                .limit(1)
            )
            result = EstimateResult(
                project_id=project_id, revision_id=uid(), revision=latest.number + 1, brief=brief
            )
            session.add(
                Revision(
                    id=result.revision_id,
                    project_id=project_id,
                    number=result.revision,
                    result=result.model_dump(mode="json"),
                )
            )
        self.audit(identity, "project_revised", project_id, {"revision": result.revision})
        return result

    def claim(self, revision_id: str, tenant: str) -> str | None:
        self.get_revision(revision_id, tenant)
        token = uid()
        with self.session.begin() as session:
            count = session.execute(
                update(Revision)
                .where(
                    Revision.id == revision_id,
                    Revision.lease_until < time.time(),
                    Revision.status.not_in(["draft", "incomplete", "reviewed"]),
                )
                .values(
                    lease_until=time.time() + self.settings.lease_seconds, run_token=token, status="running"
                )
            ).rowcount
            return token if count else None

    def save_result(self, result: EstimateResult, token: str | None = None):
        with self.session.begin() as session:
            stmt = update(Revision).where(Revision.id == result.revision_id)
            if token:
                stmt = stmt.where(Revision.run_token == token)
            values = {"result": result.model_dump(mode="json"), "status": result.status}
            if token:
                values["lease_until"] = time.time() + self.settings.lease_seconds
            if not session.execute(stmt.values(**values)).rowcount:
                raise RuntimeError("Revision lease lost")

    def release(self, revision_id: str, token: str):
        with self.session.begin() as session:
            session.execute(
                update(Revision)
                .where(Revision.id == revision_id, Revision.run_token == token)
                .values(lease_until=0, run_token=None)
            )

    def pin_pack(self, revision_id: str, payload: dict):
        with self.session.begin() as session:
            session.execute(
                update(Revision)
                .where(Revision.id == revision_id, Revision.pack_snapshot.is_(None))
                .values(pack_snapshot=payload)
            )

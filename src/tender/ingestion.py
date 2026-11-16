"""Incremental folder ingestion, keyed by bytes AND metadata, with immutable history."""

import csv
import hashlib
import io
import json
import threading
from datetime import date
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select

from tender.db import DocumentRow, FileImport
from tender.drafts import DraftPackGenerator
from tender.knowledge import KnowledgeGateway, key
from tender.schemas import DomainPack, Identity, SourceDocument, now

SUPPORTED = {".pdf", ".txt", ".md", ".csv", ".xlsx", ".docx", ".json"}


def extract(content: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > 2000:
            raise ValueError("PDF exceeds the 2,000 page extraction limit")
        pages = [(i, page.extract_text() or "") for i, page in enumerate(reader.pages, 1)]
        if sum(len(text.strip()) for _, text in pages) < 20:
            raise ValueError("PDF has no usable text; run OCR and place the searchable PDF in database/")
        text = "\n\n".join(f"[Page {i}]\n{body}" for i, body in pages)
    elif suffix == ".docx":
        doc = Document(io.BytesIO(content))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            parts.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
        text = "\n".join(parts)
    elif suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        parts = []
        for sheet in workbook:
            if sheet.max_row and sheet.max_row > 100000:
                raise ValueError("Worksheet exceeds row limit")
            parts.append(f"[Sheet: {sheet.title}]")
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, ())
            for number, row in enumerate(rows, 2):
                parts.append(
                    f"Row {number}: " + " | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False))
                )
        workbook.close()
        text = "\n".join(parts)
    elif suffix == ".csv":
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        text = "\n".join(
            f"Row {i}: " + " | ".join(f"{k}: {v}" for k, v in row.items()) for i, row in enumerate(reader, 2)
        )
    elif suffix == ".json":
        text = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
    else:
        text = content.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("Document contains no extractable content")
    if len(text) > 500000:
        raise ValueError("Extracted text exceeds 500,000 characters; split the document into volumes")
    return text


class FolderIngestor:
    def __init__(self, gateway: KnowledgeGateway):
        self.gateway, self.repo = gateway, gateway.repo
        self.drafts = DraftPackGenerator(gateway.settings)
        self.lock = threading.Lock()
        self.last_report = {"added": 0, "updated": 0, "skipped": 0, "failed": 0, "files": []}

    def ingest_file(self, path: Path, root: Path, tenant: str, namespace: str = "") -> dict:
        relative = namespace + str(path.relative_to(root))
        metadata_path = path.with_name(path.name + ".meta.json")
        content = path.read_bytes()
        metadata_bytes = metadata_path.read_bytes() if metadata_path.is_file() else b"{}"
        digest = hashlib.sha256(content + b"\x00" + metadata_bytes).hexdigest()
        with self.repo.session() as session:
            previous = session.scalar(
                select(FileImport).where(FileImport.tenant == tenant, FileImport.path == relative)
            )
            if previous and previous.digest == digest and previous.status == "indexed":
                return {"path": relative, "status": "skipped", "digest": digest}
        doc_id = None
        status = "updated" if previous else "added"
        error = None
        try:
            if len(content) > self.gateway.settings.max_upload_bytes:
                raise ValueError("File exceeds the configured upload limit")
            if path.name.endswith(".pack.json"):
                pack = DomainPack.model_validate_json(content)
                doc_id = self.gateway.import_pack(pack, Identity(tenant=tenant, user="folder-ingestion"))
            else:
                metadata = json.loads(metadata_bytes)
                text = extract(content, path.suffix.lower())
                doc = SourceDocument(
                    id=key(tenant, digest),
                    title=metadata.get("title", path.stem),
                    version=metadata.get("version", digest[:12]),
                    kind="rule" if metadata.get("kind") == "norms" else metadata.get("kind", "web"),
                    authority=metadata.get("authority", "unknown"),
                    state=metadata.get("state", ""),
                    discipline=metadata.get("discipline", "all"),
                    url=metadata.get("url", ""),
                    effective_from=metadata.get("effective_from", date(1900, 1, 1)),
                    effective_to=metadata.get("effective_to"),
                    text=text,
                    locator=relative,
                    trust="candidate",
                    snapshot_ref=self.gateway.objects.put(content),
                    content_hash=hashlib.sha256(content).hexdigest(),
                )
                doc_id = self.gateway.index_document(doc, tenant)
        except Exception as exc:
            status, error = "failed", str(exc)[:1200]
        with self.repo.session.begin() as session:
            row = session.scalar(
                select(FileImport).where(FileImport.tenant == tenant, FileImport.path == relative)
            )
            if row is None:
                row = FileImport(tenant=tenant, path=relative, digest=digest)
                session.add(row)
            # Superseded inbox versions remain stored but cease to be current retrieval candidates.
            if status != "failed" and row.document_id and row.document_id != doc_id:
                old = session.get(DocumentRow, row.document_id)
                shared = session.scalar(
                    select(FileImport).where(
                        FileImport.tenant == tenant,
                        FileImport.document_id == row.document_id,
                        FileImport.path != relative,
                        FileImport.status == "indexed",
                    )
                )
                if old and not shared:
                    old.active = False
            row.digest, row.status, row.error = digest, "failed" if error else "indexed", error
            if doc_id:
                row.document_id = doc_id
            row.updated_at = now()
        return {"path": relative, "status": status, "digest": digest, "error": error, "document_id": doc_id}

    def scan(self, tenant: str | None = None) -> dict:
        settings = self.gateway.settings
        tenant = tenant or settings.database_tenant
        if tenant != settings.database_tenant:
            return {
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "files": [],
                "note": "Server inbox belongs to a different tenant; use uploads.",
            }
        root = settings.database_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        report = {"added": 0, "updated": 0, "skipped": 0, "failed": 0, "files": [], "at": now()}
        with self.lock:
            for path in sorted(root.rglob("*")):
                if (
                    not path.is_file()
                    or path.suffix.lower() not in SUPPORTED
                    or path.name.endswith(".meta.json")
                    or path.name == "README.md"
                    or not path.resolve().is_relative_to(root)
                ):
                    continue
                try:
                    result = self.ingest_file(path, root, tenant)
                except Exception as exc:
                    result = {"path": str(path.relative_to(root)), "status": "failed", "error": str(exc)}
                report[result["status"]] += 1
                report["files"].append(result)
                if path.suffix.lower() == ".pdf" and result["status"] in {"added", "updated"}:
                    metadata_path = path.with_name(path.name + ".meta.json")
                    metadata = json.loads(metadata_path.read_bytes()) if metadata_path.is_file() else {}
                    if metadata.get("kind") in {"schedule", "specification", "rule", "norms"}:
                        try:
                            report.setdefault("drafts", []).append(
                                self.drafts.generate(path, metadata, path.read_bytes())
                            )
                        except Exception as exc:
                            report.setdefault("drafts", []).append(
                                {"path": str(path.relative_to(root)), "status": "failed", "error": str(exc)[:1200]}
                            )
            report["embedding_backfilled"] = self.gateway.backfill_embeddings(tenant)
            self.last_report = report
        return report

    def draft_files(self, tenant: str | None = None) -> list[dict]:
        """Manually rebuild review artifacts; never imports a generated package."""
        tenant = tenant or self.gateway.settings.database_tenant
        if tenant != self.gateway.settings.database_tenant:
            return [{"status": "skipped", "message": "Server inbox belongs to a different tenant; use uploads."}]
        root = self.gateway.settings.database_dir.resolve()
        results = []
        for path in sorted(root.rglob("*.pdf")):
            if not path.resolve().is_relative_to(root):
                continue
            metadata_path = path.with_name(path.name + ".meta.json")
            metadata = json.loads(metadata_path.read_bytes()) if metadata_path.is_file() else {}
            if metadata.get("kind") not in {"schedule", "specification", "rule", "norms"}:
                continue
            try:
                results.append(self.drafts.generate(path, metadata, path.read_bytes()))
            except Exception as exc:
                results.append({"path": str(path.relative_to(root)), "status": "failed", "error": str(exc)[:1200]})
        return results

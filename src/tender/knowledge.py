"""Shared retrieval gateway. Similarity finds evidence; it never selects a numeric rate."""

import hashlib
import math
import re
from collections import Counter
from datetime import date
from functools import cached_property

import httpx
import numpy as np
from sqlalchemy import select

from tender.config import Settings
from tender.db import ChunkRow, DocumentRow, PackRow, RateRow, Repository
from tender.schemas import DomainPack, Identity, RateRecord, SourceDocument
from tender.storage import ObjectStore


def key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:40]


def tokens(value: str) -> list[str]:
    return re.findall(r"[\w.-]+", value.casefold())


def in_period(start: date, end: date | None, when: date) -> bool:
    return start <= when and (end is None or when <= end)


class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.name = settings.nvidia_embedding_model or settings.embedding_url
        self._dimension: int | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.name)

    @cached_property
    def nvidia(self):
        from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

        options = {"model": self.settings.nvidia_embedding_model, "api_key": self.settings.nvidia_api_key}
        if self.settings.nvidia_base_url:
            options["base_url"] = self.settings.nvidia_base_url
        return NVIDIAEmbeddings(**options)

    @property
    def model_id(self) -> str:
        return f"{self.name}:{self._dimension}" if self._dimension else self.name

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float] | None]:
        if not self.enabled:
            return [None] * len(texts)
        if self.settings.nvidia_embedding_model:
            vectors = [self.nvidia.embed_query(texts[0])] if query else self.nvidia.embed_documents(texts)
        else:
            response = httpx.post(
                self.name,
                json={"texts": texts},
                timeout=60,
                headers={"Authorization": f"Bearer {self.settings.embedding_key}"},
            )
            response.raise_for_status()
            vectors = response.json()["vectors"]
        if len(vectors) != len(texts):
            raise ValueError("Embedding provider returned the wrong number of vectors")
        sizes = {len(v) for v in vectors}
        if (
            len(sizes) != 1
            or not next(iter(sizes))
            or not all(math.isfinite(float(n)) for v in vectors for n in v)
        ):
            raise ValueError("Embedding provider returned invalid vectors")
        self._dimension = next(iter(sizes))
        return vectors


def chunk_document(content: str) -> list[tuple[str, str]]:
    """Keep PDF page locators and prefer paragraph/heading boundaries under a conservative token cap."""
    pages = re.split(r"(?=\[Page \d+\])", content)
    chunks: list[tuple[str, str]] = []
    for page in pages:
        number = re.search(r"\[Page (\d+)\]", page)
        locator = f"Page {number.group(1)}" if number else ""
        pieces = re.split(r"\n\s*\n|(?=^\s*(?:\d+(?:\.\d+)*[.)]|[A-Z][A-Z /-]{4,})\s*$)", page, flags=re.M)
        current = ""
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            candidate = f"{current}\n\n{piece}".strip()
            if len(candidate) <= 1800:
                current = candidate
                continue
            if current:
                chunks.append((current, locator))
            while len(piece) > 1800:
                split_at = max(piece.rfind(" ", 0, 1800), piece.rfind("\n", 0, 1800), 1)
                chunks.append((piece[:split_at].strip(), locator))
                piece = piece[split_at:].strip()
            current = piece
        if current:
            chunks.append((current, locator))
    return chunks or [(content[:1800], "")]


class KnowledgeGateway:
    def __init__(self, repo: Repository, objects: ObjectStore, settings: Settings):
        self.repo, self.objects, self.settings = repo, objects, settings
        self.embedder = Embedder(settings)

    @property
    def embedding_model_id(self) -> str:
        """Keep lightweight evaluation fakes compatible with the production embedder."""
        return getattr(self.embedder, "model_id", getattr(self.embedder, "name", ""))

    @property
    def embeddings_enabled(self) -> bool:
        return getattr(self.embedder, "enabled", bool(getattr(self.embedder, "name", "")))

    def index_document(self, document: SourceDocument, tenant: str, namespace: str = "inbox") -> str:
        if not document.content_hash:
            document.content_hash = hashlib.sha256(document.text.encode()).hexdigest()
        doc_id = key(tenant, namespace, document.id, document.content_hash)
        with self.repo.session.begin() as session:
            existing = session.get(DocumentRow, doc_id)
            if existing:
                existing.active = True
                if not self.embeddings_enabled:
                    return doc_id
                stale = session.scalars(select(ChunkRow).where(ChunkRow.document_id == doc_id)).all()
                if self.embedder._dimension is None and stale:
                    model, separator, dimension = stale[0].embedding_model.rpartition(":")
                    if separator and model == self.embedder.name and dimension.isdigit():
                        self.embedder._dimension = int(dimension)
                if stale and all(chunk.embedding_model == self.embedding_model_id for chunk in stale):
                    return doc_id
        content = document.text
        chunk_data = chunk_document(content)
        chunks = [chunk for chunk, _ in chunk_data]
        try:
            vectors = []
            for offset in range(0, len(chunks), 32):
                vectors.extend(self.embedder.embed(chunks[offset : offset + 32]))
        except Exception:
            # Text remains searchable even when an optional embedding endpoint is unavailable.
            vectors = [None] * len(chunks)
        if not document.snapshot_ref:
            document.snapshot_ref = self.objects.put(content.encode())
        if not document.content_hash:
            document.content_hash = hashlib.sha256(content.encode()).hexdigest()
        with self.repo.session.begin() as session:
            row = session.get(DocumentRow, doc_id)
            if row is None:
                row = DocumentRow(
                    id=doc_id,
                    tenant=tenant,
                    authority=document.authority,
                    trust=document.trust,
                    payload=document.model_dump(mode="json"),
                )
                session.add(row)
            else:
                session.query(ChunkRow).filter(ChunkRow.document_id == doc_id).delete()
            session.flush()
            for i, ((chunk, locator), vector) in enumerate(zip(chunk_data, vectors, strict=True)):
                session.add(
                    ChunkRow(
                        id=f"{doc_id}-{i}",
                        document_id=doc_id,
                        position=i,
                        content=chunk,
                        embedding=vector,
                        embedding_model=self.embedding_model_id if vector is not None else "",
                    )
                )
        return doc_id

    def backfill_embeddings(self, tenant: str) -> int:
        """Refresh vectors for the configured model without making a failed embedding block text search."""
        if not self.embeddings_enabled:
            return 0
        with self.repo.session() as session:
            rows = session.scalars(select(DocumentRow).where(DocumentRow.tenant == tenant)).all()
            documents = [(row.id, SourceDocument.model_validate(row.payload)) for row in rows]
        refreshed = 0
        for doc_id, document in documents:
            with self.repo.session() as session:
                chunks = session.scalars(select(ChunkRow).where(ChunkRow.document_id == doc_id)).all()
                if self.embedder._dimension is None and chunks:
                    model, separator, dimension = chunks[0].embedding_model.rpartition(":")
                    if separator and model == self.embedder.name and dimension.isdigit():
                        self.embedder._dimension = int(dimension)
                if chunks and all(chunk.embedding_model == self.embedding_model_id for chunk in chunks):
                    continue
            data = chunk_document(document.text)
            try:
                vectors = []
                for offset in range(0, len(data), 32):
                    vectors.extend(self.embedder.embed([text for text, _ in data[offset : offset + 32]]))
            except Exception:
                vectors = [None] * len(data)
            with self.repo.session.begin() as session:
                session.query(ChunkRow).filter(ChunkRow.document_id == doc_id).delete()
                for position, ((text, _), vector) in enumerate(zip(data, vectors, strict=True)):
                    session.add(
                        ChunkRow(
                            id=f"{doc_id}-{position}",
                            document_id=doc_id,
                            position=position,
                            content=text,
                            embedding=vector,
                            embedding_model=self.embedding_model_id if vector is not None else "",
                        )
                    )
            refreshed += 1
        return refreshed

    def import_pack(self, pack: DomainPack, identity: Identity, *, internal_demo: bool = False) -> str:
        pack = pack.model_copy(deep=True)
        pack_id = key(identity.tenant, pack.id, pack.version)
        with self.repo.session() as session:
            existing = session.get(PackRow, pack_id)
            if existing:
                # Import is idempotent, but an existing version cannot be silently changed.
                old = DomainPack.model_validate(existing.payload)

                def comparable(p):
                    data = p.model_dump(mode="json")
                    data.pop("trust", None)
                    for d in data["documents"]:
                        for field in ("trust", "snapshot_ref", "content_hash", "retrieved_at"):
                            d.pop(field, None)
                    return data

                if comparable(old) != comparable(pack):
                    raise ValueError(
                        "This package version already exists with different content; increment version"
                    )
                return pack_id
        is_demo = internal_demo or pack.trust == "demo" or any(d.trust == "demo" for d in pack.documents)
        if is_demo and self.settings.mode == "production":
            raise ValueError("Synthetic demonstration packages cannot be imported into production")
        pack.trust = "demo" if is_demo else "candidate"
        for doc in pack.documents:
            doc.trust = pack.trust
            # Recompute snapshots from the submitted source content; clients cannot forge object refs.
            doc.snapshot_ref = self.objects.put(doc.text.encode())
            doc.content_hash = hashlib.sha256(doc.text.encode()).hexdigest()
            self.index_document(doc, identity.tenant, pack_id)
        with self.repo.session.begin() as session:
            session.add(
                PackRow(
                    id=pack_id,
                    tenant=identity.tenant,
                    authority=pack.authority,
                    trust=pack.trust,
                    payload=pack.model_dump(mode="json"),
                )
            )
            session.flush()
            for rate in pack.rates:
                session.add(
                    RateRow(
                        id=key(pack_id, rate.id),
                        pack_id=pack_id,
                        component_key=rate.component_key,
                        item_code=rate.item_code,
                        unit=rate.unit,
                        value=rate.value,
                        payload=rate.model_dump(mode="json"),
                    )
                )
        self.repo.audit(identity, "pack_imported", pack_id, {"version": pack.version, "trust": pack.trust})
        return pack_id

    def approve_pack(self, pack_id: str, identity: Identity, reason: str):
        with self.repo.session.begin() as session:
            row = session.get(PackRow, pack_id)
            if not row or row.tenant != identity.tenant:
                raise LookupError("Package not found")
            if row.trust == "demo":
                raise ValueError("Synthetic demo data cannot be promoted to official data")
            pack = DomainPack.model_validate(row.payload)
            if pack.authority == "unknown":
                raise ValueError("Package authority must be resolved before approval")
            pack.trust = "approved"
            for doc in pack.documents:
                if doc.authority not in (pack.authority, "unknown"):
                    # Cross-authority adoption must be represented as a package rule, not rejected.
                    if not pack.rules:
                        raise ValueError("Cross-authority sources require an explicit adoption rule")
                doc.trust = "approved"
                doc_id = key(identity.tenant, pack_id, doc.id, doc.content_hash)
                source_row = session.get(DocumentRow, doc_id)
                if source_row:
                    source_row.trust = "approved"
                    source_row.payload = doc.model_dump(mode="json")
            row.trust, row.payload = "approved", pack.model_dump(mode="json")
        self.repo.audit(identity, "pack_approved", pack_id, {"reason": reason})

    def packs(self, tenant: str, include_candidates: bool = True) -> list[tuple[str, DomainPack]]:
        with self.repo.session() as session:
            stmt = select(PackRow).where(PackRow.tenant == tenant)
            if not include_candidates:
                stmt = stmt.where(PackRow.trust.in_(["approved", "demo"]))
            return [(row.id, DomainPack.model_validate(row.payload)) for row in session.scalars(stmt)]

    def rate_candidates(self, pack_id: str, component_key: str, tenant: str) -> list[RateRecord]:
        with self.repo.session() as session:
            rows = session.scalars(
                select(RateRow)
                .join(PackRow)
                .where(
                    RateRow.pack_id == pack_id,
                    RateRow.component_key == component_key,
                    PackRow.tenant == tenant,
                )
            )
            return [RateRecord.model_validate(row.payload) for row in rows]

    def search(
        self,
        query: str,
        tenant: str,
        authority: str | None = None,
        as_of: date | None = None,
        approved_only: bool = False,
        limit: int = 8,
        state: str | None = None,
        discipline: str | None = None,
    ) -> dict:
        with self.repo.session() as session:
            stmt = (
                select(ChunkRow, DocumentRow)
                .join(DocumentRow)
                .where(DocumentRow.tenant == tenant, DocumentRow.active.is_(True))
            )
            if authority:
                stmt = stmt.where(DocumentRow.authority.in_([authority, "unknown"]))
            if approved_only:
                stmt = stmt.where(DocumentRow.trust == "approved")
            rows = session.execute(stmt).all()
        # Filter applicability BEFORE ranking so inaccessible or expired evidence cannot crowd out matches.
        rows = [
            (c, d)
            for c, d in rows
            if not as_of
            or in_period(
                date.fromisoformat(d.payload["effective_from"]),
                date.fromisoformat(d.payload["effective_to"]) if d.payload.get("effective_to") else None,
                as_of,
            )
        ]
        if state:
            rows = [
                (c, d) for c, d in rows if d.payload.get("state", "").casefold() in ("", state.casefold())
            ]
        if discipline:
            rows = [
                (c, d)
                for c, d in rows
                if d.payload.get("discipline", "all").casefold() in ("all", discipline.casefold())
            ]
        if not rows:
            return {"mode": "keyword", "results": []}
        terms = set(tokens(query))
        corpus = [Counter(tokens(c.content)) for c, _ in rows]
        average = sum(sum(c.values()) for c in corpus) / len(corpus) or 1
        lexical = []
        for i, counts in enumerate(corpus):
            score = 0.0
            for term in terms:
                frequency = counts[term]
                n = sum(term in c for c in corpus)
                idf = math.log(1 + (len(corpus) - n + 0.5) / (n + 0.5))
                score += (
                    idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * sum(counts.values()) / average))
                )
            if score:
                lexical.append((i, score))
        lexical.sort(key=lambda x: x[1], reverse=True)
        ranked = {i: 1 / (60 + rank) for rank, (i, _) in enumerate(lexical, 1)}
        mode, warning = "keyword", None
        if self.embeddings_enabled:
            try:
                vector = np.array(self.embedder.embed([query], query=True)[0])
                semantic = []
                for i, (chunk, _) in enumerate(rows):
                    if chunk.embedding is None or chunk.embedding_model != self.embedding_model_id:
                        continue
                    other = np.array(chunk.embedding)
                    if other.shape != vector.shape:
                        continue
                    denom = np.linalg.norm(vector) * np.linalg.norm(other)
                    score = float(np.dot(vector, other) / denom) if denom else 0
                    if score > 0:
                        semantic.append((i, score))
                for rank, (i, _) in enumerate(sorted(semantic, key=lambda x: -x[1]), 1):
                    ranked[i] = ranked.get(i, 0) + 1 / (60 + rank)
                mode = "hybrid" if semantic else "keyword"
            except (httpx.HTTPError, ValueError, KeyError):
                warning = "Semantic retrieval unavailable; keyword results are shown."
            except Exception:
                warning = "Semantic retrieval unavailable; keyword results are shown."
        candidate_limit = max(limit, min(40, limit * 4))
        candidate_ids = [i for i, _ in sorted(ranked.items(), key=lambda x: -x[1])[:candidate_limit]]
        if self.settings.rag_enabled and self.settings.nvidia_rerank_model and candidate_ids:
            try:
                from langchain_core.documents import Document
                from langchain_nvidia_ai_endpoints import NVIDIARerank

                options = {
                    "model": self.settings.nvidia_rerank_model,
                    "api_key": self.settings.nvidia_api_key,
                }
                if self.settings.nvidia_base_url:
                    options["base_url"] = self.settings.nvidia_base_url
                candidates = [
                    Document(page_content=rows[i][0].content, metadata={"index": i}) for i in candidate_ids
                ]
                reranked = NVIDIARerank(**options).compress_documents(candidates, query)
                candidate_ids = [item.metadata["index"] for item in reranked if "index" in item.metadata]
                mode = "hybrid_reranked" if mode == "hybrid" else "keyword_reranked"
            except Exception:
                warning = "Reranking unavailable; hybrid candidates are shown."
        results = []
        for i in candidate_ids[:limit]:
            chunk, doc = rows[i]
            results.append(
                {
                    "document_id": doc.id,
                    "source_id": doc.payload["id"],
                    "url": doc.payload.get("url", ""),
                    "title": doc.payload["title"],
                    "version": doc.payload["version"],
                    "trust": doc.trust,
                    "authority": doc.authority,
                    "content": chunk.content,
                    "locator": "; ".join(
                        value
                        for value in (
                            doc.payload.get("locator", ""),
                            re.search(r"\[Page (\d+)\]", chunk.content).group(0).strip("[]")
                            if re.search(r"\[Page (\d+)\]", chunk.content)
                            else "",
                            f"chunk {chunk.position + 1}",
                        )
                        if value
                    ),
                    "snapshot_ref": doc.payload["snapshot_ref"],
                    "content_hash": doc.payload["content_hash"],
                    "score": ranked.get(i, 0),
                }
            )
        return {"mode": mode, "warning": warning, "results": results}

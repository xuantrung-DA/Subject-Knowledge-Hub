"""Scoped exact pgvector / PostgreSQL FTS retrieval with rank-based fusion.

Exact search intentionally avoids ANN post-filter recall loss in small local
collections. Every candidate SQL query includes owner, subject, active version,
embedding space and deletion constraints before ORDER BY/LIMIT.
"""

from __future__ import annotations
import hashlib
import time
from datetime import timedelta
from app.models import utcnow
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from app.config import settings
from app.errors import AppError
from app.models import Subject, Document, DocumentVersion, Chunk, EmbeddingCache, UsageEvent
from app.security import require_subject
from app.tokens import count_tokens


def active_chunks(user_id, subject_id):
    return (
        select(Chunk, Document, DocumentVersion)
        .join(DocumentVersion, Chunk.version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(Subject, Document.subject_id == Subject.id)
        .where(
            Subject.id == subject_id,
            Subject.user_id == user_id,
            Subject.deleted_at.is_(None),
            Document.deleted_at.is_(None),
            Document.active_version_id == DocumentVersion.id,
            DocumentVersion.status == "ready",
            Chunk.embedding_model == settings.openai_embedding_model,
            Chunk.config_version == settings.config_version,
            DocumentVersion.embedding_dimensions == settings.openai_embedding_dimensions,
        )
    )


def evidence_item(chunk, doc, version, score=0.0):
    return dict(
        id=chunk.id,
        chunk_id=chunk.id,
        document_id=doc.id,
        version_id=version.id,
        document_name=doc.name,
        version=version.version,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        pages=chunk.pages,
        paragraph_ids=getattr(chunk, "paragraph_ids", None),
        source_type=getattr(doc, "source_type", "pdf"),
        text=chunk.text,
        score=float(score),
    )


def rrf(dense, lexical, k=60):
    """Accept ID lists and return fused ID/score pairs. Deterministic ties."""
    scores = {}
    for ranking in (dense, lexical):
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


def query_vector(db, user_id, subject_id, query, provider, job_id=None):
    started = time.perf_counter()
    key = hashlib.sha256(("query\x00" + query).encode()).hexdigest()
    cached = db.scalar(
        select(EmbeddingCache).where(
            EmbeddingCache.user_id == user_id,
            EmbeddingCache.content_hash == key,
            EmbeddingCache.model == settings.openai_embedding_model,
            EmbeddingCache.dimensions == settings.openai_embedding_dimensions,
            EmbeddingCache.created_at >= utcnow() - timedelta(seconds=settings.query_cache_ttl),
        )
    )
    if cached:
        event = UsageEvent(
            user_id=user_id,
            subject_id=subject_id,
            job_id=job_id,
            kind="query_embedding_cache",
            model=settings.openai_embedding_model,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            retries=0,
            cache_hit=True,
        )
        db.add(event)
        db.flush()
        if "rag_usage_ids" in db.info:
            db.info["rag_usage_ids"].append(event.id)
        return cached.embedding
    if provider is None:
        from app.provider import get_provider

        provider = get_provider()
    from app.provider import OpenAIProvider

    if not isinstance(provider, OpenAIProvider) and "rag_budget" in db.info:
        db.info["rag_budget"].reserve([query], output=0, embedding=True)
    vector = provider.embed([query], user_id=user_id, subject_id=subject_id, job_id=job_id, db=db)[0]
    db.execute(
        insert(EmbeddingCache)
        .values(
            user_id=user_id,
            content_hash=key,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
            embedding=vector,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "content_hash", "model", "dimensions"],
            set_={"embedding": vector, "created_at": utcnow()},
        )
    )
    return vector


def retrieve(db, user_id, subject_id, query, mode=None, limit=None, provider=None, job_id=None, document_ids=None):
    require_subject(db, user_id, subject_id)
    if not query or not query.strip():
        return []
    if count_tokens(query) > 1200:
        raise AppError("query_too_long", "Câu tìm kiếm quá dài (tối đa 1.200 tokens).", 400)
    mode = mode or settings.retrieval_mode
    if mode not in ("dense", "lexical", "hybrid"):
        raise AppError("retrieval_mode", "Chế độ tìm kiếm không hợp lệ.", 400)
    top_k = min(max(1, limit or settings.retrieval_top_k), settings.retrieval_top_k)
    candidates = max(top_k, getattr(settings, "retrieval_candidates", 20))
    base = active_chunks(user_id, subject_id)
    if document_ids is not None:
        base = base.where(Document.id.in_(document_ids))
    # No provider request when the authenticated corpus has no current chunks.
    if db.execute(base.limit(1)).first() is None:
        return []
    dense, lexical, items = [], [], {}
    if mode in ("dense", "hybrid"):
        vector = query_vector(db, user_id, subject_id, query, provider, job_id)
        distance = Chunk.embedding.cosine_distance(vector)
        rows = db.execute(
            base.where(Chunk.embedding.is_not(None))
            .add_columns(distance.label("distance"))
            .order_by(distance, Chunk.id)
            .limit(candidates)
        ).all()
        for chunk, doc, version, dist in rows:
            dense.append(chunk.id)
            items[chunk.id] = evidence_item(chunk, doc, version, 1.0 - float(dist))
    if mode in ("lexical", "hybrid"):
        terms = func.plainto_tsquery("simple", query)
        vector = func.to_tsvector("simple", Chunk.text)
        rank = func.ts_rank_cd(vector, terms)
        rows = db.execute(
            base.where(vector.op("@@")(terms))
            .add_columns(rank.label("rank"))
            .order_by(rank.desc(), Chunk.id)
            .limit(candidates)
        ).all()
        for chunk, doc, version, score in rows:
            lexical.append(chunk.id)
            items.setdefault(chunk.id, evidence_item(chunk, doc, version, score))
    if mode == "hybrid":
        ranking = rrf(dense, lexical)
    elif mode == "dense":
        ranking = [(key, items[key]["score"]) for key in dense]
    else:
        ranking = [(key, items[key]["score"]) for key in lexical]
    result, seen, used = [], set(), 0
    for key, score in ranking:
        item = dict(items[key], score=score)
        # Content deduplication prevents copied passages consuming context twice.
        digest = hashlib.sha256(item["text"].strip().encode()).hexdigest()
        tokens = count_tokens(item["text"]) + 100  # evidence metadata overhead
        if digest in seen or used + tokens > settings.max_context_tokens:
            continue
        seen.add(digest)
        used += tokens
        result.append(item)
        if len(result) >= top_k:
            break
    return result

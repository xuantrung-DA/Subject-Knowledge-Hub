"""Durable incremental ingestion; PostgreSQL is the source of truth for progress."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
from time import perf_counter

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.chunking import chunk_pages
from app.config import settings
from app.db import SessionLocal, engine
from app.errors import AppError
from app.models import (
    Chunk,
    Document,
    DocumentPage,
    DocumentVersion,
    EmbeddingCache,
    Job,
    Subject,
    UsageEvent,
    new_id,
    utcnow,
)
from app.parser import PDFParser
from app.tokens import count_embedding_tokens

log = logging.getLogger(__name__)
TERMINAL = {"ready", "failed", "needs_ocr", "cancelled"}


def lock_key(job_id: str) -> int:
    return int.from_bytes(hashlib.sha256(("hub-job:" + job_id).encode()).digest()[:8], "big", signed=True)


@contextmanager
def job_lock(job_id: str):
    # Session advisory lock survives stage commits, and drops on process death.
    with engine.connect() as connection:
        key = lock_key(job_id)
        acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()


def _live(db, job):
    # populate_existing prevents an identity-map snapshot from hiding deletion.
    subject = db.scalar(select(Subject).where(Subject.id == job.subject_id).execution_options(populate_existing=True))
    document = db.scalar(
        select(Document).where(Document.id == job.document_id).execution_options(populate_existing=True)
    )
    if (
        not subject
        or subject.deleted_at
        or subject.user_id != job.user_id
        or not document
        or document.deleted_at
        or document.subject_id != subject.id
    ):
        raise AppError("document_deleted", "Tài liệu hoặc môn học đã bị xóa; đã hủy xử lý.")
    return subject, document


def _checkpoint(db, job, version, stage, *, checkpoint=None, progress=None):
    _live(db, job)
    job.status = version.status = stage
    job.heartbeat_at = utcnow()
    if checkpoint:
        job.checkpoint = {**(job.checkpoint or {}), **checkpoint}
    if progress:
        job.progress = {**(job.progress or {}), **progress}
    db.commit()


def _parse(db, job, version):
    if (job.checkpoint or {}).get("parse_complete"):
        return
    _checkpoint(db, job, version, "parsing")
    with PDFParser(
        version.file_path,
        max_pages=settings.max_pdf_pages,
        max_page_chars=getattr(settings, "parser_max_page_chars", 300000),
    ) as parser:
        version.page_count = parser.page_count
        start = int((job.checkpoint or {}).get("parsed_pages", 0)) + 1
        warnings = list(version.warning or [])
        for page in parser.pages(start):
            db.execute(
                insert(DocumentPage)
                .values(
                    id=new_id(),
                    version_id=version.id,
                    page_number=page.number,
                    text=page.text,
                    has_text=page.has_text,
                    created_at=utcnow(),
                )
                .on_conflict_do_update(
                    index_elements=["version_id", "page_number"], set_={"text": page.text, "has_text": page.has_text}
                )
            )
            warnings = (warnings + [w for w in page.warnings if w not in warnings])[:50]
            if page.number % max(1, settings.parse_checkpoint_pages) == 0 or page.number == parser.page_count:
                version.text_page_count = db.scalar(
                    select(func.count())
                    .select_from(DocumentPage)
                    .where(DocumentPage.version_id == version.id, DocumentPage.has_text.is_(True))
                )
                version.warning = warnings
                _checkpoint(
                    db,
                    job,
                    version,
                    "parsing",
                    checkpoint={"parsed_pages": page.number},
                    progress={
                        "pages_processed": page.number,
                        "pages_total": parser.page_count,
                        "text_pages": version.text_page_count,
                    },
                )
        # Count from durable rows, not local counters (safe on resumed parsing).
        version.text_page_count = db.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.version_id == version.id, DocumentPage.has_text.is_(True))
        )
        if not version.text_page_count:
            raise AppError("needs_ocr", "PDF không có văn bản trích xuất được. Hãy OCR trước khi tải lên.")
        skipped = version.page_count - version.text_page_count
        if skipped:
            warnings.append(f"{skipped}/{version.page_count} trang không có text đã được bỏ qua; V1 chưa hỗ trợ OCR.")
        if parser.repeated_edges:
            warnings.append(f"Đã bỏ {len(parser.repeated_edges)} dòng đầu/cuối trang lặp lại theo quy tắc bảo thủ.")
        version.warning = list(dict.fromkeys(warnings))[:50]
        _checkpoint(db, job, version, "chunking", checkpoint={"parse_complete": True})


def _page_stream(db, version_id):
    # Keyset pagination avoids committing underneath a live server-side cursor.
    cursor = 0
    while True:
        pages = db.scalars(
            select(DocumentPage)
            .where(DocumentPage.version_id == version_id, DocumentPage.page_number > cursor)
            .order_by(DocumentPage.page_number)
            .limit(20)
        ).all()
        if not pages:
            return
        for page in pages:
            cursor = page.page_number
            yield page


def _chunk(db, job, version):
    if (job.checkpoint or {}).get("chunk_complete"):
        return
    _checkpoint(db, job, version, "chunking")
    resume = int((job.checkpoint or {}).get("chunks_written", 0))
    # Pin the strategy in the durable checkpoint so a deployment/config change
    # cannot change ordinals midway through a resumed job. Legacy partial jobs
    # used cross-page chunks; completed historical versions remain readable.
    page_boundaries = (job.checkpoint or {}).get(
        "chunk_page_boundaries", False if resume else settings.chunk_page_boundaries
    )
    _checkpoint(db, job, version, "chunking", checkpoint={"chunk_page_boundaries": page_boundaries})
    total = 0
    for chunk in chunk_pages(
        _page_stream(db, version.id),
        target_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        page_boundaries=page_boundaries,
    ):
        total = chunk.ordinal + 1
        if chunk.ordinal < resume:
            continue
        db.execute(
            insert(Chunk)
            .values(
                id=new_id(),
                version_id=version.id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                token_count=chunk.token_count,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                pages=chunk.pages,
                content_hash=chunk.content_hash,
                embedding_model=version.embedding_model,
                config_version=version.config_version,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["version_id", "ordinal"])
        )
        if total % 50 == 0:
            version.chunk_count = total
            _checkpoint(
                db, job, version, "chunking", checkpoint={"chunks_written": total}, progress={"chunks_processed": total}
            )
    version.chunk_count = total
    if not total:
        raise AppError("needs_ocr", "Không tạo được nội dung để tìm kiếm; tài liệu có thể cần OCR.")
    _checkpoint(
        db,
        job,
        version,
        "embedding",
        checkpoint={"chunks_written": total, "chunk_complete": True},
        progress={"chunks_processed": total, "chunks_total": total, "chunks_embedded": 0},
    )


def reserve_embedding_budget(checkpoint: dict, tokens: int, *, retries: int, max_tokens: int, max_calls: int) -> dict:
    # Reserve before sending: a network disconnect may mean the provider charged
    # even when no response arrived. Counting the retry ceiling is conservative.
    calls = max(0, retries) + 1
    reserved_tokens = int(checkpoint.get("reserved_embedding_tokens", 0)) + tokens * calls
    reserved_calls = int(checkpoint.get("reserved_embedding_calls", 0)) + calls
    if reserved_tokens > max_tokens or reserved_calls > max_calls:
        raise AppError(
            "ingestion_budget_exceeded", "Đã đạt ngân sách embedding của job. Tăng giới hạn hoặc chia PDF rồi thử lại."
        )
    return {"reserved_embedding_tokens": reserved_tokens, "reserved_embedding_calls": reserved_calls}


def _embed(db, job, version, provider):
    while True:
        _live(db, job)
        candidates = db.scalars(
            select(Chunk)
            .where(Chunk.version_id == version.id, Chunk.embedding.is_(None))
            .order_by(Chunk.ordinal)
            .limit(settings.embedding_batch_size)
        ).all()
        if not candidates:
            break
        batch, total_tokens = [], 0
        for chunk in candidates:
            embedding_tokens = count_embedding_tokens(chunk.text)
            if embedding_tokens > min(8191, settings.embedding_batch_tokens):
                raise AppError(
                    "embedding_input_too_large", "Một đoạn vượt giới hạn token embedding. Giảm kích thước bảng/đoạn."
                )
            if batch and total_tokens + embedding_tokens > settings.embedding_batch_tokens:
                break
            batch.append(chunk)
            total_tokens += embedding_tokens
        hashes = {c.content_hash for c in batch}
        cached = db.scalars(
            select(EmbeddingCache).where(
                EmbeddingCache.user_id == job.user_id,
                EmbeddingCache.content_hash.in_(hashes),
                EmbeddingCache.model == version.embedding_model,
                EmbeddingCache.dimensions == version.embedding_dimensions,
            )
        ).all()
        cache = {c.content_hash: c.embedding for c in cached}
        missing = list({c.content_hash: c for c in batch if c.content_hash not in cache}.values())
        if missing:
            reservation = reserve_embedding_budget(
                job.checkpoint or {},
                sum(count_embedding_tokens(c.text) for c in missing),
                retries=getattr(settings, "openai_max_retries", 3),
                max_tokens=settings.max_ingestion_tokens,
                max_calls=settings.max_ingestion_calls,
            )
            _checkpoint(
                db,
                job,
                version,
                "embedding",
                checkpoint=reservation,
                progress={"embedding_token_estimate": sum(count_embedding_tokens(c.text) for c in missing)},
            )
            vectors = provider.embed(
                [c.text for c in missing], user_id=job.user_id, subject_id=job.subject_id, job_id=job.id, db=db
            )
            # Release unused retry reservations only after a confirmed response.
            actual_retries = int((getattr(provider, "last_usage", None) or {}).get("retries", 0))
            unused_calls = max(0, getattr(settings, "openai_max_retries", 3) - actual_retries)
            job.checkpoint = {
                **job.checkpoint,
                "reserved_embedding_tokens": job.checkpoint["reserved_embedding_tokens"]
                - unused_calls * sum(count_embedding_tokens(c.text) for c in missing),
                "reserved_embedding_calls": job.checkpoint["reserved_embedding_calls"] - unused_calls,
            }
            if len(vectors) != len(missing) or any(len(v) != version.embedding_dimensions for v in vectors):
                raise AppError(
                    "embedding_dimensions_mismatch", "Kích thước embedding không khớp cấu hình. Cần reindex/migration."
                )
            for chunk, vector in zip(missing, vectors):
                vector = [float(x) for x in vector]
                cache[chunk.content_hash] = vector
                db.execute(
                    insert(EmbeddingCache)
                    .values(
                        id=new_id(),
                        user_id=job.user_id,
                        content_hash=chunk.content_hash,
                        model=version.embedding_model,
                        dimensions=version.embedding_dimensions,
                        embedding=vector,
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing(index_elements=["user_id", "content_hash", "model", "dimensions"])
                )
        for chunk in batch:
            chunk.embedding = cache[chunk.content_hash]
        if cached:
            db.add(
                UsageEvent(
                    user_id=job.user_id,
                    subject_id=job.subject_id,
                    job_id=job.id,
                    kind="embedding",
                    model=version.embedding_model,
                    input_tokens=0,
                    output_tokens=0,
                    cached_tokens=0,
                    cache_hit=True,
                )
            )
        db.flush()
        done = db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.version_id == version.id, Chunk.embedding.is_not(None))
        )
        _checkpoint(
            db, job, version, "embedding", checkpoint={"embedded_chunks": done}, progress={"chunks_embedded": done}
        )


def _activate(db, job, version):
    # Lock ordering matches API mutation paths. NO KEY UPDATE serializes
    # mutable fields while remaining compatible with FK KEY SHARE locks held
    # by concurrent usage/message inserts. Recheck AFTER taking locks.
    subject = db.scalar(
        select(Subject)
        .where(Subject.id == job.subject_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    document = db.scalar(
        select(Document)
        .where(Document.id == job.document_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if not subject or subject.deleted_at or not document or document.deleted_at:
        raise AppError("document_deleted", "Tài liệu đã bị xóa; không kích hoạt phiên bản.")
    count, embedded = db.execute(
        select(func.count(Chunk.id), func.count(Chunk.embedding)).where(Chunk.version_id == version.id)
    ).one()
    if not count or count != version.chunk_count or embedded != count:
        raise AppError("incomplete_index", "Index chưa hoàn tất; chưa thể kích hoạt phiên bản.")
    # Concurrent replacements can finish out of order: never roll active backward.
    active = db.get(DocumentVersion, document.active_version_id) if document.active_version_id else None
    activated = not active or version.version >= active.version
    if activated and document.active_version_id != version.id:
        document.active_version_id = version.id
        subject.corpus_revision += 1
    job.status = version.status = "ready"
    job.error_code = version.error_code = None
    job.error_message = version.error_message = None
    job.heartbeat_at = utcnow()
    job.checkpoint = {**(job.checkpoint or {}), "complete": True}
    job.result = {
        "document_id": document.id,
        "version_id": version.id,
        "pages": version.page_count,
        "text_pages": version.text_page_count,
        "chunks": version.chunk_count,
        "activated": activated,
    }
    db.commit()


def ingest_job(job_id: str, provider=None):
    """Process/recover one durable job; injected providers are test-only callers."""
    with job_lock(job_id) as acquired:
        if not acquired:
            return {"status": "already_running"}
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job or job.kind != "ingestion" or job.status in TERMINAL:
                return {"status": job.status if job else "not_found"}
            version = db.get(DocumentVersion, job.version_id)
            if not version:
                job.status, job.error_code, job.error_message = (
                    "failed",
                    "version_missing",
                    "Không tìm thấy phiên bản PDF.",
                )
                db.commit()
                return {"status": "failed"}
            began = perf_counter()
            try:
                _live(db, job)
                job.attempts += 1
                if job.attempts > getattr(settings, "job_max_attempts", 4):
                    raise AppError("job_retry_exhausted", "Job đã vượt số lần phục hồi tự động. Hãy thử lại chủ động.")
                if (
                    version.embedding_model != settings.openai_embedding_model
                    or version.embedding_dimensions != settings.openai_embedding_dimensions
                    or version.config_version != settings.config_version
                ):
                    raise AppError(
                        "reindex_required", "Cấu hình embedding/chunk đã thay đổi. Cần reindex trong collection mới."
                    )
                job.error_code = job.error_message = version.error_code = version.error_message = None
                db.commit()
                _parse(db, job, version)
                _chunk(db, job, version)
                if provider is None:
                    from app.provider import get_provider

                    provider = get_provider()
                _embed(db, job, version, provider)
                _activate(db, job, version)
                log.info(
                    "ingestion_ready", extra={"job_id": job_id, "elapsed_seconds": round(perf_counter() - began, 3)}
                )
            except Exception as exc:
                # Preserve provider UsageEvents already flushed on API failure;
                # only rollback a failed database transaction.
                if not db.is_active:
                    db.rollback()
                    job, version = db.get(Job, job_id), db.get(DocumentVersion, version.id)
                code = getattr(exc, "code", "ingestion_failed")
                message = getattr(exc, "message", "Xử lý PDF thất bại. Kiểm tra worker log và thử lại.")
                status = "needs_ocr" if code == "needs_ocr" else "cancelled" if code == "document_deleted" else "failed"
                job.status = version.status = status
                job.error_code = version.error_code = code
                job.error_message = version.error_message = message
                job.heartbeat_at = utcnow()
                db.commit()
                log.error(
                    "ingestion_failed", extra={"job_id": job_id, "error_code": code, "error_type": type(exc).__name__}
                )
            return {"status": job.status, "job_id": job.id}

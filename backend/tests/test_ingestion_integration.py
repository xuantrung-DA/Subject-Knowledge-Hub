"""PostgreSQL-only integration gates. Run after Alembic with RUN_INTEGRATION=1.

These use the production ingestion service and explicit fake embedding injection;
no SQLite substitution and no paid OpenAI calls.
"""

import hashlib
import os
from uuid import uuid4
import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import delete, func, select
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Chunk,
    Document,
    DocumentPage,
    DocumentVersion,
    EmbeddingCache,
    Job,
    Subject,
    UsageEvent,
    User,
    utcnow,
)
from app.ingestion import ingest_job, job_lock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RUN_INTEGRATION") != "1", reason="Real PostgreSQL integration opt-in required"),
]


class FakeProvider:
    def __init__(self, hook=None):
        self.calls = 0
        self.hook = hook
        self.last_usage = None

    def embed(self, texts, **kwargs):
        self.calls += 1
        if self.hook:
            self.hook()
        return [[1.0] + [0.0] * (settings.openai_embedding_dimensions - 1) for _ in texts]


@pytest.fixture
def owner():
    with SessionLocal() as db:
        user = User(email=f"ingestion-{uuid4()}@example.invalid", password_hash="test-only")
        db.add(user)
        db.flush()
        subject = Subject(user_id=user.id, name="Ingestion regression")
        db.add(subject)
        db.commit()
        ids = (user.id, subject.id)
    yield ids
    with SessionLocal() as db:
        user_id, subject_id = ids
        db.execute(delete(UsageEvent).where(UsageEvent.user_id == user_id))
        db.execute(delete(EmbeddingCache).where(EmbeddingCache.user_id == user_id))
        db.execute(delete(Job).where(Job.user_id == user_id))
        db.execute(delete(Document).where(Document.subject_id == subject_id))
        db.execute(delete(Subject).where(Subject.id == subject_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def make_pdf(path, content="The solar calibration constant is seventeen.", pages=3):
    c = canvas.Canvas(str(path))
    for number in range(pages):
        c.drawString(40, 760, f"{content} Physical page {number + 1}." if content else "")
        c.showPage()
    c.save()
    return path


def make_job(owner, path, *, document_id=None):
    user_id, subject_id = owner
    with SessionLocal() as db:
        if document_id is None:
            document = Document(subject_id=subject_id, name=path.name)
            db.add(document)
            db.flush()
            document_id = document.id
        previous = (
            db.scalar(select(func.max(DocumentVersion.version)).where(DocumentVersion.document_id == document_id)) or 0
        )
        version = DocumentVersion(
            document_id=document_id,
            version=previous + 1,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_path=str(path),
            size_bytes=path.stat().st_size,
        )
        db.add(version)
        db.flush()
        job = Job(
            user_id=user_id,
            subject_id=subject_id,
            document_id=document_id,
            version_id=version.id,
            kind="ingestion",
            status="queued",
        )
        db.add(job)
        db.commit()
        return document_id, version.id, job.id


def test_ready_redelivery_and_content_cache(owner, tmp_path):
    path = make_pdf(tmp_path / "course.pdf")
    did, vid, jid = make_job(owner, path)
    provider = FakeProvider()
    assert ingest_job(jid, provider)["status"] == "ready"
    calls = provider.calls
    assert calls > 0
    assert ingest_job(jid, provider)["status"] == "ready"
    assert provider.calls == calls
    with SessionLocal() as db:
        version = db.get(DocumentVersion, vid)
        assert db.get(Document, did).active_version_id == vid
        assert version.page_count == version.text_page_count == 3
        assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.version_id == vid)) == 3
        assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == vid)) == version.chunk_count
        assert db.get(Subject, owner[1]).corpus_revision == 1
    # Independently inserted test version bypasses upload dedup to test scoped
    # embedding reuse; upload duplicate locking is covered in API integration.
    _, _, next_job = make_job(owner, path)
    assert ingest_job(next_job, provider)["status"] == "ready"
    assert provider.calls == calls


def test_replacement_failure_preserves_active_then_success_switches(owner, tmp_path):
    did, original, jid = make_job(owner, make_pdf(tmp_path / "original.pdf"))
    assert ingest_job(jid, FakeProvider())["status"] == "ready"
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7\ninvalid")
    _, _, failed = make_job(owner, bad, document_id=did)
    assert ingest_job(failed, FakeProvider())["status"] == "failed"
    with SessionLocal() as db:
        assert db.get(Document, did).active_version_id == original
        assert db.get(Subject, owner[1]).corpus_revision == 1
    _, newer, good = make_job(
        owner, make_pdf(tmp_path / "new.pdf", "The new solar constant is forty-three."), document_id=did
    )
    assert ingest_job(good, FakeProvider())["status"] == "ready"
    with SessionLocal() as db:
        assert db.get(Document, did).active_version_id == newer
        assert db.get(Subject, owner[1]).corpus_revision == 2


def test_out_of_order_replacement_cannot_activate_older_version(owner, tmp_path):
    did, old, first = make_job(owner, make_pdf(tmp_path / "old.pdf", "Older fact."))
    _, new, second = make_job(owner, make_pdf(tmp_path / "new.pdf", "Newer fact."), document_id=did)
    assert ingest_job(second, FakeProvider())["status"] == "ready"
    assert ingest_job(first, FakeProvider())["status"] == "ready"
    with SessionLocal() as db:
        assert db.get(Document, did).active_version_id == new
        assert db.get(Job, first).result["activated"] is False


def test_worker_crash_after_chunk_checkpoint_resumes_without_duplicate(owner, tmp_path):
    _, vid, jid = make_job(owner, make_pdf(tmp_path / "resume.pdf", pages=13))

    def crash():
        raise KeyboardInterrupt("simulated process death after durable reservation")

    with pytest.raises(KeyboardInterrupt):
        ingest_job(jid, FakeProvider(hook=crash))
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "embedding"
        assert job.checkpoint["parse_complete"] and job.checkpoint["chunk_complete"]
        before = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == vid))
    assert ingest_job(jid, FakeProvider())["status"] == "ready"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.version_id == vid)) == 13
        assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == vid)) == before
        assert db.get(Job, jid).attempts == 2


def test_chunk_strategy_stays_pinned_across_config_change(owner, tmp_path, monkeypatch):
    from app import ingestion

    monkeypatch.setattr(settings, "chunk_page_boundaries", True)
    _, vid, jid = make_job(owner, make_pdf(tmp_path / "pinned.pdf", pages=60))
    real_checkpoint = ingestion._checkpoint

    def crash_after_commit(*args, **kwargs):
        real_checkpoint(*args, **kwargs)
        if kwargs.get("checkpoint", {}).get("chunks_written") == 50:
            raise KeyboardInterrupt("Crash after 50 durable chunks")

    monkeypatch.setattr(ingestion, "_checkpoint", crash_after_commit)
    with pytest.raises(KeyboardInterrupt):
        ingest_job(jid, FakeProvider())
    monkeypatch.setattr(ingestion, "_checkpoint", real_checkpoint)
    monkeypatch.setattr(settings, "chunk_page_boundaries", False)
    assert ingest_job(jid, FakeProvider())["status"] == "ready"
    with SessionLocal() as db:
        chunks = db.scalars(select(Chunk).where(Chunk.version_id == vid).order_by(Chunk.ordinal)).all()
        assert len(chunks) == 60
        assert [c.pages for c in chunks] == [[n] for n in range(1, 61)]
        assert db.get(Job, jid).checkpoint["chunk_page_boundaries"] is True


def test_delete_during_embedding_never_activates(owner, tmp_path):
    did, vid, jid = make_job(owner, make_pdf(tmp_path / "deleted.pdf"))

    def delete_document():
        with SessionLocal() as db:
            subject = db.scalar(select(Subject).where(Subject.id == owner[1]).with_for_update())
            document = db.scalar(select(Document).where(Document.id == did).with_for_update())
            document.deleted_at = utcnow()
            subject.corpus_revision += 1
            db.commit()

    assert ingest_job(jid, FakeProvider(hook=delete_document))["status"] == "cancelled"
    with SessionLocal() as db:
        assert db.get(Document, did).active_version_id is None
        assert db.get(DocumentVersion, vid).status == "cancelled"


def test_advisory_lock_rejects_duplicate_worker(owner, tmp_path):
    _, _, jid = make_job(owner, make_pdf(tmp_path / "lock.pdf"))
    provider = FakeProvider()
    with job_lock(jid) as acquired:
        assert acquired
        assert ingest_job(jid, provider)["status"] == "already_running"
    assert provider.calls == 0
    assert ingest_job(jid, provider)["status"] == "ready"


def test_scanned_pdf_is_needs_ocr(owner, tmp_path):
    _, vid, jid = make_job(owner, make_pdf(tmp_path / "scan.pdf", content=""))
    provider = FakeProvider()
    assert ingest_job(jid, provider)["status"] == "needs_ocr"
    assert provider.calls == 0
    with SessionLocal() as db:
        assert db.get(DocumentVersion, vid).text_page_count == 0


def test_queue_failure_after_commit_recovers(owner, tmp_path, monkeypatch):
    from app import worker

    _, _, jid = make_job(owner, make_pdf(tmp_path / "queue.pdf"))

    def fail(*_, **__):
        raise ConnectionError("simulated unavailable Redis")

    monkeypatch.setattr(worker.process_job, "apply_async", fail)
    assert worker.dispatch_job(jid) is False
    with SessionLocal() as db:
        assert db.get(Job, jid).status == "queued"
        assert db.get(Job, jid).enqueued_at is None
    published = []
    monkeypatch.setattr(worker, "dispatch_job", lambda job_id: published.append(job_id) or True)
    worker.reconcile_jobs()
    assert jid in published

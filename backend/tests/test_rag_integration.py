"""Real PostgreSQL/pgvector service regressions; injected provider is offline only."""

import hashlib
import json
import os
from uuid import uuid4
import pytest
from sqlalchemy import select, text
from app.config import settings
from app.db import SessionLocal, engine
from app.errors import AppError
from app.models import User, Subject, Document, DocumentVersion, DocumentPage, Chunk, Job, Message, Conversation, utcnow
from app.rag import answer, execute_tool, create_summary_job, run_summary_job, _history
from app.retrieval import retrieve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="Requires migrated real PostgreSQL+pgvector; no SQLite fallback"
    ),
]


class FakeResponse:
    def __init__(self, content="The calibration code is COBALT [1].", output=None):
        self.output_text = content
        self.output = output or []


class FakeProvider:
    def __init__(self, hook=None):
        self.calls = 0
        self.hook = hook
        self.inputs = []

    def embed(self, texts, **kwargs):
        return [[1.0] + [0.0] * (settings.openai_embedding_dimensions - 1) for _ in texts]

    def respond(self, inputs, **kwargs):
        self.calls += 1
        self.inputs.append(inputs)
        if self.hook:
            self.hook(self.calls)
        return FakeResponse()


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.setattr("app.rag._cache_get", lambda key: None)
    monkeypatch.setattr("app.rag._cache_set", lambda key, value: None)
    monkeypatch.setattr("app.api.publish_after_commit", lambda job_id: None)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
    with SessionLocal() as db:
        user = User(email=f"rag-{uuid4()}@example.invalid", password_hash="test-only")
        db.add(user)
        db.flush()
        subjects = [Subject(user_id=user.id, name=name) for name in ("A", "B")]
        db.add_all(subjects)
        db.flush()
        docs = []
        versions = []
        for subject in subjects:
            doc = Document(subject_id=subject.id, name=f"{subject.name}.pdf")
            db.add(doc)
            db.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version=1,
                sha256=hashlib.sha256(subject.id.encode()).hexdigest(),
                file_path="/test-only.pdf",
                size_bytes=100,
                status="ready",
                page_count=3,
                text_page_count=3,
                chunk_count=3,
                embedding_model=settings.openai_embedding_model,
                embedding_dimensions=settings.openai_embedding_dimensions,
                config_version=settings.config_version,
            )
            db.add(version)
            db.flush()
            doc.active_version_id = version.id
            for page in range(1, 4):
                content = f"The calibration code is COBALT in subject {subject.name}, physical PDF page {page}. "
                db.add(DocumentPage(version_id=version.id, page_number=page, text=content, has_text=True))
                db.add(
                    Chunk(
                        version_id=version.id,
                        ordinal=page,
                        text=content,
                        token_count=25,
                        page_start=page,
                        page_end=page,
                        pages=[page],
                        content_hash=hashlib.sha256(content.encode()).hexdigest(),
                        embedding=[1.0] + [0.0] * (settings.openai_embedding_dimensions - 1),
                        embedding_model=settings.openai_embedding_model,
                        config_version=settings.config_version,
                    )
                )
            docs.append(doc.id)
            versions.append(version.id)
        other = User(email=f"rag-other-{uuid4()}@example.invalid", password_hash="test-only")
        db.add(other)
        db.commit()
        return {
            "user": user.id,
            "other": other.id,
            "subjects": [x.id for x in subjects],
            "docs": docs,
            "versions": versions,
        }


def test_all_retrieval_modes_filter_scope_and_inactive_versions(corpus):
    c = corpus
    with SessionLocal() as db:
        for mode in ("dense", "lexical", "hybrid"):
            evidence = retrieve(db, c["user"], c["subjects"][0], "COBALT", mode=mode, provider=FakeProvider())
            assert evidence and all(e["document_id"] == c["docs"][0] for e in evidence)
        with pytest.raises(AppError):
            retrieve(db, c["other"], c["subjects"][0], "COBALT", mode="lexical")
        db.get(Document, c["docs"][0]).deleted_at = utcnow()
        db.get(Subject, c["subjects"][0]).corpus_revision += 1
        db.commit()
        assert retrieve(db, c["user"], c["subjects"][0], "COBALT", mode="lexical") == []


def test_direct_answer_citations_and_old_history_invalidation(corpus):
    c = corpus
    with SessionLocal() as db:
        result = answer(
            db,
            c["user"],
            c["subjects"][0],
            "COBALT",
            retrieval_mode="lexical",
            provider=FakeProvider(),
            disable_cache=True,
        )
        assert result["citations"][0]["document_id"] == c["docs"][0]
        assert result["citations"][0]["pdf_url"].endswith("#page=" + str(result["citations"][0]["page_start"]))
        subject = db.get(Subject, c["subjects"][0])
        subject.corpus_revision += 1
        db.commit()
        assert _history(db, result["conversation_id"], subject.corpus_revision) == []
        with pytest.raises(AppError) as exc:
            answer(
                db,
                c["user"],
                c["subjects"][1],
                "COBALT",
                conversation_id=result["conversation_id"],
                retrieval_mode="lexical",
                provider=FakeProvider(),
            )
        assert exc.value.code == "conversation_not_found"


def test_revision_change_during_model_call_rejects_new_answer(corpus):
    c = corpus

    def change(_):
        with SessionLocal() as db:
            db.get(Document, c["docs"][0]).deleted_at = utcnow()
            db.get(Subject, c["subjects"][0]).corpus_revision += 1
            db.commit()

    with SessionLocal() as db:
        with pytest.raises(AppError) as exc:
            answer(
                db,
                c["user"],
                c["subjects"][0],
                "COBALT",
                retrieval_mode="lexical",
                provider=FakeProvider(change),
                disable_cache=True,
            )
        assert exc.value.code == "corpus_changed"
        assert not db.scalars(
            select(Message)
            .join(Conversation)
            .where(Conversation.subject_id == c["subjects"][0], Message.role == "assistant")
        ).all()


def test_tool_backend_scope_ranges_and_explicit_summary_confirmation(corpus):
    c = corpus
    with SessionLocal() as db:
        registry = {}
        provider = FakeProvider()
        _, listed = execute_tool(db, c["user"], c["subjects"][0], "list_documents", "{}", registry, provider)
        assert [x["document_id"] for x in listed["documents"]] == [c["docs"][0]]
        args = json.dumps({"document_id": c["docs"][0], "page_start": 2, "page_end": 2})
        _, read = execute_tool(db, c["user"], c["subjects"][0], "read_document_pages", args, registry, provider)
        assert read["evidence"][0]["page_start"] == 2
        stolen = json.dumps({"document_id": c["docs"][1], "page_start": 1, "page_end": 1})
        with pytest.raises(AppError):
            execute_tool(db, c["user"], c["subjects"][0], "read_document_pages", stolen, registry, provider)
        with pytest.raises(AppError):
            execute_tool(db, c["user"], c["subjects"][0], "shell", "{}", registry, provider)
        summary_args = json.dumps({"document_id": c["docs"][0], "page_start": None, "page_end": None})
        _, estimate = execute_tool(
            db, c["user"], c["subjects"][0], "summarize_document", summary_args, registry, provider
        )
        assert estimate["requires_confirmation"] and not estimate.get("job_id")
        assert provider.calls == 0
        created = create_summary_job(db, c["user"], c["subjects"][0], c["docs"][0], confirmed=True)
        _, status = execute_tool(
            db,
            c["user"],
            c["subjects"][0],
            "get_job_status",
            json.dumps({"job_id": created["job_id"]}),
            registry,
            provider,
        )
        assert status["status"] == "queued"
        with pytest.raises(AppError):
            execute_tool(
                db,
                c["user"],
                c["subjects"][1],
                "get_job_status",
                json.dumps({"job_id": created["job_id"]}),
                registry,
                provider,
            )


def test_summary_reads_full_range_and_reuses_version_cache(corpus, monkeypatch):
    c = corpus
    monkeypatch.setattr(settings, "summary_batch_tokens", 450)
    with SessionLocal() as db:
        for page in db.scalars(select(DocumentPage).where(DocumentPage.version_id == c["versions"][0])):
            page.text = page.text * 40
        db.commit()
        created = create_summary_job(db, c["user"], c["subjects"][0], c["docs"][0], confirmed=True)
    provider = FakeProvider()
    run_summary_job(created["job_id"], provider=provider)
    with SessionLocal() as db:
        job = db.get(Job, created["job_id"])
        assert job.status == "ready", job.error_message
        assert job.result["pages_read"] == [1, 2, 3]
        assert job.result["reserved_calls"] == provider.calls > 0
        cached = create_summary_job(db, c["user"], c["subjects"][0], c["docs"][0], confirmed=True)
        assert cached["cached"] and cached["status"] == "ready"


def test_summary_restart_preserves_call_reservations_and_checkpoint(corpus, monkeypatch):
    c = corpus
    monkeypatch.setattr(settings, "summary_batch_tokens", 450)
    with SessionLocal() as db:
        for page in db.scalars(select(DocumentPage).where(DocumentPage.version_id == c["versions"][0])):
            page.text = page.text * 40
        db.commit()
        created = create_summary_job(db, c["user"], c["subjects"][0], c["docs"][0], confirmed=True)

    def crash(call):
        if call == 2:
            raise SystemExit("simulated worker process death during provider call")

    interrupted = FakeProvider(crash)
    with pytest.raises(SystemExit):
        run_summary_job(created["job_id"], provider=interrupted)
    with SessionLocal() as db:
        job = db.get(Job, created["job_id"])
        assert len(job.checkpoint["parts"]) == 1
        assert job.checkpoint["reserved_calls"] == 2
        assert job.status == "running"
    resumed = FakeProvider()
    run_summary_job(created["job_id"], provider=resumed)
    with SessionLocal() as db:
        job = db.get(Job, created["job_id"])
        assert job.status == "ready", job.error_message
        assert job.result["reserved_calls"] == 2 + resumed.calls
        assert job.result["pages_read"] == [1, 2, 3]
        assert job.attempts == 2


def test_assistant_executes_function_output_roundtrip(corpus):
    c = corpus

    class Call:
        type = "function_call"
        name = "read_document_pages"
        call_id = "call_read"
        id = "fc_read"
        status = "completed"
        arguments = json.dumps({"document_id": c["docs"][0], "page_start": 2, "page_end": 2})

        def model_dump(self, **kwargs):
            return {key: getattr(self, key) for key in ("type", "name", "call_id", "id", "status", "arguments")}

    class ToolProvider(FakeProvider):
        def respond(self, inputs, **kwargs):
            self.calls += 1
            self.inputs.append(inputs)
            if self.calls == 1:
                assert any(tool["name"] == "read_document_pages" for tool in kwargs["tools"])
                return FakeResponse("", [Call()])
            outputs = [x for x in inputs if x.get("type") == "function_call_output"]
            assert outputs[0]["call_id"] == "call_read"
            payload = json.loads(outputs[0]["output"])
            assert payload["evidence"][0]["page_start"] == 2
            return FakeResponse()

    provider = ToolProvider()
    with SessionLocal() as db:
        result = answer(
            db,
            c["user"],
            c["subjects"][0],
            "Read physical page 2",
            mode="assistant",
            provider=provider,
            disable_cache=True,
        )
        assert provider.calls == 2
        assert result["citations"][0]["page_start"] == 2
        assert result["debug"]["tool_runs"][0]["name"] == "read_document_pages"
        assert result["debug"]["tool_runs"][0]["status"] == "success"

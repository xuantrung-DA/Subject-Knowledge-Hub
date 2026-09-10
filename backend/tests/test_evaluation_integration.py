"""Real PostgreSQL evaluation jobs; explicit opt-in, never an SQLite substitute."""

import json
import os
from uuid import uuid4
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func, text
from app.db import SessionLocal, engine
from app.models import (
    User,
    Subject,
    Document,
    DocumentVersion,
    DocumentPage,
    Chunk,
    EvaluationRun,
    EvaluationResult,
    Job,
)
from app.config import settings
from app.evaluation import run_evaluation_job, validate_mapping
from app.evaluation_api import create_run, enqueue_run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="Needs migrated PostgreSQL/pgvector; no SQLite fallback"
    ),
]


@pytest.fixture
def collection(monkeypatch):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
    monkeypatch.setattr("app.worker.dispatch_job", lambda job_id: None)
    with SessionLocal() as db:
        user = User(email=f"eval-{uuid4().hex}@example.com", password_hash="not-an-auth-test")
        db.add(user)
        db.flush()
        subject = Subject(user_id=user.id, name="Evaluation isolation")
        db.add(subject)
        db.flush()
        document = Document(subject_id=subject.id, name="fixture.pdf", document_key="fixture")
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=uuid4().hex * 2,
            file_path="/unused-test.pdf",
            size_bytes=100,
            status="ready",
            page_count=1,
            text_page_count=1,
            chunk_count=1,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            config_version=settings.config_version,
        )
        db.add(version)
        db.flush()
        document.active_version_id = version.id
        db.add(DocumentPage(version_id=version.id, page_number=1, text="Calibration secret is COBALT.", has_text=True))
        db.add(
            Chunk(
                version_id=version.id,
                ordinal=0,
                text="Calibration secret is COBALT.",
                token_count=8,
                page_start=1,
                page_end=1,
                pages=[1],
                content_hash=uuid4().hex * 2,
                embedding=[1.0] + [0.0] * (settings.openai_embedding_dimensions - 1),
                embedding_model=settings.openai_embedding_model,
                config_version=settings.config_version,
            )
        )
        db.commit()
        yield db, user, subject, document


def dataset(reference="COBALT"):
    return (
        json.dumps(
            {
                "id": "one",
                "question": "Calibration",
                "reference_answer": reference,
                "answerable": True,
                "evidence": [
                    {
                        "document_key": "fixture",
                        "page_start": 1,
                        "page_end": 1,
                        "quote": "Calibration secret is COBALT.",
                    }
                ],
                "tags": ["en"],
            }
        )
        + "\n"
    ).encode()


def test_lexical_no_key_durable_results_replay_export_and_scope(collection, monkeypatch):
    db, user, subject, document = collection

    def forbidden():
        raise AssertionError("Lexical retrieval-only must not construct a provider")

    monkeypatch.setattr("app.provider.get_provider", forbidden)
    run = create_run(db, user.id, subject.id, dataset(), {}, {"modes": ["lexical"], "limit": 1}, "Lexical offline")
    enqueue_run(db, run)
    run_evaluation_job(run.job_id)
    db.expire_all()
    run = db.get(EvaluationRun, run.id)
    assert run.status == "ready", run.report
    assert run.report["summary"]["lexical"]["evidence_recall_at_k"] == 1
    assert run.report["summary"]["lexical"]["answer_token_f1"] is None
    run_evaluation_job(run.job_id)
    assert db.scalar(select(func.count()).select_from(EvaluationResult).where(EvaluationResult.run_id == run.id)) == 1
    outsider = User(email=f"other-{uuid4().hex}@example.com", password_hash="unused")
    db.add(outsider)
    db.commit()
    with pytest.raises(Exception):
        validate_mapping(db, outsider.id, subject.id, run.dataset, run.mapping)


def test_generation_does_not_receive_reference_or_previous_budget(collection, monkeypatch):
    db, user, subject, document = collection
    provider = SimpleNamespace(call_budget="exhausted previous question", job_budget=None)
    seen = []

    def spy_answer(db_, uid, sid, question, **kwargs):
        seen.append((question, kwargs))
        assert provider.call_budget is None
        assert "GOLDEN_NOT_IN_CORPUS" not in json.dumps(
            {"question": question, "history": kwargs.get("conversation_id")}
        )
        return {
            "answer": "COBALT",
            "citations": [],
            "debug": {"retrieved_evidence": []},
            "conversation_id": str(uuid4()),
            "message_id": str(uuid4()),
        }

    monkeypatch.setattr("app.rag.answer", spy_answer)

    def duplicate_retrieval(*args, **kwargs):
        raise AssertionError("Answer generation owns retrieval; evaluation must not send a second embedding query")

    monkeypatch.setattr("app.retrieval.retrieve", duplicate_retrieval)
    run = create_run(
        db,
        user.id,
        subject.id,
        dataset("GOLDEN_NOT_IN_CORPUS"),
        {},
        {"modes": ["lexical"], "generate_answers": True, "limit": 1},
        "Leakage guard",
    )
    enqueue_run(db, run)
    run_evaluation_job(run.job_id, provider)
    db.expire_all()
    assert db.get(EvaluationRun, run.id).status == "ready"
    assert len(seen) == 1
    assert (
        db.scalar(select(Chunk.text).where(Chunk.version_id == document.active_version_id))
        == "Calibration secret is COBALT."
    )


def test_corpus_revision_change_fails_run_without_stale_evidence(collection):
    db, user, subject, document = collection
    run = create_run(db, user.id, subject.id, dataset(), {}, {"modes": ["lexical"], "limit": 1}, "Stale corpus")
    enqueue_run(db, run)
    subject.corpus_revision += 1
    db.commit()
    run_evaluation_job(run.job_id)
    db.expire_all()
    assert db.get(EvaluationRun, run.id).status == "failed"
    assert db.get(Job, run.job_id).error_code == "evaluation_corpus_changed"
    assert not db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)).all()


def test_import_defaults_to_server_retrieval_limit(collection, monkeypatch):
    from app.errors import AppError

    db, user, subject, document = collection
    monkeypatch.setattr(settings, "retrieval_top_k", 2)
    run = create_run(db, user.id, subject.id, dataset(), {}, {"modes": ["lexical"]}, "Custom limit")
    assert run.config["top_k"] == 2
    with pytest.raises(AppError, match="top_k exceeds"):
        create_run(db, user.id, subject.id, dataset(), {}, {"top_k": 3}, "Too broad")

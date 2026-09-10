"""Requires migrated real PostgreSQL/pgvector. RUN_INTEGRATION=1 fails if absent."""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from app.config import settings
from app.api import publish_after_commit as real_publish_after_commit
from app.db import SessionLocal, engine
from app.main import app
from app.models import Document, DocumentVersion, Job, Subject

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="Set RUN_INTEGRATION=1 with migrated PostgreSQL/pgvector; no SQLite fallback",
    ),
]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
        conn.execute(select(Subject.id).limit(1))
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr("app.api.check_rate", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.security.check_rate", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.publish_after_commit", lambda job_id: None)

    def make_user():
        client = TestClient(app)
        response = client.post(
            "/api/auth/register", json={"email": f"{uuid4().hex}@example.com", "password": "test-password-123"}
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    return make_user


def make_pdf(text_value="A deterministic fact: launch code is COBALT."):
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text_value)
    pdf.save()
    return buf.getvalue()


def subject(client, name):
    response = client.post("/api/subjects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, sid, pdf=None):
    response = client.post(
        f"/api/subjects/{sid}/documents", files={"file": ("source.pdf", pdf or make_pdf(), "application/pdf")}
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_auth_csrf_and_every_child_ownership(setup):
    owner, other = setup(), setup()
    sid, other_sid = subject(owner, "A"), subject(other, "B")
    data = upload(owner, sid)
    conversation = owner.post(f"/api/subjects/{sid}/conversations", json={"title": "Private"}).json()
    did, jid = data["document_id"], data["job_id"]
    urls = [
        f"/api/subjects/{sid}/documents",
        f"/api/subjects/{sid}/documents/{did}/pdf",
        f"/api/subjects/{sid}/jobs/{jid}",
        f"/api/subjects/{sid}/conversations/{conversation['id']}/messages",
    ]
    for url in urls:
        assert other.get(url).status_code == 404
    # Child ID under a subject the second user DOES own must still be denied.
    assert other.get(f"/api/subjects/{other_sid}/documents/{did}/pdf").status_code == 404
    assert other.get(f"/api/subjects/{other_sid}/jobs/{jid}").status_code == 404
    assert other.get(f"/api/subjects/{other_sid}/conversations/{conversation['id']}/messages").status_code == 404
    token = owner.headers.pop("X-CSRF-Token")
    assert owner.post("/api/subjects", json={"name": "csrf bypass"}).status_code == 403
    owner.headers["X-CSRF-Token"] = token
    assert owner.post("/api/auth/logout").status_code == 200
    assert owner.get("/api/subjects").status_code == 401


def test_parallel_duplicates_are_one_durable_version(setup):
    client = setup()
    sid = subject(client, "Dedupe")
    pdf = make_pdf()

    # Separate clients/connections model simultaneous HTTP requests.
    def send(_):
        c = TestClient(app)
        c.cookies.update(client.cookies)
        c.headers.update(client.headers)
        return upload(c, sid, pdf)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(send, [1, 2]))
    assert first["document_id"] == second["document_id"]
    assert sorted([first["duplicate"], second["duplicate"]]) == [False, True]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Document.id)).where(Document.subject_id == sid)) == 1
        assert (
            db.scalar(select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == first["document_id"]))
            == 1
        )
        assert db.scalar(select(func.count(Job.id)).where(Job.subject_id == sid)) == 1
    assert len(list(settings.storage_dir.glob("*.pdf"))) == 1


def test_summary_history_tracks_source_lifecycle_and_retry(setup):
    client, outsider = setup(), setup()
    sid = subject(client, "Summary history")
    uploaded = upload(client, sid)
    base = f"/api/subjects/{sid}"
    with SessionLocal() as db:
        document = db.get(Document, uploaded["document_id"])
        version = db.get(DocumentVersion, uploaded["version_id"])
        version.status = "ready"
        document.active_version_id = version.id
        ingestion = db.get(Job, uploaded["job_id"])
        ingestion.status = "ready"
        summary = Job(
            user_id=ingestion.user_id,
            subject_id=sid,
            document_id=document.id,
            version_id=version.id,
            kind="summary",
            status="failed",
            checkpoint={"page_start": 1, "page_end": 1},
            result={"summary": "Historical fact."},
        )
        db.add(summary)
        db.commit()
        jid = summary.id
    url = f"{base}/jobs/{jid}"
    active = client.get(url).json()
    assert active["source"] == {
        "document_name": "source.pdf",
        "version": 1,
        "state": "active",
        "page_start": 1,
        "page_end": 1,
    }
    retried = client.post(url + "/retry")
    assert retried.status_code == 200
    assert retried.json()["source"] == active["source"]
    assert outsider.get(url).status_code == 404
    replacement = client.post(
        f"{base}/documents/{uploaded['document_id']}/versions",
        files={"file": ("new.pdf", make_pdf("New fact."), "application/pdf")},
    ).json()
    with SessionLocal() as db:
        document = db.get(Document, uploaded["document_id"])
        document.active_version_id = replacement["version_id"]
        db.get(Job, jid).status = "failed"
        db.commit()
    replaced = client.get(url).json()
    assert replaced["source"]["state"] == "replaced"
    assert replaced["source"]["version"] == 1
    assert client.post(url + "/retry").status_code == 409
    assert client.delete(f"{base}/documents/{uploaded['document_id']}").status_code == 200
    deleted = next(j for j in client.get(base + "/jobs").json() if j["id"] == jid)
    assert deleted["source"]["state"] == "deleted"
    assert deleted["result"]["summary"] == "Historical fact."


def test_failed_publish_preserves_job_and_pdf(setup, monkeypatch):
    client = setup()
    sid = subject(client, "Durable")

    def fail(_):
        raise ConnectionError("Simulated publish failure")

    monkeypatch.setattr("app.worker.dispatch_job", fail)
    monkeypatch.setattr("app.api.publish_after_commit", real_publish_after_commit)
    result = upload(client, sid)
    job = client.get(f"/api/subjects/{sid}/jobs/{result['job_id']}").json()
    assert job["status"] == "queued"
    response = client.get(f"/api/subjects/{sid}/documents/{result['document_id']}/pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    assert response.headers["cache-control"] == "private, no-store"


def test_replacement_and_deletion_keep_transactional_state(setup):
    client = setup()
    sid = subject(client, "Versions")
    original = upload(client, sid)
    did = original["document_id"]
    with SessionLocal() as db:
        document = db.get(Document, did)
        document.active_version_id = original["version_id"]
        db.get(DocumentVersion, original["version_id"]).status = "ready"
        db.get(Job, original["job_id"]).status = "ready"
        db.commit()
    replacement = client.post(
        f"/api/subjects/{sid}/documents/{did}/versions",
        files={"file": ("replacement.pdf", make_pdf("Replacement fact is AMBER."), "application/pdf")},
    )
    assert replacement.status_code == 202
    with SessionLocal() as db:
        assert db.get(Document, did).active_version_id == original["version_id"]
        replacement_job = db.get(Job, replacement.json()["job_id"])
        replacement_job.status = "failed"
        db.commit()
    assert client.post(f"/api/subjects/{sid}/jobs/{replacement.json()['job_id']}/retry").status_code == 200
    deleted = client.delete(f"/api/subjects/{sid}/documents/{did}")
    assert deleted.status_code == 200 and deleted.json()["corpus_revision"] == 1
    assert client.get(f"/api/subjects/{sid}/documents").json() == []
    assert client.get(f"/api/subjects/{sid}/documents/{did}/pdf").status_code == 404
    with SessionLocal() as db:
        assert db.get(Job, replacement.json()["job_id"]).status == "cancelled"

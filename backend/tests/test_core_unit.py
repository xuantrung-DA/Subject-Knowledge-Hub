"""Offline checks do not substitute for PostgreSQL integration acceptance."""

import asyncio
import io
import pytest
from fastapi import Request, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_mock_engine
from app.api import store_upload
from app.config import settings
from app.errors import AppError
from app.models import Base
from app.security import hash_password, verify_password, token_hash, validate_origin


def test_password_hash_is_salted_and_verified():
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first != second
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong", first)
    assert not verify_password("correct horse battery", "invalid")
    assert not verify_password("x", "scrypt$999999999$8$1$AA==$AA==")
    assert token_hash("session") != "session"


def test_origin_rejects_cross_site():
    request = Request({"type": "http", "headers": [(b"origin", b"https://evil.example")], "method": "POST"})
    with pytest.raises(AppError) as exc:
        validate_origin(request)
    assert exc.value.status_code == 403
    validate_origin(Request({"type": "http", "headers": [(b"origin", b"http://localhost:3000")], "method": "POST"}))


def test_schema_compiles_for_postgres_with_vector_and_constraints():
    statements = []
    engine = create_mock_engine(
        "postgresql+psycopg://", lambda sql, *a, **k: statements.append(str(sql.compile(dialect=engine.dialect)))
    )
    Base.metadata.create_all(engine)
    ddl = "\n".join(statements)
    assert len(Base.metadata.tables) == 16
    assert f"VECTOR({settings.openai_embedding_dimensions})" in ddl
    assert "to_tsvector('simple'::regconfig, text)" in ddl
    assert "uq_document_version" in ddl and "uq_version_chunk" in ddl
    assert "uq_documents_subject_key" in ddl and "deleted_at IS NULL" in ddl
    assert "fk_documents_active_version" in ddl and "uq_evaluation_result" in ddl
    assert "source_type" in ddl and "paragraph_ids" in ddl


@pytest.mark.parametrize(
    "filename,content,code",
    [
        ("bad.exe", b"%PDF-1.4", "NOT_PDF"),
        ("../secret.pdf", b"%PDF-1.4", "UNSAFE_FILENAME"),
        ("bad.pdf", b"", "EMPTY_FILE"),
        ("bad.pdf", b"not a pdf", "NOT_PDF"),
        ("bad\nname.pdf", b"%PDF-1.4", "UNSAFE_FILENAME"),
    ],
)
def test_upload_validation_cleans_files(tmp_path, monkeypatch, filename, content, code):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    with pytest.raises(AppError) as exc:
        asyncio.run(store_upload(UploadFile(io.BytesIO(content), filename=filename)))
    assert exc.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_upload_streams_bounded_reads_and_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    class RecordingFile(io.BytesIO):
        read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    stream = RecordingFile(b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))
    name, version_id, path, digest, size = asyncio.run(store_upload(UploadFile(stream, filename="safe.pdf")))
    assert path.name == version_id + ".pdf" and path.parent == tmp_path
    assert size == path.stat().st_size and len(digest) == 64
    assert stream.read_sizes and set(stream.read_sizes) == {1024 * 1024}


def test_upload_size_failure_cleans_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    with pytest.raises(AppError) as exc:
        asyncio.run(store_upload(UploadFile(io.BytesIO(b"%PDF-1.4" + b"x" * 1048576), filename="large.pdf")))
    assert exc.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_public_config_liveness_and_unauthenticated_error(monkeypatch):
    from app.main import app

    client = TestClient(app)  # No lifespan/reconciler and no database substitution.
    config = client.get("/api/config")
    assert config.status_code == 200 and "openai_api_key" not in config.json()
    assert config.json()["max_question_tokens"] > 0
    assert client.get("/api/health/live").json() == {"status": "live"}
    response = client.get("/api/subjects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    oversized = client.post(
        "/api/auth/login", headers={"Content-Length": str((settings.max_upload_mb + 2) * 1048576)}, content=b"{}"
    )
    assert oversized.status_code == 413


def test_rate_limit_is_finite_with_redis_unavailable(monkeypatch):
    import redis
    from app.security import check_rate

    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(redis.Redis, "from_url", unavailable)
    key = "test-unique-rate-limit"
    check_rate(key, 2)
    check_rate(key, 2)
    with pytest.raises(AppError) as exc:
        check_rate(key, 2)
    assert exc.value.code == "RATE_LIMIT"


def test_chunked_multipart_413_closes_spooled_files(monkeypatch):
    import httpx
    import starlette.formparsers
    from app.main import app

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    opened = []
    original_factory = starlette.formparsers.SpooledTemporaryFile

    def recording_factory(*args, **kwargs):
        result = original_factory(*args, **kwargs)
        opened.append(result)
        return result

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", recording_factory)

    async def run():
        async def parts():
            yield b'--BOUND\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n'
            for _ in range(20):
                yield b"x" * (128 * 1024)
            yield b"\r\n--BOUND--\r\n"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/api/subjects/fake/documents",
                headers={"Content-Type": "multipart/form-data; boundary=BOUND"},
                content=parts(),
            )

    response = asyncio.run(run())
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert opened and all(file.closed for file in opened)


def test_mutation_lock_is_compatible_with_foreign_key_reads():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from app.models import Subject

    sql = str(select(Subject).with_for_update(key_share=True).compile(dialect=postgresql.dialect()))
    assert sql.endswith("FOR NO KEY UPDATE")


def test_api_docs_work_through_same_origin_proxy():
    from app.main import app

    client = TestClient(app)
    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert "/api/openapi.json" in docs.text
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert "/api/subjects" in schema.json()["paths"]
    alias = client.get("/docs", follow_redirects=False)
    assert alias.status_code == 307
    assert alias.headers["location"] == "/api/docs"

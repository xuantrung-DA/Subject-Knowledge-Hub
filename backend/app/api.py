import hashlib
import logging
import os
import re
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .errors import AppError
from .models import Conversation, Document, DocumentVersion, Job, Message, Subject, UsageEvent, User, new_id, utcnow
from .security import (
    check_rate,
    current_user,
    hash_password,
    make_session,
    require_subject,
    validate_origin,
    verify_password,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
ACTIVE_JOB_STATUSES = ("queued", "parsing", "chunking", "embedding", "running")
_DUMMY_PASSWORD_HASH = hash_password("nonexistent-account-timing-pad")


def serialize(model, exclude=()):
    return {
        column.name: getattr(model, column.name) for column in model.__table__.columns if column.name not in exclude
    }


def public_job(job, document=None, version=None):
    if job is None:
        return None
    result = serialize(job)
    if job.kind == "summary":
        state = (
            "deleted"
            if document is None or document.deleted_at
            else "active"
            if document.active_version_id == job.version_id
            else "replaced"
        )
        scope = {**(job.checkpoint or {}), **(job.result or {})}
        result["source"] = {
            "document_name": document.name if document else None,
            "version": version.version if version else None,
            "state": state,
            "page_start": scope.get("page_start"),
            "page_end": scope.get("page_end"),
        }
    return result


def scoped_jobs(user_id, subject_id):
    # Fetch source metadata in one query, including historical/deleted documents.
    return (
        select(Job, Document, DocumentVersion)
        .outerjoin(Document, (Document.id == Job.document_id) & (Document.subject_id == Job.subject_id))
        .outerjoin(
            DocumentVersion, (DocumentVersion.id == Job.version_id) & (DocumentVersion.document_id == Job.document_id)
        )
        .where(Job.user_id == user_id, Job.subject_id == subject_id)
    )


def require_document(db, subject_id, document_id, lock=False):
    query = select(Document).where(
        Document.id == document_id, Document.subject_id == subject_id, Document.deleted_at.is_(None)
    )
    if lock:
        query = query.with_for_update(key_share=True)
    document = db.scalar(query)
    if not document:
        raise AppError("DOCUMENT_NOT_FOUND", "Không tìm thấy tài liệu.", 404)
    return document


def publish_after_commit(job_id: str):
    """Job is already durable. API never loses it when Redis publish fails."""
    try:
        from .worker import dispatch_job

        dispatch_job(job_id)
    except Exception as exc:
        logger.warning("job_publish_deferred", extra={"job_id": job_id, "error_type": type(exc).__name__})


def check_job_capacity(db, user_id, *, enforce=True):
    # Serializes admission across subjects for a user.
    db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    count = db.scalar(select(func.count(Job.id)).where(Job.user_id == user_id, Job.status.in_(ACTIVE_JOB_STATUSES)))
    if enforce and count >= settings.max_user_jobs:
        raise AppError("JOB_LIMIT", f"Bạn đang có {count} tác vụ. Hãy đợi một tác vụ hoàn tất.", 429)


class AuthBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Tên không được để trống")
        return value


class ConversationBody(BaseModel):
    title: str = Field(default="Cuộc trò chuyện mới", min_length=1, max_length=200)


def auth_result(response, db, user):
    token, session = make_session(db, user.id)
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"user": {"id": user.id, "email": user.email}, "csrf_token": session.csrf_token}


@router.get("/config")
def config():
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_pdf_pages": settings.max_pdf_pages,
        "openai_configured": bool(settings.openai_api_key.strip()),
        "chat_model": settings.openai_chat_model,
        "embedding_model": settings.openai_embedding_model,
        "retrieval_mode": settings.retrieval_mode,
        "retrieval_top_k": settings.retrieval_top_k,
        "page_numbering": "physical_1_based",
        "max_user_jobs": settings.max_user_jobs,
        **{
            key: getattr(settings, key)
            for key in (
                "max_question_tokens",
                "max_question_calls",
                "max_output_tokens",
                "max_ingestion_tokens",
                "max_ingestion_calls",
                "max_summary_tokens",
                "max_summary_calls",
            )
        },
    }


@router.post("/auth/register", status_code=201)
def register(body: AuthBody, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    check_rate(f"auth:{request.client.host if request.client else 'local'}", settings.auth_rate_limit_per_minute)
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError("EMAIL_EXISTS", "Email này đã được đăng ký.", 409)
    return auth_result(response, db, user)


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    check_rate(f"auth:{request.client.host if request.client else 'local'}", settings.auth_rate_limit_per_minute)
    user = db.scalar(select(User).where(User.email == str(body.email).strip().lower()))
    # Evaluate a real hash on missing accounts too to reduce account timing leakage.
    stored = user.password_hash if user else _DUMMY_PASSWORD_HASH
    verified = verify_password(body.password, stored)
    if not user or not verified:
        raise AppError("INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng.", 401)
    return auth_result(response, db, user)


@router.get("/auth/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"user": {"id": user.id, "email": user.email}, "csrf_token": request.state.session.csrf_token}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(request.state.session)
    db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/subjects")
def list_subjects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        serialize(s)
        for s in db.scalars(
            select(Subject).where(Subject.user_id == user.id, Subject.deleted_at.is_(None)).order_by(Subject.created_at)
        )
    ]


@router.post("/subjects", status_code=201)
def create_subject(body: NameBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    subject = Subject(user_id=user.id, name=body.name)
    db.add(subject)
    db.commit()
    return serialize(subject)


@router.patch("/subjects/{subject_id}")
def rename_subject(subject_id: str, body: NameBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    subject = require_subject(db, user.id, subject_id, lock=True)
    subject.name = body.name
    db.commit()
    return serialize(subject)


@router.delete("/subjects/{subject_id}")
def delete_subject(subject_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    subject = require_subject(db, user.id, subject_id, lock=True)
    subject.deleted_at = utcnow()
    subject.corpus_revision += 1
    for document in db.scalars(
        select(Document)
        .where(Document.subject_id == subject.id, Document.deleted_at.is_(None))
        .with_for_update(key_share=True)
    ):
        document.deleted_at = subject.deleted_at
    for job in db.scalars(select(Job).where(Job.subject_id == subject.id, Job.status.in_(ACTIVE_JOB_STATUSES))):
        job.status = "cancelled"
        job.error_code = "SUBJECT_DELETED"
        job.error_message = "Môn học đã bị xóa."
    db.commit()
    return {"ok": True}


@router.get("/subjects/{subject_id}/documents")
def list_documents(subject_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_subject(db, user.id, subject_id)
    result = []
    for document in db.scalars(
        select(Document)
        .where(Document.subject_id == subject_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    ):
        versions = list(
            db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version.desc())
            )
        )
        job = db.scalar(
            select(Job)
            .where(Job.document_id == document.id, Job.kind == "ingestion")
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        item = serialize(document)
        item["versions"] = [serialize(v, ("file_path",)) for v in versions]
        item["latest_version"] = item["versions"][0] if versions else None
        item["job"] = public_job(job)
        result.append(item)
    return result


async def store_upload(file: UploadFile):
    original = file.filename or "document.pdf"
    if (
        any(ord(c) < 32 or ord(c) == 127 for c in original)
        or "/" in original
        or "\\" in original
        or len(original) > 255
    ):
        raise AppError("UNSAFE_FILENAME", "Tên file không hợp lệ. Hãy đổi tên file rồi tải lại.")
    if not original.lower().endswith(".pdf"):
        raise AppError("NOT_PDF", "Chỉ hỗ trợ file PDF.")
    root = settings.storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    version_id = new_id()
    path = root / f"{version_id}.pdf"
    digest = hashlib.sha256()
    total = 0
    header = b""
    try:
        with path.open("xb") as target:
            while data := await file.read(1024 * 1024):
                total += len(data)
                if total > settings.max_upload_mb * 1024 * 1024:
                    raise AppError("UPLOAD_TOO_LARGE", f"File vượt giới hạn {settings.max_upload_mb} MB.", 413)
                if len(header) < 1024:
                    header += data[: 1024 - len(header)]
                digest.update(data)
                target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if not total:
            raise AppError("EMPTY_FILE", "File PDF rỗng.")
        if not header.lstrip().startswith(b"%PDF-"):
            raise AppError("NOT_PDF", "Nội dung file không phải PDF hợp lệ.")
        if os.name == "posix":
            directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return original, version_id, path, digest.hexdigest(), total
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


async def upload_version(subject_id, document_id, file, document_key, user, db):
    require_subject(db, user.id, subject_id)
    if document_id:
        require_document(db, subject_id, document_id)
    if document_key is not None:
        document_key = document_key.strip() or None
        if document_key and not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", document_key):
            raise AppError("DOCUMENT_KEY_INVALID", "Document key chỉ gồm chữ, số, dấu chấm, gạch ngang hoặc gạch dưới.")
    original, version_id, path, digest, size = await store_upload(file)
    committed = False
    try:
        # Release read transaction before obtaining admission + subject locks.
        db.rollback()
        check_job_capacity(db, user.id, enforce=False)
        subject = require_subject(db, user.id, subject_id, lock=True)
        existing = db.execute(
            select(DocumentVersion, Document)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(Document.subject_id == subject_id, Document.deleted_at.is_(None), DocumentVersion.sha256 == digest)
            .order_by(DocumentVersion.created_at.desc())
            .limit(1)
        ).first()
        if existing:
            version, document = existing
            job = db.scalar(
                select(Job)
                .where(Job.version_id == version.id, Job.kind == "ingestion")
                .order_by(Job.created_at.desc())
                .limit(1)
            )
            db.rollback()
            return {
                "document_id": document.id,
                "version_id": version.id,
                "job_id": job.id if job else None,
                "duplicate": True,
            }
        check_job_capacity(db, user.id)
        if document_id:
            document = require_document(db, subject_id, document_id, lock=True)
            if document.source_type != "pdf":
                raise AppError("SOURCE_TYPE", "Chỉ thay phiên bản PDF cho tài liệu PDF.")
            previous = (
                db.scalar(select(func.max(DocumentVersion.version)).where(DocumentVersion.document_id == document.id))
                or 0
            )
        else:
            if document_key and db.scalar(
                select(Document.id).where(
                    Document.subject_id == subject_id,
                    Document.document_key == document_key,
                    Document.deleted_at.is_(None),
                )
            ):
                raise AppError("DOCUMENT_KEY_EXISTS", "Document key đã tồn tại trong môn này.", 409)
            document = Document(id=new_id(), subject_id=subject.id, name=original, document_key=document_key)
            db.add(document)
            db.flush()
            previous = 0
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            version=previous + 1,
            sha256=digest,
            file_path=str(path),
            size_bytes=size,
            status="queued",
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            config_version=settings.config_version,
        )
        db.add(version)
        db.flush()
        job = Job(
            id=new_id(),
            user_id=user.id,
            subject_id=subject.id,
            document_id=document.id,
            version_id=version.id,
            kind="ingestion",
            status="queued",
        )
        db.add(job)
        db.commit()
        committed = True
        publish_after_commit(job.id)
        return {"document_id": document.id, "version_id": version.id, "job_id": job.id, "duplicate": False}
    except BaseException:
        db.rollback()
        raise
    finally:
        if not committed:
            path.unlink(missing_ok=True)


@router.post("/subjects/{subject_id}/documents", status_code=202)
async def upload_document(
    subject_id: str,
    file: UploadFile = File(...),
    document_key: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await upload_version(subject_id, None, file, document_key, user, db)


@router.post("/subjects/{subject_id}/documents/{document_id}/versions", status_code=202)
async def replace_document(
    subject_id: str,
    document_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await upload_version(subject_id, document_id, file, None, user, db)


@router.delete("/subjects/{subject_id}/documents/{document_id}")
def delete_document(
    subject_id: str, document_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    subject = require_subject(db, user.id, subject_id, lock=True)
    document = require_document(db, subject_id, document_id, lock=True)
    document.deleted_at = utcnow()
    subject.corpus_revision += 1
    for job in db.scalars(select(Job).where(Job.document_id == document.id, Job.status.in_(ACTIVE_JOB_STATUSES))):
        job.status = "cancelled"
        job.error_code = "DOCUMENT_DELETED"
        job.error_message = "Tài liệu đã bị xóa."
    db.commit()
    return {"ok": True, "corpus_revision": subject.corpus_revision}


@router.get("/subjects/{subject_id}/documents/{document_id}/pdf")
def document_pdf(
    subject_id: str,
    document_id: str,
    version_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_subject(db, user.id, subject_id)
    document = require_document(db, subject_id, document_id)
    if document.source_type != "pdf":
        raise AppError("NOT_PDF_SOURCE", "Nguồn này là đoạn văn dữ liệu, không có PDF.", 404)
    query = select(DocumentVersion).where(DocumentVersion.document_id == document.id)
    if version_id:
        query = query.where(DocumentVersion.id == version_id)
    elif document.active_version_id:
        query = query.where(DocumentVersion.id == document.active_version_id)
    version = db.scalar(query.order_by(DocumentVersion.version.desc()).limit(1))
    if version is None:
        raise AppError("VERSION_NOT_FOUND", "Không tìm thấy phiên bản PDF.", 404)
    path = Path(version.file_path).resolve()
    if not path.is_relative_to(settings.storage_dir.resolve()) or not path.is_file():
        raise AppError("PDF_MISSING", "Không tìm thấy file PDF đã lưu.", 404)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/subjects/{subject_id}/jobs")
def list_jobs(subject_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_subject(db, user.id, subject_id)
    rows = db.execute(scoped_jobs(user.id, subject_id).order_by(Job.created_at.desc()).limit(100))
    return [public_job(job, document, version) for job, document, version in rows]


@router.get("/subjects/{subject_id}/jobs/{job_id}")
def job_status(subject_id: str, job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_subject(db, user.id, subject_id)
    row = db.execute(scoped_jobs(user.id, subject_id).where(Job.id == job_id)).first()
    if row is None:
        raise AppError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
    return public_job(*row)


@router.post("/subjects/{subject_id}/jobs/{job_id}/retry")
def retry_job(subject_id: str, job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_job_capacity(db, user.id)
    require_subject(db, user.id, subject_id, lock=True)
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.subject_id == subject_id, Job.user_id == user.id)
        .with_for_update(key_share=True)
    )
    if not job:
        raise AppError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
    if job.status not in {"failed", "needs_ocr"}:
        raise AppError("JOB_NOT_RETRYABLE", "Chỉ có thể thử lại tác vụ lỗi hoặc cần OCR.", 409)
    document = None
    if job.document_id:
        document = require_document(db, subject_id, job.document_id)
        if job.kind == "summary" and document.active_version_id != job.version_id:
            raise AppError("SUMMARY_SOURCE_STALE", "Tài liệu đã có phiên bản mới. Hãy tạo bản tóm tắt mới.", 409)
    job.status = "queued"
    job.error_code = job.error_message = None
    job.attempts = 0
    job.heartbeat_at = job.enqueued_at = None
    if job.version_id and job.kind == "ingestion":
        version = db.get(DocumentVersion, job.version_id)
        version.status = "queued"
        version.error_code = version.error_message = None
    db.commit()
    publish_after_commit(job.id)
    return public_job(job, document, db.get(DocumentVersion, job.version_id) if job.version_id else None)


@router.get("/subjects/{subject_id}/conversations")
def list_conversations(subject_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_subject(db, user.id, subject_id)
    return [
        serialize(c)
        for c in db.scalars(
            select(Conversation).where(Conversation.subject_id == subject_id).order_by(Conversation.created_at.desc())
        )
    ]


@router.post("/subjects/{subject_id}/conversations", status_code=201)
def create_conversation(
    subject_id: str, body: ConversationBody, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_subject(db, user.id, subject_id)
    conversation = Conversation(subject_id=subject_id, title=body.title.strip() or "Cuộc trò chuyện mới")
    db.add(conversation)
    db.commit()
    return serialize(conversation)


def citation_state(db, subject_id, citation):
    result = dict(citation)
    document = db.scalar(
        select(Document).where(Document.id == citation.get("document_id"), Document.subject_id == subject_id)
    )
    if not document or document.deleted_at:
        result["state"] = "deleted"
    elif document.active_version_id != citation.get("version_id"):
        result["state"] = "replaced"
    else:
        result["state"] = "active"
    return result


@router.get("/subjects/{subject_id}/conversations/{conversation_id}/messages")
def list_messages(
    subject_id: str, conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_subject(db, user.id, subject_id)
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.subject_id == subject_id)
    )
    if not conversation:
        raise AppError("CONVERSATION_NOT_FOUND", "Không tìm thấy cuộc trò chuyện.", 404)
    result = []
    for message in db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
    ):
        item = serialize(message)
        item["citations"] = [citation_state(db, subject_id, c) for c in message.citations]
        result.append(item)
    return result


@router.get("/subjects/{subject_id}/usage")
def usage(
    subject_id: str, job_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_subject(db, user.id, subject_id)
    filters = [UsageEvent.user_id == user.id, UsageEvent.subject_id == subject_id]
    if job_id:
        owned_job = db.scalar(
            select(Job.id).where(Job.id == job_id, Job.subject_id == subject_id, Job.user_id == user.id)
        )
        if not owned_job:
            raise AppError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
        filters.append(UsageEvent.job_id == job_id)
    totals = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cached_tokens), 0),
            func.sum(UsageEvent.estimated_cost_usd),
            func.count(UsageEvent.estimated_cost_usd),
            func.count(UsageEvent.id).filter(UsageEvent.cache_hit.is_(False)),
        ).where(*filters)
    ).one()
    return {
        "totals": {
            "events_count": totals[0],
            "calls": totals[6],
            "input_tokens": totals[1],
            "output_tokens": totals[2],
            "cached_tokens": totals[3],
            "estimated_cost_usd": totals[4] if totals[5] == totals[0] else None,
        },
        "events": [
            serialize(e)
            for e in db.scalars(select(UsageEvent).where(*filters).order_by(UsageEvent.created_at.desc()).limit(100))
        ],
        "pricing_updated_at": settings.pricing_updated_at or None,
    }

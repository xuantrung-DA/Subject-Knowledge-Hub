"""Authenticated, durable dataset import, evaluation and export endpoints."""

import json
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db import get_db
from app.errors import AppError
from app.models import EvaluationRun, EvaluationResult, Job, User
from app.security import current_user, require_subject
from app.evaluation import EvaluationConfig, parse_dataset, validate_mapping, export_report

router = APIRouter(prefix="/api/subjects/{subject_id}/evaluations", tags=["evaluation"])


def serialize_run(run, include_dataset=False):
    data = {
        "id": run.id,
        "name": run.name,
        "status": run.status,
        "job_id": run.job_id,
        "created_at": run.created_at.isoformat(),
        "question_count": len(run.dataset),
        "config": run.config,
        "report": run.report or {},
    }
    if include_dataset:
        data["mapping"] = run.mapping
    return data


def get_run(db, user, subject_id, run_id):
    require_subject(db, user.id, subject_id)
    run = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id, EvaluationRun.user_id == user.id, EvaluationRun.subject_id == subject_id
        )
    )
    if run is None:
        raise AppError("evaluation_not_found", "Không tìm thấy lần đánh giá.", 404)
    return run


def create_run(db, user_id, subject_id, content, mapping, config, name):
    subject = require_subject(db, user_id, subject_id)
    from app.config import settings

    try:
        dataset = parse_dataset(content)
        configuration = EvaluationConfig.model_validate({"top_k": settings.retrieval_top_k, **config}).model_dump()
        if configuration["top_k"] > settings.retrieval_top_k:
            raise ValueError(
                "top_k exceeds the application RETRIEVAL_TOP_K; change server config for a broader comparison"
            )
    except (ValueError, TypeError) as exc:
        raise AppError("evaluation_dataset_invalid", str(exc), 422) from exc
    if not isinstance(mapping, dict):
        raise AppError("evaluation_mapping_invalid", "Mapping phải là JSON object.", 422)
    resolved = validate_mapping(db, user_id, subject_id, dataset, mapping)
    run = EvaluationRun(
        user_id=user_id,
        subject_id=subject_id,
        name=name[:200],
        dataset=dataset,
        mapping=resolved,
        config={**configuration, "corpus_revision": subject.corpus_revision},
        status="imported",
        report={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def enqueue_run(db, run):
    from app.worker import dispatch_job
    from app.config import settings
    from app.api import check_job_capacity

    check_job_capacity(db, run.user_id)
    require_subject(db, run.user_id, run.subject_id, lock=True)
    db.refresh(run)
    if run.status in ("queued", "running"):
        return run
    if run.status == "ready":
        return run
    active_jobs = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == run.user_id, Job.status.in_(["queued", "parsing", "chunking", "embedding", "running"]))
    )
    if active_jobs >= settings.max_user_jobs:
        raise AppError("job_limit", "Có quá nhiều tác vụ đang chạy.", 429)
    if run.job_id:
        job = db.get(Job, run.job_id)
        job.status, job.error_code, job.error_message = "queued", None, None
    else:
        job = Job(
            user_id=run.user_id,
            subject_id=run.subject_id,
            kind="evaluation",
            status="queued",
            progress={"completed": 0, "total": min(len(run.dataset), run.config["limit"]) * len(run.config["modes"])},
            checkpoint={},
            result={},
        )
        db.add(job)
        db.flush()
        run.job_id = job.id
    run.status = "queued"
    db.commit()
    # Persistent reconciler re-enqueues even if Redis publish fails.
    try:
        dispatch_job(job.id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("evaluation_dispatch_deferred", extra={"job_id": job.id})
    return run


@router.get("")
def list_runs(subject_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_subject(db, user.id, subject_id)
    return [
        serialize_run(run)
        for run in db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.user_id == user.id, EvaluationRun.subject_id == subject_id)
            .order_by(EvaluationRun.created_at.desc())
        )
    ]


@router.post("", status_code=201)
async def import_dataset(
    subject_id: str,
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    config: str = Form("{}"),
    name: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_subject(db, user.id, subject_id)
    content = bytearray()
    while chunk := await file.read(65536):
        content.extend(chunk)
        if len(content) > 10 * 1024 * 1024:
            raise AppError("evaluation_dataset_too_large", "Bộ câu hỏi vượt giới hạn 10 MB.", 413)
    try:
        mapping_data, config_data = json.loads(mapping), json.loads(config)
    except json.JSONDecodeError as exc:
        raise AppError("evaluation_json_invalid", "Mapping/config phải là JSON hợp lệ.", 422) from exc
    return serialize_run(
        create_run(
            db, user.id, subject_id, bytes(content), mapping_data, config_data, name or file.filename or "Evaluation"
        )
    )


@router.post("/{run_id}/run")
def start_run(subject_id: str, run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize_run(enqueue_run(db, get_run(db, user, subject_id, run_id)))


@router.get("/{run_id}")
def show_run(subject_id: str, run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = get_run(db, user, subject_id, run_id)
    data = serialize_run(run, True)
    data["results"] = [
        {"question_id": r.question_id, "mode": r.mode, "result": r.result}
        for r in db.scalars(
            select(EvaluationResult).where(EvaluationResult.run_id == run.id).order_by(EvaluationResult.created_at)
        )
    ]
    if run.job_id:
        job = db.get(Job, run.job_id)
        data["job"] = {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "error_code": job.error_code,
            "error_message": job.error_message,
        }
    return data


@router.get("/{run_id}/export")
def export_run(
    subject_id: str,
    run_id: str,
    format: str = "json",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    run = get_run(db, user, subject_id, run_id)
    rows = [
        {"question_id": r.question_id, "mode": r.mode, "result": r.result}
        for r in db.scalars(
            select(EvaluationResult).where(EvaluationResult.run_id == run.id).order_by(EvaluationResult.created_at)
        )
    ]
    try:
        content, mime_type = export_report(run, rows, format)
    except ValueError as exc:
        raise AppError("evaluation_export_format", str(exc), 422) from exc
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{run.id}.{format}"',
            "X-Content-Type-Options": "nosniff",
        },
    )

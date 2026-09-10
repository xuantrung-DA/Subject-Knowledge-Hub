"""Celery transport plus PostgreSQL-backed reconciliation (at-least-once)."""

from __future__ import annotations

from datetime import timedelta
import logging
import json
from threading import Event, Thread

from celery import Celery
from celery.signals import worker_ready, worker_shutdown, after_setup_logger, after_setup_task_logger
from sqlalchemy import and_, or_, select

from app.config import settings
from app.db import SessionLocal
from app.models import Document, DocumentVersion, Job, Subject, utcnow

log = logging.getLogger(__name__)


class WorkerJSONFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in ("job_id", "error_code", "error_type", "elapsed_seconds", "task_id", "task_name"):
            if hasattr(record, key):
                value[key] = getattr(record, key)
        # Exception messages may contain SQL document parameters. Keep the type;
        # durable jobs expose a sanitized machine-readable failure code/message.
        if record.exc_info:
            value["exception_type"] = record.exc_info[0].__name__
        return json.dumps(value, ensure_ascii=False)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _structured_worker_logging(logger, **_):
    for handler in logger.handlers:
        handler.setFormatter(WorkerJSONFormatter())


celery_app = Celery("subject_hub", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=1,
    task_track_started=True,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    task_publish_retry=False,
    broker_transport_options={
        "visibility_timeout": settings.job_timeout_seconds + 300,
        "socket_connect_timeout": 3,
        "socket_timeout": 5,
    },
    result_backend_transport_options={"socket_connect_timeout": 3, "socket_timeout": 5},
    task_soft_time_limit=settings.job_timeout_seconds,
    task_time_limit=settings.job_timeout_seconds + 60,
)


def dispatch_job(job_id: str) -> bool:
    """Publish only committed jobs. Broker failure leaves a recoverable DB row."""
    try:
        process_job.apply_async(args=[job_id], retry=False)
    except Exception:
        log.warning("queue_publish_failed", extra={"job_id": job_id}, exc_info=True)
        return False
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job:
            job.enqueued_at = utcnow()
            db.commit()
    return True


@celery_app.task(name="hub.process_job", bind=True)
def process_job(self, job_id: str):
    from app.ingestion import ingest_job, job_lock

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status in {"ready", "failed", "needs_ocr", "cancelled"}:
            return
        kind = job.kind
    if kind == "ingestion":
        return ingest_job(job_id)
    with job_lock(job_id) as acquired:
        if not acquired:
            return
        try:
            if kind == "summary":
                from app.rag import run_summary_job

                return run_summary_job(job_id)
            if kind == "evaluation":
                from app.evaluation import run_evaluation_job

                return run_evaluation_job(job_id)
            raise ValueError("Unknown job kind")
        except Exception as exc:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job and job.status not in {"ready", "cancelled"}:
                    job.status = "failed"
                    job.error_code = getattr(exc, "code", "job_failed")
                    job.error_message = getattr(exc, "message", "Job thất bại. Kiểm tra worker log rồi thử lại.")
                    job.heartbeat_at = utcnow()
                    db.commit()
            log.exception("background_job_failed", extra={"job_id": job_id})


def reconcile_jobs() -> dict:
    """Recover commit-before-publish and workers lost between durable batches.

    Active jobs have an advisory lock. A stale heartbeat alone never unlocks or
    force-restarts a healthy worker. Duplicate deliveries serialize at execution.
    """
    from app.ingestion import job_lock

    now = utcnow()
    stale = now - timedelta(seconds=settings.job_stale_seconds)
    requeue = now - timedelta(seconds=settings.job_reconcile_seconds)
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(Job.id)
                .where(
                    or_(
                        and_(Job.status == "queued", or_(Job.enqueued_at.is_(None), Job.enqueued_at < requeue)),
                        and_(
                            Job.status.in_(["parsing", "chunking", "embedding", "running"]),
                            or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < stale),
                        ),
                    )
                )
                .order_by(Job.created_at)
                .limit(100)
            )
        )
    result = {"examined": len(ids), "published": 0, "cancelled": 0, "active": 0}
    for job_id in ids:
        with job_lock(job_id) as acquired:
            if not acquired:
                result["active"] += 1
                continue
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if not job or job.status in {"ready", "failed", "needs_ocr", "cancelled"}:
                    continue
                subject = db.get(Subject, job.subject_id)
                document = db.get(Document, job.document_id) if job.document_id else None
                if not subject or subject.deleted_at or (job.document_id and (not document or document.deleted_at)):
                    job.status, job.error_code, job.error_message = (
                        "cancelled",
                        "document_deleted",
                        "Tài liệu hoặc môn đã bị xóa.",
                    )
                    if job.version_id:
                        version = db.get(DocumentVersion, job.version_id)
                        if version and version.status != "ready":
                            version.status = "cancelled"
                    db.commit()
                    result["cancelled"] += 1
                    continue
            # Release advisory lock before queue publication so a fast worker
            # cannot consume+ack while this reconciler still holds its lock.
        if dispatch_job(job_id):
            result["published"] += 1
    return result


def reconcile_loop(stop_event: Event):
    """Thread target shared by API lifespan and worker parent process."""
    import redis

    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    while not stop_event.is_set():
        try:
            reconcile_jobs()
        except Exception:
            log.warning("job_reconcile_failed", exc_info=True)
        try:
            client.set("hub:reconciler:heartbeat", utcnow().isoformat(), ex=max(60, settings.job_reconcile_seconds * 3))
        except Exception:
            pass
        stop_event.wait(settings.job_reconcile_seconds)


_worker_stop = Event()


@worker_ready.connect
def _start_reconciler(**_):
    _worker_stop.clear()
    Thread(target=reconcile_loop, args=(_worker_stop,), daemon=True, name="job-reconciler").start()


@worker_shutdown.connect
def _stop_reconciler(**_):
    _worker_stop.set()

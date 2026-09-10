#!/usr/bin/env python3
"""Kill/restart real Celery processes on isolated PostgreSQL/Redis; fake embeddings."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    from sqlalchemy import select, func
    from app.config import settings
    from app.db import SessionLocal
    from app.models import User, Subject, Document, DocumentVersion, Job, Chunk, DocumentPage
    from app.worker import dispatch_job
    from reportlab.pdfgen import canvas

    assert settings.test_mode and not settings.openai_api_key
    assert settings.redis_url.endswith("/15"), "Use the isolated compose.test stack."
    report = {
        "provider": "explicit deterministic fixture; no OpenAI",
        "trials": [],
        "status": "RUNNING",
        "fault": "SIGKILL entire Celery process group during second embedding batch",
        "pages_per_trial": 32,
        "job_stale_seconds": 10,
        "job_reconcile_seconds": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    for trial in range(args.trials):
        with tempfile.TemporaryDirectory(prefix="hub-recovery-") as temp:
            probe = Path(temp)
            path = probe / "recovery.pdf"
            pdf = canvas.Canvas(str(path))
            for page in range(1, 33):
                pdf.drawString(48, 750, f"Trial {trial + 1}, page {page}: immutable measurement code PROBE-{page:04}.")
                pdf.showPage()
            pdf.save()
            with SessionLocal() as db:
                user = User(email=f"recovery-{uuid4().hex}@example.com", password_hash="not-an-auth-test")
                db.add(user)
                db.flush()
                subject = Subject(user_id=user.id, name="Isolated process recovery probe")
                db.add(subject)
                db.flush()
                document = Document(subject_id=subject.id, name="recovery.pdf")
                db.add(document)
                db.flush()
                version = DocumentVersion(
                    document_id=document.id,
                    version=1,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    file_path=str(path),
                    size_bytes=path.stat().st_size,
                )
                db.add(version)
                db.flush()
                job = Job(user_id=user.id, subject_id=subject.id, document_id=document.id, version_id=version.id)
                db.add(job)
                db.commit()
                jid, vid, did = job.id, version.id, document.id
            env = {
                **os.environ,
                "SKH_RECOVERY_PROBE": str(probe),
                "JOB_STALE_SECONDS": "10",
                "JOB_RECONCILE_SECONDS": "1",
                "EMBEDDING_BATCH_SIZE": "8",
                "CHUNK_PAGE_BOUNDARIES": "true",
                "PYTHONPATH": "/app:/app/scripts",
            }
            processes = []
            with (args.output.parent / f"recovery-worker-{trial + 1}.log").open("w") as log:

                def start():
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "celery",
                            "-A",
                            "recovery_probe_worker:celery_app",
                            "worker",
                            "--concurrency=1",
                            "--loglevel=INFO",
                            "--without-gossip",
                            "--without-mingle",
                        ],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    processes.append(process)
                    return process

                try:
                    first = start()
                    dispatch_job(jid)
                    deadline = time.monotonic() + 90
                    while not (probe / "paused").exists():
                        assert first.poll() is None, "Worker exited before checkpoint"
                        assert time.monotonic() < deadline, "No durable checkpoint before deadline"
                        time.sleep(0.5)
                    with SessionLocal() as db:
                        committed = db.scalar(
                            select(func.count())
                            .select_from(Chunk)
                            .where(Chunk.version_id == vid, Chunk.embedding.is_not(None))
                        )
                        total_before = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == vid))
                    assert committed == 8 and total_before == 32
                    os.killpg(first.pid, signal.SIGKILL)
                    first.wait(timeout=10)
                    began = time.monotonic()
                    second = start()
                    # No manual requeue: the real worker reconciler must recover it.
                    while True:
                        with SessionLocal() as db:
                            job = db.get(Job, jid)
                            if job.status == "ready":
                                pages = db.scalar(
                                    select(func.count()).select_from(DocumentPage).where(DocumentPage.version_id == vid)
                                )
                                chunks = db.scalar(
                                    select(func.count()).select_from(Chunk).where(Chunk.version_id == vid)
                                )
                                distinct = db.scalar(
                                    select(func.count(func.distinct(Chunk.ordinal))).where(Chunk.version_id == vid)
                                )
                                assert pages == chunks == distinct == 32
                                assert db.get(Document, did).active_version_id == vid
                                attempts = job.attempts
                                break
                            assert job.status not in ("failed", "cancelled"), job.error_code
                        assert second.poll() is None and time.monotonic() - began < 90
                        time.sleep(0.5)
                    calls = [json.loads(line) for line in (probe / "calls.jsonl").read_text().splitlines()]
                    first_batch = set(calls[0]["texts"])
                    assert not any(first_batch.intersection(call["texts"]) for call in calls[1:]), (
                        "Committed batch embedded again"
                    )
                    assert attempts == 2
                    report["trials"].append(
                        {
                            "trial": trial + 1,
                            "job_id": jid,
                            "status": "PASS",
                            "recovery_seconds": round(time.monotonic() - began, 3),
                            "pages": pages,
                            "chunks": chunks,
                            "unique_chunk_ordinals": distinct,
                            "attempts": attempts,
                            "committed_embeddings_preserved": committed,
                            "embedding_attempts": len(calls),
                        }
                    )
                    save()
                finally:
                    for process in processes:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=12)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait(timeout=10)
    report["status"] = "PASS"
    save()
    print(json.dumps(report))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Index the pinned QASPER corpus, then run its fixed retrieval-only test100."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        print(
            "Dry run: pinned corpus embeddings plus <=30,000 reserved evaluation embedding tokens; no generated answers."
        )
        return
    if args.output.exists():
        raise RuntimeError("Existing run found. Inspect it before requesting another paid run.")
    from sqlalchemy import select
    from app.config import settings
    from app.db import SessionLocal
    from app.models import User, Subject, Job, EvaluationRun, EvaluationResult, UsageEvent, utcnow
    from app.eval_cli import import_qasper
    from app.evaluation_api import create_run
    from app.evaluation import run_evaluation_job, export_report

    settings.query_cache_ttl = 0
    report = {
        "status": "RUNNING",
        "provider": "live_openai_embeddings",
        "generation": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "QASPER fixed eligible test100, 95 papers",
        "source": "https://huggingface.co/datasets/allenai/qasper",
        "license": "CC-BY-4.0",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        assert user is not None
        name = "QASPER retrieval " + uuid4().hex[:8]
        import_qasper(db, user, SimpleNamespace(directory=args.directory, confirm=True, subject_id=None, name=name))
        subject = db.scalar(select(Subject).where(Subject.user_id == user.id, Subject.name == name))
        report["subject_id"] = subject.id
        save()
        deadline = time.monotonic() + 900
        while True:
            db.expire_all()
            jobs = db.scalars(select(Job).where(Job.subject_id == subject.id)).all()
            report["ingestion"] = {
                status: sum(j.status == status for j in jobs) for status in sorted({j.status for j in jobs})
            }
            save()
            assert not any(j.status in ("failed", "cancelled") for j in jobs), [
                (j.id, j.error_code) for j in jobs if j.status == "failed"
            ]
            if len(jobs) == 95 and all(j.status == "ready" for j in jobs):
                break
            assert time.monotonic() < deadline, "Ingestion deadline exceeded"
            time.sleep(2)
        run = create_run(
            db,
            user.id,
            subject.id,
            (args.directory / "test100.jsonl").read_bytes(),
            {},
            {
                "modes": ["lexical", "dense", "hybrid"],
                "generate_answers": False,
                "limit": 100,
                "top_k": 6,
                "max_tokens": 30000,
                "max_calls": 400,
            },
            "Frozen QASPER eligible test100",
        )
        job = Job(user_id=user.id, subject_id=subject.id, kind="evaluation", enqueued_at=utcnow())
        db.add(job)
        db.flush()
        run.job_id = job.id
        run.status = "queued"
        db.commit()
        report.update(run_id=run.id, job_id=job.id)
        save()
        run_evaluation_job(job.id)
        db.expire_all()
        run = db.get(EvaluationRun, run.id)
        rows = [
            {"question_id": r.question_id, "mode": r.mode, "result": r.result}
            for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
        ]
        for fmt in ("json", "csv", "md"):
            content, _ = export_report(run, rows, fmt)
            args.output.with_name(args.output.stem + "-results." + fmt).write_text(content, encoding="utf-8")
        report.update(status=run.status, report=run.report, finished_at=datetime.now(timezone.utc).isoformat())
        events = db.scalars(select(UsageEvent).where(UsageEvent.subject_id == subject.id)).all()
        report["usage"] = {
            "input_tokens": sum(e.input_tokens for e in events),
            "output_tokens": sum(e.output_tokens for e in events),
            "provider_calls": sum(1 + e.retries for e in events if not e.cache_hit),
            "estimated_cost_usd": sum(e.estimated_cost_usd or 0 for e in events),
        }
        save()
        assert run.status == "ready", run.report
    print(json.dumps({"status": report["status"], "usage": report["usage"]}))


if __name__ == "__main__":
    main()

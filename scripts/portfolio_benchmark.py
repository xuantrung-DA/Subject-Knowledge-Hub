#!/usr/bin/env python3
"""Bounded live benchmark using production parser, ingestion, pgvector and RAG.

Runs production job functions in this process (not a Celery throughput test).
Uses a separate corpus for each chunk strategy, reuses it for the held-out run.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=["baseline", "page"], required=True)
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute_paid:
        print(
            "Dry run: at most 300k reserved evaluation tokens on dev or 700k on test; plus at most 250k ingestion embedding tokens per new corpus."
        )
        return
    from sqlalchemy import select
    from app.config import settings
    from app.db import SessionLocal
    from app.models import (
        User,
        Subject,
        Document,
        DocumentVersion,
        Job,
        UsageEvent,
        EvaluationRun,
        EvaluationResult,
        utcnow,
    )
    from app.ingestion import ingest_job
    from app.evaluation_api import create_run
    from app.evaluation import run_evaluation_job, export_report
    from app.security import hash_password

    # The single experimental variable; all other serving limits are fixed.
    settings.chunk_page_boundaries = args.strategy == "page"
    assert settings.max_context_tokens == 1800
    assert settings.max_question_tokens <= 8000
    assert settings.max_ingestion_tokens <= 25000
    directory = ROOT / "fixtures" / "portfolio"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["hashes"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected, name
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / f"{args.strategy}-corpus.json"
    report_path = args.output_dir / f"{args.strategy}-{args.split}.json"
    if report_path.exists():
        raise RuntimeError("Output already exists. Inspect or resume explicitly; refusing an accidental paid rerun.")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "strategy": args.strategy,
        "split": args.split,
        "provider": "live_openai",
        "execution": "production job functions, real PostgreSQL; no Celery throughput claim",
        "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        "runs": {},
    }

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    with SessionLocal() as db:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            subject = db.get(Subject, state["subject_id"])
            assert subject is not None
            user = db.get(User, subject.user_id)
        else:
            user = User(email=f"portfolio-{uuid4().hex}@example.com", password_hash=hash_password(uuid4().hex))
            db.add(user)
            db.flush()
            subject = Subject(user_id=user.id, name=f"Portfolio {args.strategy} — original synthetic runbooks")
            db.add(subject)
            db.commit()
            state = {"subject_id": subject.id, "email": user.email, "ingestion": []}
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        report.update(subject_id=subject.id, email=user.email)
        corpus = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
        for entry in corpus:
            document = db.scalar(
                select(Document).where(
                    Document.subject_id == subject.id, Document.document_key == entry["document_key"]
                )
            )
            if document and document.active_version_id:
                continue
            assert document is None, "Incomplete previous ingestion; inspect the existing durable job before retrying."
            document = Document(
                subject_id=subject.id, name=entry["document_key"] + ".pdf", document_key=entry["document_key"]
            )
            db.add(document)
            db.flush()
            vid = str(uuid4())
            path = settings.storage_dir / f"{vid}.pdf"
            shutil.copyfile(directory / document.name, path)
            version = DocumentVersion(
                id=vid,
                document_id=document.id,
                version=1,
                sha256=entry["sha256"],
                file_path=str(path),
                size_bytes=path.stat().st_size,
            )
            db.add(version)
            db.flush()
            job = Job(
                user_id=user.id, subject_id=subject.id, document_id=document.id, version_id=vid, enqueued_at=utcnow()
            )
            db.add(job)
            db.commit()
            started = time.perf_counter()
            ingest_job(job.id)
            db.expire_all()
            assert db.get(Job, job.id).status == "ready", db.get(Job, job.id).error_code
            state["ingestion"].append(
                {
                    "document": document.name,
                    "job_id": job.id,
                    "seconds": time.perf_counter() - started,
                    "chunks": db.get(DocumentVersion, vid).chunk_count,
                }
            )
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            print(json.dumps({"ingested": document.name, "strategy": args.strategy}), flush=True)
        settings.query_cache_ttl = 0
        # Reserve limits in the durable evaluation budget before provider attempts.
        for label, answers, modes in [
            ("retrieval", False, ["lexical", "dense", "hybrid"]),
            ("answers", True, ["dense"]),
        ]:
            cap = 10000 if not answers else (290000 if args.split == "dev" else 690000)
            run = create_run(
                db,
                user.id,
                subject.id,
                (directory / f"{args.split}.jsonl").read_bytes(),
                {},
                {
                    "modes": modes,
                    "generate_answers": answers,
                    "limit": 100,
                    "top_k": 6,
                    "max_tokens": cap,
                    "max_calls": 600,
                },
                f"{args.strategy} {args.split} {label}",
            )
            job = Job(user_id=user.id, subject_id=subject.id, kind="evaluation", enqueued_at=utcnow())
            db.add(job)
            db.flush()
            run.job_id = job.id
            run.status = "queued"
            db.commit()
            report["runs"][label] = {"run_id": run.id, "job_id": job.id, "status": "RUNNING"}
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
                (args.output_dir / f"{args.strategy}-{args.split}-{label}.{fmt}").write_text(content, encoding="utf-8")
            report["runs"][label].update(status=run.status, report=run.report)
            save()
            assert run.status == "ready", run.report
        events = db.scalars(select(UsageEvent).where(UsageEvent.subject_id == subject.id)).all()
        report["cumulative_corpus_usage"] = {
            "input_tokens": sum(e.input_tokens for e in events),
            "output_tokens": sum(e.output_tokens for e in events),
            "provider_calls": sum(1 + e.retries for e in events if not e.cache_hit),
            "estimated_cost_usd": sum(e.estimated_cost_usd or 0 for e in events),
            "unpriced_events": sum(e.estimated_cost_usd is None and not e.cache_hit for e in events),
        }
    report.update(status="COMPLETE", finished_at=datetime.now(timezone.utc).isoformat())
    save()
    print(
        json.dumps(
            {"status": report["status"], "artifact": str(report_path), "usage": report["cumulative_corpus_usage"]}
        )
    )


if __name__ == "__main__":
    main()

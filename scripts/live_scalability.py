#!/usr/bin/env python3
"""Explicit paid 1,000-page ingestion and incremental-index verification.

Uses a project-owned synthetic PDF, real OpenAI embeddings and three RAG answers.
Default is dry-run. Execute inside the API image on the normal app database.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import tempfile
import time
from uuid import uuid4
from scalability_smoke import create_pdf, database_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute_paid:
        print(
            "Dry run: <=2,000,000 reserved embedding tokens per job, 2 jobs, 3 answers <=24,000 reserved tokens each. Conservative price ceiling <0.20 USD at verified configured models."
        )
        return
    from sqlalchemy import select, func
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Document, DocumentVersion, Job, Chunk, UsageEvent, Subject, utcnow
    from app.provider import OpenAIProvider
    from app.ingestion import ingest_job
    from app.rag import answer
    from app.tokens import count_embedding_tokens
    from reportlab.pdfgen import canvas

    assert settings.openai_embedding_model == "text-embedding-3-small"
    assert settings.openai_chat_model == "gpt-4.1-mini"
    assert settings.max_ingestion_tokens <= 2000000 and settings.max_question_tokens <= 24000
    if args.output.exists():
        raise RuntimeError("Inspect existing result before deliberately choosing another paid output path.")

    class MeteredProvider(OpenAIProvider):
        def __init__(self):
            super().__init__()
            self.calls = self.inputs = self.max_batch_inputs = self.max_batch_tokens = 0

        def embed(self, texts, **kwargs):
            self.calls += 1
            self.inputs += len(texts)
            self.max_batch_inputs = max(self.max_batch_inputs, len(texts))
            self.max_batch_tokens = max(self.max_batch_tokens, sum(count_embedding_tokens(t) for t in texts))
            return super().embed(texts, **kwargs)

    provider = MeteredProvider()
    report = {
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": "live_openai",
        "corpus": "Project-owned synthetic 1000-page PDF; not representative of arbitrary PDFs",
        "answers": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    with tempfile.TemporaryDirectory(prefix="hub-live-scale-") as temp:
        path = Path(temp) / "live-1000.pdf"
        anchors = create_pdf(path, 1000)
        began = time.perf_counter()
        result = database_pipeline(path, provider, anchors)
        result["retrieval_implementation"] = (
            "production ingestion + PostgreSQL exact pgvector + real text-embedding-3-small"
        )
        report.update(
            result,
            ingestion_and_retrieval_seconds=round(time.perf_counter() - began, 3),
            pages=1000,
            embedding_calls=provider.calls,
            embedding_inputs=provider.inputs,
            max_batch_inputs=provider.max_batch_inputs,
            max_batch_tokens=provider.max_batch_tokens,
        )
        save()
    with SessionLocal() as db:
        uid = db.get(Subject, report["subject_id"]).user_id
        for page, (anchor, expected) in anchors.items():
            response = answer(
                db,
                uid,
                report["subject_id"],
                f"What is the calibration value of {anchor}? Give only the value and its citation.",
                provider=provider,
                disable_cache=True,
            )
            passed = expected in response["answer"] and any(
                c["page_start"] <= page <= c["page_end"] for c in response["citations"]
            )
            report["answers"].append({"page": page, "expected": expected, "passed": passed, "response": response})
            save()
        original_vid = db.get(Document, report["document_id"]).active_version_id
        before = set(db.scalars(select(Chunk.id).where(Chunk.version_id == original_vid)))
        before_usage = db.scalar(
            select(func.count()).select_from(UsageEvent).where(UsageEvent.job_id == report["job_id"])
        )
        document = Document(subject_id=report["subject_id"], name="incremental-3.pdf")
        db.add(document)
        db.flush()
        vid = str(uuid4())
        path = settings.storage_dir / f"{vid}.pdf"
        pdf = canvas.Canvas(str(path))
        for page in range(1, 4):
            pdf.drawString(48, 750, f"Additional independent appendix {page}: incremental code INCREMENT-{page}.")
            pdf.showPage()
        pdf.save()
        version = DocumentVersion(
            id=vid,
            document_id=document.id,
            version=1,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_path=str(path),
            size_bytes=path.stat().st_size,
        )
        db.add(version)
        db.flush()
        job = Job(
            user_id=uid, subject_id=report["subject_id"], document_id=document.id, version_id=vid, enqueued_at=utcnow()
        )
        db.add(job)
        db.commit()
        inputs_before, calls_before = provider.inputs, provider.calls
        began = time.perf_counter()
        assert ingest_job(job.id, provider)["status"] == "ready"
        db.expire_all()
        after = set(db.scalars(select(Chunk.id).where(Chunk.version_id == original_vid)))
        after_usage = db.scalar(
            select(func.count()).select_from(UsageEvent).where(UsageEvent.job_id == report["job_id"])
        )
        assert before == after and len(after) == 1000 and before_usage == after_usage
        assert provider.inputs - inputs_before == 3
        report["incremental"] = {
            "status": "PASS",
            "new_pages": 3,
            "new_embedding_inputs": provider.inputs - inputs_before,
            "new_embedding_calls": provider.calls - calls_before,
            "original_chunks_preserved": len(after),
            "original_job_extra_usage_events": after_usage - before_usage,
            "seconds": round(time.perf_counter() - began, 3),
        }
        events = db.scalars(select(UsageEvent).where(UsageEvent.subject_id == report["subject_id"])).all()
        report["usage"] = {
            "input_tokens": sum(e.input_tokens for e in events),
            "output_tokens": sum(e.output_tokens for e in events),
            "provider_calls": sum(1 + e.retries for e in events if not e.cache_hit),
            "estimated_cost_usd": sum(e.estimated_cost_usd or 0 for e in events),
            "unpriced_events": sum(e.estimated_cost_usd is None and not e.cache_hit for e in events),
        }
    report.update(
        status="PASS"
        if all(r["evidence_found"] for r in report["retrieval_checks"]) and all(r["passed"] for r in report["answers"])
        else "FAIL",
        finished_at=datetime.now(timezone.utc).isoformat(),
        process_peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        limitations=[
            "Single synthetic corpus on this machine.",
            "Production job functions execute in the measurement process; this is not a Celery throughput benchmark.",
            "RSS includes parser, tokenizer, SDK and Python runtime.",
        ],
    )
    save()
    print(json.dumps({"status": report["status"], "pages": report["pages"], "usage": report["usage"]}))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

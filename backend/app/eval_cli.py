"""Local administrator CLI. Run inside the API container with existing account email."""

from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True, help="Existing local account; CLI requires trusted container/DB access"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fixtures = commands.add_parser(
        "import-fixtures", help="Create a separate fixture subject and enqueue normal PDF ingestion"
    )
    fixtures.add_argument("--directory", type=Path, default=Path("/app/fixtures/project"))
    fixtures.add_argument("--name", default="Project regression fixtures")
    fixtures.add_argument("--subject-id", help="Reuse an existing owned subject for idempotent import")
    imported = commands.add_parser("import", help="Import evaluation JSONL, never into the document index")
    imported.add_argument("--subject-id", required=True)
    imported.add_argument("--dataset", type=Path, required=True)
    imported.add_argument("--mapping", type=Path, help="JSON document_key -> document_id; keys auto-map when omitted")
    imported.add_argument("--name", default="CLI evaluation")
    imported.add_argument("--modes", default="lexical,dense,hybrid")
    imported.add_argument("--answers", action="store_true")
    imported.add_argument("--limit", type=int, default=10)
    imported.add_argument("--top-k", type=int, help="Defaults to the running application retrieval limit")
    imported.add_argument("--max-tokens", type=int, default=100000)
    imported.add_argument("--max-calls", type=int, default=200)
    for name in ("run", "status", "export"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        if name == "export":
            command.add_argument("--format", choices=["json", "csv", "md"], default="json")
            command.add_argument("--output", type=Path, required=True)
    qasper = commands.add_parser(
        "import-qasper", help="Create a separate QASPER paragraph corpus; print estimate before --confirm"
    )
    qasper.add_argument("--directory", type=Path, default=Path("/app/artifacts/qasper"))
    qasper.add_argument("--name", default="QASPER fixed test100 — paragraphs")
    qasper.add_argument("--confirm", action="store_true")
    qasper.add_argument("--subject-id", help="Resume import into the same separate owned QASPER subject")
    args = parser.parse_args()
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import User, Subject, EvaluationRun, EvaluationResult
    from app.security import require_subject

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if not user:
            parser.error("Create this account in the application first")
        if args.command == "import-fixtures":
            from fastapi import UploadFile
            from app.api import upload_version

            if args.subject_id:
                subject = require_subject(db, user.id, args.subject_id)
            else:
                subject = Subject(user_id=user.id, name=args.name)
                db.add(subject)
                db.commit()
            responses = []
            for key in ("fixture_vi", "fixture_en", "conflict", "injection"):
                with (args.directory / f"{key}.pdf").open("rb") as stream:
                    responses.append(
                        asyncio.run(
                            upload_version(
                                subject.id, None, UploadFile(filename=f"{key}.pdf", file=stream), key, user, db
                            )
                        )
                    )
            print(
                json.dumps(
                    {
                        "subject_id": subject.id,
                        "ingestion": responses,
                        "next": "Wait for all jobs ready before importing regression JSONL.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "import":
            from app.evaluation_api import create_run, serialize_run

            mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {}
            config = {
                "modes": args.modes.split(","),
                "generate_answers": args.answers,
                "limit": args.limit,
                "max_tokens": args.max_tokens,
                "max_calls": args.max_calls,
            }
            if args.top_k is not None:
                config["top_k"] = args.top_k
            run = create_run(db, user.id, args.subject_id, args.dataset.read_bytes(), mapping, config, args.name)
            print(json.dumps(serialize_run(run), ensure_ascii=False, indent=2))
        elif args.command in ("run", "status", "export"):
            from app.evaluation_api import enqueue_run, serialize_run
            from app.evaluation import export_report

            run = db.scalar(
                select(EvaluationRun).where(EvaluationRun.id == args.run_id, EvaluationRun.user_id == user.id)
            )
            if not run:
                parser.error("Evaluation not found for this account")
            require_subject(db, user.id, run.subject_id)
            if args.command == "run":
                run = enqueue_run(db, run)
            if args.command == "export":
                rows = [
                    {"question_id": r.question_id, "mode": r.mode, "result": r.result}
                    for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
                ]
                content, _ = export_report(run, rows, args.format)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(content, encoding="utf-8")
                print(str(args.output))
            else:
                print(json.dumps(serialize_run(run), ensure_ascii=False, indent=2))
        elif args.command == "import-qasper":
            import_qasper(db, user, args)


def import_qasper(db, user, args):
    from sqlalchemy import select
    from app.api import check_job_capacity
    from app.chunking import chunk_pages
    from app.config import settings
    from app.models import Subject, Document, DocumentVersion, Chunk, Job
    from app.security import require_subject
    from app.provider import estimate_cost
    from app.worker import dispatch_job
    from app.tokens import count_embedding_tokens
    from app.evaluation import canonical_hash

    corpus_path = args.directory / "corpus.jsonl"
    manifest = json.loads((args.directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("question_count") != 100 or len(manifest.get("question_ids", [])) != 100:
        raise ValueError("Require a materialized fixed 100-ID QASPER manifest from scripts/qasper.py")
    if hashlib.sha256(corpus_path.read_bytes()).hexdigest() != manifest["corpus_sha256"]:
        raise ValueError("QASPER corpus differs from the pinned manifest")
    corpus = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def chunks_for(paper):
        ordinal = 0
        for paragraph in paper["paragraphs"]:
            # Reuse the application's tokenizer/paragraph splitter. The temporary
            # sequence index is discarded: persisted evidence has paragraph IDs only.
            for piece in chunk_pages(
                [SimpleNamespace(number=1, text=paragraph["text"])],
                target_tokens=settings.chunk_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            ):
                yield dict(
                    ordinal=ordinal,
                    text=piece.text,
                    token_count=piece.token_count,
                    page_start=None,
                    page_end=None,
                    pages=[],
                    paragraph_ids=[paragraph["id"]],
                    content_hash=piece.content_hash,
                )
                ordinal += 1

    estimates = [(paper, list(chunks_for(paper))) for paper in corpus]
    tokens = sum(count_embedding_tokens(chunk["text"]) for _, chunks in estimates for chunk in chunks)
    estimate = {
        "papers": len(corpus),
        "chunks": sum(len(chunks) for _, chunks in estimates),
        "embedding_tokens_estimate": tokens,
        "embedding_cost_estimate_usd": estimate_cost(settings.openai_embedding_model, tokens, 0, 0),
        "model": settings.openai_embedding_model,
        "dimensions": settings.openai_embedding_dimensions,
        "retry_ceiling_multiplier": settings.openai_max_retries + 1,
        "note": "Includes corpus embedding only, not evaluation answers. Use --confirm to enqueue; no synthetic PDFs are created.",
    }
    print(json.dumps(estimate, ensure_ascii=False, indent=2))
    if not args.confirm:
        return
    if args.subject_id:
        subject = require_subject(db, user.id, args.subject_id)
        existing = db.scalars(
            select(Document).where(Document.subject_id == subject.id, Document.deleted_at.is_(None))
        ).all()
        if any(d.source_type != "paragraph" or not (d.document_key or "").startswith("qasper:") for d in existing):
            raise ValueError("QASPER requires a separate paragraph-only collection")
    else:
        subject = Subject(user_id=user.id, name=args.name)
        db.add(subject)
        db.commit()
    print(json.dumps({"subject_id": subject.id, "resume": "Pass --subject-id with this value after interruption."}))
    responses = []
    for paper, chunks in estimates:
        import time
        from app.errors import AppError

        started = time.monotonic()
        while True:
            try:
                check_job_capacity(db, user.id)
                break
            except AppError as exc:
                db.rollback()
                if exc.status_code != 429 or time.monotonic() - started > settings.job_timeout_seconds:
                    raise
                time.sleep(2)  # Bounded CLI admission wait; worker concurrency remains one.
        require_subject(db, user.id, subject.id, lock=True)
        existing = db.scalar(
            select(Document).where(
                Document.subject_id == subject.id,
                Document.document_key == paper["document_key"],
                Document.deleted_at.is_(None),
            )
        )
        if existing:
            responses.append({"document_key": paper["document_key"], "document_id": existing.id, "duplicate": True})
            db.commit()
            continue
        document = Document(
            subject_id=subject.id,
            name=paper["title"][:255],
            document_key=paper["document_key"],
            source_type="paragraph",
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=canonical_hash(paper),
            file_path="",
            size_bytes=len(json.dumps(paper).encode()),
            status="queued",
            page_count=0,
            text_page_count=0,
            chunk_count=len(chunks),
            warning=["QASPER full-text paragraphs: not PDF pages; PDF parser not exercised."],
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            config_version=settings.config_version,
        )
        db.add(version)
        db.flush()
        for chunk in chunks:
            db.add(
                Chunk(
                    version_id=version.id,
                    embedding_model=settings.openai_embedding_model,
                    config_version=settings.config_version,
                    **chunk,
                )
            )
        job = Job(
            user_id=user.id,
            subject_id=subject.id,
            document_id=document.id,
            version_id=version.id,
            kind="ingestion",
            status="queued",
            checkpoint={"parse_complete": True, "chunk_complete": True, "chunks_written": len(chunks)},
            progress={"chunks_total": len(chunks), "evidence_unit": "paragraph"},
            result={},
        )
        db.add(job)
        db.commit()
        try:
            dispatch_job(job.id)
        except Exception:
            pass  # Durable reconciler will publish.
        responses.append({"document_key": paper["document_key"], "document_id": document.id, "job_id": job.id})
    print(
        json.dumps(
            {
                "subject_id": subject.id,
                "documents": responses,
                "next": "Wait for ready, then eval_cli import --dataset /app/artifacts/qasper/test100.jsonl --subject-id ...",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

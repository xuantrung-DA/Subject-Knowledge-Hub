#!/usr/bin/env python3
"""Reproducible 1,000-page smoke. NO OpenAI calls; provider is explicitly fake.

Default tests parser, chunker, batching and streaming exact fake-vector retrieval.
--database additionally uses real PostgreSQL ingestion/checkpoints/pgvector retrieval.
The latter needs migrated DATABASE_URL and writes an isolated test subject.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import resource
import shutil
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from reportlab.pdfgen import canvas  # noqa: E402 - standalone script sets the backend import path first
from app.chunking import chunk_pages  # noqa: E402 - standalone script sets the backend import path first
from app.parser import PDFParser  # noqa: E402 - standalone script sets the backend import path first
from app.tokens import count_embedding_tokens  # noqa: E402 - standalone script sets the backend import path first


class FakeEmbeddingProvider:
    """Local hash bag-of-words fixture: never used in production runtime."""

    def __init__(self, dimensions=1536):
        self.dimensions = dimensions
        self.calls = 0
        self.inputs = 0
        self.max_batch_inputs = 0
        self.max_batch_tokens = 0
        self.last_usage = None

    def vector(self, text):
        vector = [0.0] * self.dimensions
        for token in set(re.findall(r"\w+", text.lower())):
            digest = hashlib.sha256(token.encode()).digest()
            # Four signed projections reduce accidental one-bucket collisions;
            # this remains a deterministic test vector, not semantic AI.
            for projection in range(4):
                value = int.from_bytes(digest[projection * 4 : projection * 4 + 4], "big")
                index = value % self.dimensions
                vector[index] += 1.0 if value & 0x80000000 else -1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed(self, texts, **_):
        self.calls += 1
        self.inputs += len(texts)
        self.max_batch_inputs = max(self.max_batch_inputs, len(texts))
        self.max_batch_tokens = max(self.max_batch_tokens, sum(count_embedding_tokens(t) for t in texts))
        return [self.vector(text) for text in texts]


def create_pdf(path, pages):
    anchors = {1: ("nebularuby", "17"), max(2, pages // 2): ("tundraopal", "29"), pages: ("quasaramber", "43")}
    c = canvas.Canvas(str(path), pageCompression=1)
    for number in range(1, pages + 1):
        c.setTitle("Project-owned scalability fixture")
        text = c.beginText(40, 790)
        text.setFont("Helvetica", 10)
        text.textLine(f"Independent lesson {number}: unique page reference P{number:04d}.")
        for paragraph in range(8):
            text.textLine(
                f"Topic{number:04d} section {paragraph}: experimental records distinguish each physical PDF page."
            )
            text.textLine(
                f"The measured sample at position {paragraph} is {number * 11 + paragraph}; retain this source provenance."
            )
            text.textLine("")
        if number in anchors:
            word, value = anchors[number]
            text.textLine(f"The verification fact {word} has calibration value {value}.")
        c.drawText(text)
        c.showPage()
    c.save()
    return anchors


def local_pipeline(path, output_dir, provider, anchors):
    from app.config import settings

    archive = output_dir / "chunk_vectors.jsonl"
    total_chunks = 0
    total_tokens = 0
    batch = []
    batch_tokens = 0
    with archive.open("w") as target:

        def flush():
            nonlocal batch, batch_tokens
            vectors = provider.embed([item.text for item in batch])
            for item, vector in zip(batch, vectors):
                target.write(
                    json.dumps({"ordinal": item.ordinal, "pages": item.pages, "text": item.text, "vector": vector})
                    + "\n"
                )
            batch, batch_tokens = [], 0

        with PDFParser(path, max_pages=settings.max_pdf_pages) as parser:
            for chunk in chunk_pages(
                parser.pages(), target_tokens=settings.chunk_tokens, overlap_tokens=settings.chunk_overlap_tokens
            ):
                tokens = count_embedding_tokens(chunk.text)
                if batch and (
                    len(batch) >= settings.embedding_batch_size
                    or batch_tokens + tokens > settings.embedding_batch_tokens
                ):
                    flush()
                batch.append(chunk)
                batch_tokens += tokens
                total_tokens += tokens
                total_chunks += 1
            if batch:
                flush()
    found = []
    for page, (anchor, value) in anchors.items():
        query = provider.vector(anchor)
        best = []
        with archive.open() as source:
            for line in source:
                item = json.loads(line)
                score = sum(a * b for a, b in zip(query, item["vector"]))
                best.append((score, item["ordinal"], item["pages"], value in item["text"] and anchor in item["text"]))
                best = sorted(best, reverse=True)[:6]
        found.append(
            {
                "query": anchor,
                "expected_page": page,
                "expected_value": value,
                "top_pages": [entry[2] for entry in best],
                "evidence_found": any(page in entry[2] and entry[3] for entry in best),
            }
        )
    return {
        "chunks": total_chunks,
        "embedding_input_tokens": total_tokens,
        "retrieval_checks": found,
        "database_verified": False,
        "retrieval_implementation": "streamed exact cosine over fake vectors; not pgvector",
    }


def database_pipeline(path, provider, anchors):
    from sqlalchemy import func, select
    from app.config import settings
    from app.db import SessionLocal
    from app.models import User, Subject, Document, DocumentVersion, Job, Chunk, new_id
    from app.ingestion import ingest_job
    from app.retrieval import retrieve

    document_id, version_id, job_id = new_id(), new_id(), new_id()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    permanent = settings.storage_dir / f"{version_id}.pdf"
    shutil.copyfile(path, permanent)
    with SessionLocal() as db:
        user = User(email=f"scalability-{uuid4()}@example.invalid", password_hash="unusable-fixture-account")
        db.add(user)
        db.flush()
        subject = Subject(user_id=user.id, name="[TEST] 1000-page scalability smoke")
        db.add(subject)
        db.flush()
        document = Document(id=document_id, subject_id=subject.id, name=path.name)
        db.add(document)
        db.flush()
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            version=1,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_path=str(permanent),
            size_bytes=permanent.stat().st_size,
        )
        db.add(version)
        db.flush()
        job = Job(
            id=job_id,
            user_id=user.id,
            subject_id=subject.id,
            document_id=document.id,
            version_id=version.id,
            kind="ingestion",
            status="queued",
        )
        db.add(job)
        db.commit()
        user_id, subject_id = user.id, subject.id
    status = ingest_job(job_id, provider=provider)
    if status["status"] != "ready":
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            raise RuntimeError(f"{job.error_code}: {job.error_message}")
    found = []
    with SessionLocal() as db:
        for page, (anchor, value) in anchors.items():
            rows = retrieve(db, user_id, subject_id, anchor, mode="dense", provider=provider)
            found.append(
                {
                    "query": anchor,
                    "expected_page": page,
                    "expected_value": value,
                    "top_pages": [[r["page_start"], r["page_end"]] for r in rows],
                    "evidence_found": any(
                        r["page_start"] <= page <= r["page_end"] and anchor in r["text"] and value in r["text"]
                        for r in rows
                    ),
                }
            )
        chunks = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == version_id))
        version = db.get(DocumentVersion, version_id)
        result = {
            "chunks": chunks,
            "pages_persisted": version.page_count,
            "retrieval_checks": found,
            "database_verified": True,
            "retrieval_implementation": "production ingestion + PostgreSQL pgvector dense retrieval using fake embeddings",
            "subject_id": subject_id,
            "document_id": document_id,
            "job_id": job_id,
        }
        db.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=1000)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/scalability.json")
    args = parser.parse_args()
    if args.pages < 3:
        parser.error("--pages must be at least 3")
    from app.config import settings

    provider = FakeEmbeddingProvider(settings.openai_embedding_dimensions)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="hub-scalability-") as temp:
        path = Path(temp) / f"scalability-{args.pages}.pdf"
        anchors = create_pdf(path, args.pages)
        generated = time.perf_counter()
        result = (
            database_pipeline(path, provider, anchors)
            if args.database
            else local_pipeline(path, Path(temp), provider, anchors)
        )
        elapsed = time.perf_counter() - generated
        result.update(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "PASS" if all(item["evidence_found"] for item in result["retrieval_checks"]) else "FAIL",
                "pages": args.pages,
                "pdf_size_bytes": path.stat().st_size,
                "generation_seconds": round(generated - started, 3),
                "ingestion_and_retrieval_seconds": round(elapsed, 3),
                "process_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                "fake_embedding_calls": provider.calls,
                "fake_embedding_inputs": provider.inputs,
                "max_embedding_batch_inputs": provider.max_batch_inputs,
                "max_embedding_batch_tokens": provider.max_batch_tokens,
                "provider": "deterministic hash bag-of-words FAKE; no OpenAI network calls",
                "live_openai_verified": False,
                "environment": {"python": platform.python_version(), "platform": platform.platform()},
                "limitations": [
                    "Synthetic smoke is not representative of every real PDF.",
                    "Peak RSS includes Python, tokenizer and parser baseline; no whole-document text list is retained.",
                    "No live 1000-page OpenAI ingestion was performed.",
                ],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

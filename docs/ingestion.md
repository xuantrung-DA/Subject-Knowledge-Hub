# Ingestion implementation and limits

The original file is stored under an ID path. The API serializes upload decisions
using the owning user/subject row, commits a version and a durable Job, and then
publishes to Celery. Redis is a delivery mechanism. A PostgreSQL job row remains
recoverable if publication fails.

`app.worker.reconcile_loop` runs every 30 seconds in the API and worker parent.
It retries queued jobs and jobs with a stale heartbeat. Each running job holds a
PostgreSQL session advisory lock on a dedicated connection across stage commits;
redelivery cannot process the same job concurrently. Worker process death drops
the lock. A healthy worker with a stale heartbeat retains its lock and is not
force-started a second time. Celery concurrency is one by default.

`app.ingestion.ingest_job` checkpoints physical pages every 10 pages, chunks every
50 chunks, and embeddings every bounded batch. Page/chunk unique constraints and
PostgreSQL conflict handling make replay idempotent. Chunk recovery rescans durable
page rows with keyset pagination but skips ordinals already checkpointed. Embedding
recovery only selects chunks without vectors. Successful responses and vectors are
committed together. A lost response may incur duplicate provider billing on retry;
this system does not promise exactly-once OpenAI execution.

Embedding budgets reserve the worst-case configured retry ceiling before an API
call. On a confirmed response, unused retry reservations are released. When the
provider never supplies a response, the reservation remains charged conservatively.
Actual usage is recorded separately from these budget reservations. Missing prices
do not manufacture a USD estimate. Cache keys include owner, content hash, model
and dimensions. Reusing embeddings does not reuse authorization decisions.

Activation locks the subject then document, checks deletion again, and verifies all
chunks have vectors in one transaction. An older replacement finishing after a
newer version cannot move the active pointer backward. Failed replacements preserve
the existing active pointer. Deletion makes the document ineligible immediately;
even if an in-flight batch writes inactive data, activation cannot resurrect it.
Subject revision is advanced on active-corpus mutation and included in answer-cache
keys by the RAG service.

The parser retains page provenance, extracts one page at a time, and bounds extracted
page text to 300,000 characters by default. This is not a complete defense against
arbitrary PDF decompression bombs; file/page limits and worker time limits are also
necessary. `pypdf` holds the PDF object index in memory. The parser does not retain a
second document-wide text collection. Entirely empty extracted text becomes
`needs_ocr`; mixed files report the number of skipped pages.

Ruled table detection uses `pdfplumber` only for pages with likely drawing operators.
Recognized table blocks are appended to the original page text, preserving original
content at the cost of some duplicate table text. Ordinary-size table blocks are
atomic chunks even above the nominal 600-token target. Tables above the embedding
input limit are divided by rows with repeated headers; exceptionally large individual
rows are split. Unruled tables, images, complex equations and perfect layout recovery
are outside V1. Conservative exact repeated edge detection needs at least five
sampled pages and 80% agreement; matching body lines are preserved.

Offline scalability command, from repository root:

```bash
backend/.venv/bin/python scripts/scalability_smoke.py --pages 1000 --output artifacts/scalability.json
```

This uses a deterministic four-projection signed hash embedding provider **only in
this test script**. It exercises real PDF parsing/chunking, token-bounded batching
and streamed exact vector lookup of facts on pages 1, 500 and 1000. It does not test
PostgreSQL or OpenAI unless the separate database mode is used; database mode still
uses fake embeddings and does not validate live OpenAI.

Real PostgreSQL pipeline smoke after Compose startup:

```bash
docker compose exec api python /app/scripts/scalability_smoke.py --pages 1000 --database --output /app/artifacts/scalability-pg.json
docker compose exec -e RUN_INTEGRATION=1 api python -m pytest tests/test_ingestion_integration.py -q
```

Database smoke creates a clearly named isolated test subject and unusable fixture
login, preserves its rows/PDF for investigation, and prints IDs. It uses the same
`ingest_job` and dense PostgreSQL retrieval functions as the runtime. All live OpenAI
and full-stack restart/browser gates remain separate acceptance checks.

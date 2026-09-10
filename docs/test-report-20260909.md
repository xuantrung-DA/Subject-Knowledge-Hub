# Subject Knowledge Hub — implementation and acceptance report

**Date:** 2026-09-09 (UTC). **Delivery status:** implementation supplied; full-stack and live acceptance **UNVERIFIED**. This report does not label the whole specification complete or the application production-ready.

## Verified results

| Check actually executed | Result | Evidence |
| --- | --- | --- |
| Consolidated backend suite | **PASS: 59; SKIPPED: 22; FAIL: 0**, 2.05 seconds | `artifacts/backend-tests.log`, `artifacts/backend-tests.xml` |
| Frontend TypeScript check | **PASS** | `artifacts/frontend-build.log` |
| Vite production build | **PASS**; JS 398.13 kB / gzip 123.55 kB; CSS 26.32 kB / gzip 6.74 kB | Same log; these are bundle sizes, not browser performance measurements |
| Playwright test discovery | **PASS: 2 tests listed**, execution **UNVERIFIED** | Same log, `frontend/tests/acceptance.spec.ts` |
| PostgreSQL schema/lock SQL compilation | **PASS**, including pgvector, uniqueness, `FOR NO KEY UPDATE` | Backend unit suite and `docs/initial-schema.sql` |
| Alembic offline SQL generation | **PASS**; no database connection or actual migration performed | `artifacts/migration.sql`, `artifacts/migration.log` |
| OpenAPI schema generation and same-origin docs routes | **PASS** | `artifacts/openapi.json`, backend docs endpoint test |
| Compose/Docker/operator static audit | **PASS: 24 static checks**; images/services not executed | `artifacts/operations-static-audit.json` |
| Original fixture dataset | **PASS: 61 questions, 59 evidence locations checked against extracted PDF text** | `fixtures/project/manifest.json`, `backend/tests/test_evaluation.py` |
| 1,000-page parser/chunker/fake-vector smoke | **PASS**, with limits below | `artifacts/scalability.json`, `artifacts/scalability.log` |
| Live smoke CLI dry-run and QASPER/CLI help | **PASS for local command paths**; no paid execution | `scripts/live_smoke.py`, `scripts/qasper.py`, `backend/app/eval_cli.py` |

The 22 skipped tests require real migrated PostgreSQL/pgvector and Redis: 4 core API, 8 ingestion, 7 RAG/tools/summary and 3 evaluation tests. Skipped means **UNVERIFIED**, never PASS. No SQLite substitute was used. The suite emits one non-blocking Starlette/AnyIO deprecated alias warning; its source and stack are in the log.

## Execution environment

- Linux x86_64, kernel 6.18.35, glibc 2.39.
- Python 3.12.14, Node 24.19.0, npm 11.9.0; Docker frontend build specifies Node 22.18.0.
- Python packages installed from `backend/uv.lock`; frontend from `frontend/package-lock.json`.
- Official OpenAI SDK 1.109.1; FastAPI 0.116.1; SQLAlchemy 2.0.43. These are pinned implementation choices, not claims of latest versions.
- **Docker unavailable; no PostgreSQL/Redis server was running.** Native-service provisioning could not complete in this environment. No real migration, vector query, database concurrency or volume restart was exercised.
- **OPENAI_API_KEY absent.** Actual OpenAI requests: **none**. SDK tests use an explicit `httpx.MockTransport` or injected provider only in tests. Runtime has no automatic fake fallback.
- No full application browser session was executed. Playwright source was authored and discovered, not run.
- Package/documentation network access was sufficient for implementation; the QASPER source archive download could not complete. Its real test IDs/archive hash are not present.

## What is implemented

React/TypeScript/Vite UI in Vietnamese; local salted password hashing, HttpOnly sessions and CSRF; subject CRUD and ownership checks; streamed PDF uploads; persistent document versions/jobs; page parser and tokenizer-based chunks; bounded embedding batches/cache; Celery and PostgreSQL job reconciliation; atomic active-version switching; deletion and corpus-revision invalidation; exact scoped pgvector, PostgreSQL lexical search and RRF; Responses API chat/function calling; safe source cards/PDF endpoints; five allowlisted tools; resumable hierarchical summaries; actual usage and optional dated pricing; JSONL evaluation, CLI and JSON/CSV/Markdown export; Docker/CI/backup instructions.

The default retrieval mode is **dense**. Hybrid is selectable but has not been established as superior by a measured live comparison. Original fixtures are a project regression, not an independent benchmark. QASPER uses paragraph evidence, no synthetic PDF page numbers.

## 1,000-page offline evidence

The smoke generated 1,000 distinct short text pages, 720,673 PDF bytes, and 955 chunks. Tokenizer-counted embedding input was 354,500 tokens across 23 **fake** batches (maximum 44 inputs / 15,970 tokens per batch). Measured parser/chunker/fake-embedding/local-retrieval time was **4.473 seconds**; process peak RSS was **175.29 MB**. Generation took 0.279 seconds.

Queries for controlled facts on physical pages **1, 500 and 1000** found the expected pages and values in the top result. This run used streamed exact cosine over deterministic hash vectors; **it did not use PostgreSQL, Redis, Celery or OpenAI**. It is not a semantic retrieval quality measurement or a full ingestion benchmark. It does not establish performance on dense textbooks, scanned PDFs, complex equations or large image-heavy pages.

An earlier test-only hash vector implementation had collisions. The initial failing diagnostic remains in `artifacts/scalability-initial-collision.json`; four signed projections corrected that fixture provider, and the final run above passed. Production OpenAI embeddings were not replaced.

## Specification checklist A — engineering

| Item | Status | Actual evidence and remaining work |
| --- | --- | --- |
| A1 Fresh build/start, all health checks, empty DB migration | **UNVERIFIED** | Frontend build, static Compose validation and offline migration SQL pass. Run real Docker build/start/migration. |
| A2 Accounts, two subjects, every child ownership/tool scope | **UNVERIFIED end-to-end** | Password/CSRF/origin and scoped SQL/schema unit checks pass. Real cross-account database/API/tool tests are included among 22 skipped tests. |
| A3 Upload → ready → PDF/citation, simultaneous dedup | **UNVERIFIED end-to-end** | Bounded upload/hash/cleanup and page provenance units pass. Concurrent DB dedup and real PDF/citation flow need the integration/browser runs. |
| A4 Incremental add, good/bad replacement, deletion and old history/cache | **UNVERIFIED end-to-end** | Version/revision filters and cache-key units pass; database lifecycle tests are written but skipped. |
| A5 Worker restart/replay and commit-before-publish recovery | **UNVERIFIED** | Durable checkpoints/advisory locks/reconciler implemented; crash/queue-failure tests require PostgreSQL. No actual Celery process kill/restart was performed. |
| A6 Corrupt/oversized/encrypted/scan/missing key errors | **PASS at component level; UI/job lifecycle UNVERIFIED** | Actual parser tests, multipart 413 and spool cleanup, format/size checks and missing-key config tests pass. Scan-to-`needs_ocr` job and UI progress require live stack. |
| A7 Provider timeout/429/quota retries | **PASS offline** | Pinned SDK MockTransport: finite timeout/429 retries, quota stops immediately, auth/permission/model classification, budget prevents additional calls, incomplete response is a failure. No live failure injection. |
| A8 Context budget, scope, caches and injection boundaries | **PASS deterministic guards; full pipeline UNVERIFIED** | Tokenizer/model/schema/output/call budgets, scope SQL, argument allowlist, citation ID and revision-key guards pass. Real DB invalidation and model response to injection await integration/live testing. |
| A9 1,000 text pages with facts at three locations | **PASS offline components; pgvector/live UNVERIFIED** | Measured smoke above. Run `--database` separately for actual ingestion/pgvector, then explicit-budget live ingestion separately. |
| A10 Whole-stack restart persistence and no dead-end UI | **UNVERIFIED** | Persistent volumes and saved state paths implemented; source/API contract review fixed docs link and stale source controls. No actual restart/browser acceptance. |

## Specification checklist B — live OpenAI

| Item | Status | How to complete |
| --- | --- | --- |
| B1 Vietnamese + English text PDFs, 10 questions, follow-up/OOS/citations | **UNVERIFIED** | Funded API key + small-budget override + `scripts/live_smoke.py --execute-paid`; review answers/source support. |
| B2 Five representative real function-calling tasks | **UNVERIFIED** | Same HTTP smoke records actual traces/results; check intended tool, scope and completion. New background summaries requested by a tool require user confirmation in UI. |
| B3 Actual model/usage/latency/error report | **UNVERIFIED** | Live report will capture real response usage, errors and configured/returned model. Existing offline metrics are not paid API usage. |
| B4 Live 1,000-page ingestion | **UNVERIFIED** | Separate opt-in upload after estimating tokens/cost; never infer it from the fake smoke. |
| B5 Paid QASPER/large summary benchmark | **NOT RUN / UNVERIFIED** | Separate commands and ceilings in `docs/evaluation.md`; no paid benchmark was started automatically. |

## Specification checklist C — user's browser acceptance

All ten browser steps are **UNVERIFIED in this environment**. The source/UI are supplied, but code inspection and build results cannot substitute for these actions.

| Item | Action to perform | Status |
| --- | --- | --- |
| C1 | Register/login; create and select `Học máy` | **UNVERIFIED** |
| C2 | Upload your own text PDF; reach ready or actionable error | **UNVERIFIED** |
| C3 | Ask a known fact; open source and verify physical page | **UNVERIFIED** |
| C4 | Ask an unsupported fact; verify abstention | **UNVERIFIED** |
| C5 | Add another PDF; verify new facts without rebuilding old docs | **UNVERIFIED** |
| C6 | Switch subjects; verify independent conversation/evidence | **UNVERIFIED** |
| C7 | Replace/delete; verify no stale new-answer evidence/cache | **UNVERIFIED** |
| C8 | Use assistant tools/summary and inspect trace | **UNVERIFIED** |
| C9 | Import/map JSONL, run a small evaluation and export | **UNVERIFIED** |
| C10 | `down` then `up` without `-v`; verify retained state | **UNVERIFIED** |

Detailed Vietnamese instructions: `docs/acceptance_vi.md`. Authored browser tests: `frontend/tests/README.md`.

## Remaining specification gap and measured limits

1. **QASPER actual fixed 100-ID artifact is not materialized.** The downloader/adapter, split, seed, license/attribution and drift checks are implemented. `fixtures/qasper-selection.json` intentionally has null IDs/hash because the source could not be downloaded. Run the download command to obtain real IDs and archive/test/corpus hashes before claiming the subset supplied or benchmarked. Synthetic adapter tests do not fill this gap.
2. Docker fresh start, database transactions/concurrency, Celery restart, Nginx behavior, browser rendering/interactions and backup/restore have not been exercised. Integration sources are concrete but may expose additional defects when first executed.
3. Citation validity is mechanical, not proof that each claim is supported. Answer token F1 and refusal heuristics are limited proxies. Semantic correctness, claim support and faithfulness have not been measured; no paid judge is bundled or silently invoked.
4. PDF OCR, image understanding, complex formula understanding and perfect table reconstruction are outside V1. The parser preserves detected bounded tables; huge text streams/tables return explicit guards rather than allowing unbounded requests.
5. Source/summary soft deletion removes evidence from new retrieval; historical versions/bytes are retained internally. Do not interpret logical deletion as forensic erasure from backups/volumes.
6. Exact vector search favors filtering correctness for a local collection; no high-concurrency or large-corpus SLA has been established. The measured 1,000-page case contains short synthetic pages.
7. A provider timeout/crash can repeat a charged call. Durable reservations bound retries but cannot guarantee exactly-once billing or recover usage the provider never returned. Cost remains unknown without dated configured prices.

## Exact commands to finish verification

From the extracted `subject-knowledge-hub` directory, PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
# Set OPENAI_API_KEY, save, then:
docker compose up --build -d
docker compose ps -a
```

Bash/WSL uses `cp .env.example .env`. Open `http://localhost:3000`; Swagger is `http://localhost:8000/docs`. Register, create/select your subject, upload a text PDF and use the Vietnamese acceptance guide. Migration should exit zero; the five long-running services should become healthy.

Run the deterministic database gates against a **separate disposable project**:

```bash
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --build --rm tests
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --rm tests python scripts/scalability_smoke.py --pages 1000 --database --output /app/artifacts/scalability-pg.json
```

To retain test artifacts, add a writable bind mount such as `-v ./artifacts:/app/artifacts` before `tests`; otherwise files in a removed one-off container do not persist. See README for the explicitly destructive cleanup of **only the disposable test project**.

Run browser tests from `frontend/` after the real stack is ready:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

The default browser test uses corrupt/empty fixtures and no model calls. The second paid test stays skipped unless explicitly enabled as documented in `frontend/tests/README.md`.

Run the separate real API smoke only after checking its budget:

```bash
docker compose exec api python scripts/live_smoke.py
docker compose -f compose.yaml -f compose.live-smoke.yaml up -d --force-recreate api worker
docker compose exec -e HUB_EMAIL=you@example.com api python scripts/live_smoke.py --execute-paid
docker compose cp api:/app/artifacts/live-smoke.json artifacts/live-smoke.json
```

The HTTP script requests the existing account password privately, creates an isolated visible subject, uploads the two fixtures, and attempts 10 questions plus 5 tool tasks. At the supplied settings it reserves a maximum planned envelope of **170,000 tokens** (two ingestion ceilings of 25,000 plus fifteen question ceilings of 8,000) within its default 200,000-token cap. This is a conservative ceiling, **not an estimate of actual billed usage**; final report distinguishes actual returned tokens, reservations and errors. It will refuse ordinary larger settings without the override. New summaries requested by tools return confirmation instead of creating unbudgeted background charges. Restore normal settings with `docker compose up -d --force-recreate api worker` afterward.

QASPER and evaluation commands: `docs/evaluation.md`. Backup/restore commands: README. Stop/start for persistence testing uses `docker compose down` and `docker compose up -d`, **without `-v`**.

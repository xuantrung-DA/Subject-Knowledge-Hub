# Executed verification — 2026-09-10

Publication follow-up: [cleanup, dependency patches and rerun checks](publication-review.md). Historical paid measurements below belong to the implementation snapshot.

The local application and portfolio measurements have been exercised. The former report with 59 passes/22 skips is preserved as [2026-09-09 history](test-report-20260909.md); its UNVERIFIED labels describe that earlier environment.

Application on this Windows workspace: **http://127.0.0.1:13000**. API docs: **http://127.0.0.1:18000/api/docs**. Fresh installations use `.env.example` defaults 3000/8000 unless changed. The runtime uses real OpenAI; keys remain in the ignored `.env`.

## Executed checks

| Check | Measured outcome | Evidence |
| --- | --- | --- |
| Initial real database baseline | 81 passed, including all 22 previously skipped integration tests | [JUnit](../artifacts/runs/20260910-implementation/backend-baseline.xml) |
| Backend on final release image | 90 passed in 6.15 s: 65 unit/contract cases and 25 real PostgreSQL/Redis integration cases, no skips/failures | [JUnit](../artifacts/runs/20260910-implementation/backend-release.xml) |
| Frontend typecheck/build | Pass; production JS 399.23 kB / gzip 123.85 kB | [Docker build log](../artifacts/runs/20260910-implementation/final-release-build.log) |
| Actual Chromium application tests | 2 passed in 35.3 s | [Run log](../artifacts/runs/20260910-implementation/browser-final.log), [test source](../frontend/tests/acceptance.spec.ts) |
| OpenAI HTTP smoke | 2 PDF ingestions, 10 questions and five tool selections completed; content review limitations below | [JSON](../artifacts/runs/20260910-implementation/live-smoke.json) |
| Tool follow-up after prompt repair | Page reading returns cited contents; summary tool preserves explicit UI confirmation | [JSON](../artifacts/runs/20260910-implementation/tool-followup.json) |
| Worker process interruption | 3/3 recovered via reconciler; no duplicate chunks or repeated committed batch | [Recovery proof](../artifacts/runs/20260910-implementation/recovery.json) |
| 1,000-page PostgreSQL pipeline, fixture embeddings | Pass; 1,000 pages/chunks, 9.977 s, 239.59 MiB process RSS | [JSON](../artifacts/runs/20260910-implementation/scalability-1000-postgres.json) |
| 1,000 pages with OpenAI + incremental upload | Pass; 41.013 s ingestion/retrieval, three correct cited anchor answers; adding three pages used one new embedding batch | [JSON](../artifacts/runs/20260910-implementation/live-scalability-1000.json) |
| Synthetic portfolio benchmark | Final dev 30/30 and test 70/70 completed for each strategy; 25.3% fewer input tokens on held-out | [Comparison](../artifacts/runs/20260910-implementation/comparison.json) |
| QASPER external retrieval | 100 questions × three modes completed, 95 papers indexed, real embeddings | [Result](../artifacts/runs/20260910-implementation/qasper.json) |
| Synthetic PDF ground truth | All 50 page bodies and pinned file hashes verified | [JSON](../artifacts/runs/20260910-implementation/portfolio-pdf-validation.json) |
| Backup and fresh-project restore | 17 table fingerprints and 35 PDF SHA256 values match; five restored services healthy | [Comparison](../artifacts/runs/20260910-implementation/backup-restore.json), [restore log](../artifacts/runs/20260910-implementation/restore.log) |

Backend integration uses actual PostgreSQL/pgvector and Redis, with explicitly injected test providers where appropriate. It does not pretend all 90 tests call OpenAI. The separate live runs above do. A Starlette/AnyIO deprecated-alias warning remains; tests pass with it. PowerShell may render native stderr progress output as `NativeCommandError` in captured logs; JUnit and structured run statuses distinguish actual failures.

## Changes validated

- New PDF ingestion preserves physical page boundaries. The strategy is stored in checkpoints so a restart/configuration change cannot change chunk ordinals midway through a job. Existing historical versions remain readable.
- Summary jobs expose source name, version, page range and current/replaced/deleted state. The UI preserves historical summaries and marks stale sources. The backend rejects retrying a summary against a replaced version.
- Evaluation UI and CLI use the server top-k limit; UI mapping also includes paragraph-corpus targets named only in metadata. The server independently validates the limit.
- Evaluation generation no longer performs a redundant retrieval/embedding before the answer pipeline's own retrieval. Reference answers remain outside prompts and indexes.
- The concise prompt prevents the observed dev introduction truncations and gives cited contents when asked to read pages. A summary requiring confirmation points to the document UI.
- Refusal detection recognizes more Vietnamese/English forms but is still explicitly a lexical proxy.
- Configurable host ports allow startup beside another application. README API docs links and existing `.env` handling were corrected.
- CI now includes an offline browser run against the full stack; a manual workflow exercises process recovery and scale. These workflow definitions were added locally; no remote CI run or deployment is claimed.

The two browser tests cover registration, CSRF/session use, cross-user ownership denial, subject/conversation isolation, invalid uploads, persistence after reload, mobile layout, evaluation top-k/import, real PDF processing/dedup, cited answer/PDF page navigation, evaluation export, summary completion, unsuccessful/successful replacement, and historical summary labeling after deletion.

## Quality boundaries

Synthetic held-out page Recall@6 was 100% on 56 answerable cases, while external QASPER paragraph Recall@6 was 58.35% on 96 answerable cases. These are different corpora and evidence units. Neither number means general answer accuracy.

Three false refusals remained among upgraded held-out answerable questions. An assistant reviewed the synthetic answers; independent human correctness/claim-support grading remains unfinished. Exact-page source navigation is verified mechanically; universal claim support is not asserted. [Full results and limitations](benchmark-report.md) include the lower MRR and failed lexical baseline.

Real scale testing used a project-owned synthetic PDF. Celery crash recovery used deterministic fixture embeddings and a ten-second stale threshold; the ordinary default is 180 seconds. These are controlled local tests, not arbitrary-PDF guarantees, production concurrency tests, uptime measurements, or service-level commitments.

## Evidence and reproduction

All new evidence lives under `artifacts/runs/20260910-implementation/`. Exploratory failures are retained beside final results. [The benchmark report](benchmark-report.md) records the fixed corpus, settings, commands and CV claims.

Final runtime evidence: [service health](../artifacts/runs/20260910-implementation/final-services.json), [HTTP checks](../artifacts/runs/20260910-implementation/final-http-health.json), and [host environment and dependency lock hashes](../artifacts/runs/20260910-implementation/environment-host.json). The [source manifest](../SOURCE_MANIFEST.json) fingerprints this delivery; the original manifest remains archived separately.

```powershell
docker compose up --build -d --wait
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --build --rm tests
```

Use the isolated test project for deterministic/recovery runs. Paid browser/benchmark scripts require explicit opt-in and the documented caps. `scripts/backup.py --project-name <source>` and `scripts/restore.py --project-name <new-target> --replace-data` select a project explicitly; use separate free ports for a restore rehearsal.

The complete implementation/test effort recorded approximately **$0.284791** in estimated OpenAI usage cost against the user's **$10 maximum**. [Usage snapshot](../artifacts/runs/20260910-implementation/pre-backup-quiesced.json). No key is included in the artifacts or frontend.

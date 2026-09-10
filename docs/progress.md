# Portfolio implementation checkpoint

Publication follow-up: [cleanup, dependency patches and rerun checks](publication-review.md). Historical paid measurements below belong to the implementation snapshot.

Updated 2026-09-10. The local application runs at http://127.0.0.1:13000 on the verified workspace. Docker/Compose startup, migrations, real PostgreSQL/Redis tests, Chromium flows, OpenAI, worker interruption, and backup/restore have been exercised.

- 90 backend cases pass, including 25 database integration cases; two actual browser flows pass.
- Page-boundary chunking, durable strategy checkpoints, historical summary source states, configurable ports, and evaluation top-k/measurement fixes are implemented.
- Paired frozen held-out benchmark: 25.3% fewer provider input tokens on 70 synthetic bilingual questions, unchanged 100% page Recall@6 on 56 answerable cases. MRR decreased; three false refusals remain.
- Live 1,000-page ingestion/retrieval: 41.013 seconds, 263.89 MiB process peak RSS; incremental three-page PDF uses one new embedding batch.
- Three real Celery process-kill trials recover without duplicate chunks. Restore into a fresh project matches every database table fingerprint and all 35 PDFs.
- QASPER now has 100 actual IDs/source hashes and an executed live-embedding retrieval run: dense/hybrid Recall@6 58.35% on 96 answerable cases. No QASPER generation claim.
- CI definitions include the actual-stack browser smoke and manual reliability gates. They have not been run on a remote CI service in this workspace.
- Total recorded API cost is approximately $0.285 of the authorized $10.

Delivered: [test report](test-report.md), [benchmark report](benchmark-report.md), [three CV statements](cv-results.md), reproducible scripts, fixed fixture manifests and raw run evidence. Independent human claim-support review, improved natural-language lexical retrieval, public hosting, production load/uptime validation and OCR remain outside the verified claims.

Historical source delivery evidence: [2026-09-09 report](test-report-20260909.md) and [original manifest](../artifacts/source-manifest-20260909.json). The root `SOURCE_MANIFEST.json` and the new run's `source-manifest.json` identify the upgraded source.

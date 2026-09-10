# CV statements backed by this run

Use the statements below with their scope intact. Evidence and limitations: [benchmark report](benchmark-report.md).

- **Reduced RAG provider input tokens by 25.3% on 70 held-out synthetic Vietnamese/English QA cases while maintaining 100% page-evidence Recall@6 on 56 answerable cases.**
- **Processed a 1,000-page synthetic PDF into 1,000 pgvector chunks using real OpenAI embeddings in 41 seconds with ~264 MiB peak process memory; added a three-page PDF with one embedding batch and no reindexing of existing chunks.**
- **Implemented resumable Celery ingestion with PostgreSQL checkpoints and advisory locks, recovering 3/3 interrupted jobs in 10.6–11.1 seconds without duplicate chunks in controlled process-kill tests.**

For a short CV, use the first two bullets and mention recovery when discussing architecture. Supporting artifacts: [paired token comparison](../artifacts/runs/20260910-implementation/comparison.json), [live scale/incremental test](../artifacts/runs/20260910-implementation/live-scalability-1000.json), [recovery trials](../artifacts/runs/20260910-implementation/recovery.json).

Keep these qualifications when interviewed:

- The 70 questions use seven synthetic runbooks and repeated templates; there is no claim of 100% general answer accuracy. External QASPER retrieval achieved 58.35% Recall@6 on 96 answerable examples within a fixed 100-question subset.
- The 41-second measurement includes ingestion and three retrieval checks. Memory is the measurement process's RSS, not total stack RAM. Real Celery process recovery was tested separately with fixture embeddings and a ten-second stale threshold.
- Page-boundary chunking improved context precision and token use but reduced MRR. Some false refusals remain. Independent human claim-support grading is unfinished.
- These are local measurements, not production SLAs, concurrent-user load claims, or cloud latency guarantees.

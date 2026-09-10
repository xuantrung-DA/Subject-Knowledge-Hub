# Portfolio benchmark — 2026-09-10

The page-boundary upgrade reduced provider input tokens **25.3%** on a frozen, paired 70-question synthetic Vietnamese/English test. Both configurations retrieved all expected pages on the 56 answerable cases. The separate external QASPER experiment reached **58.35%** evidence Recall@6: the synthetic result does not establish general RAG accuracy.

These measurements belong to the pre-publication implementation snapshot. Subsequent dependency patches and verification are recorded separately in [publication review](publication-review.md); the latency/AI comparison was not rerun on the updated dependency set.

All measurements below were executed locally. Raw evidence: [run directory](../artifacts/runs/20260910-implementation/), [paired comparison](../artifacts/runs/20260910-implementation/comparison.json), [CV wording](cv-results.md).

## Paired experiment

Ten original fictional runbooks contain 50 PDF pages and 100 templated questions: 30 dev questions from three documents and 70 test questions from seven different documents. All questions/facts from a document stay together. The [manifest](../fixtures/portfolio/manifest.json) pins hashes and IDs; [PDF validation](../artifacts/runs/20260910-implementation/portfolio-pdf-validation.json) verified all 50 source page bodies through PDF extraction. Labels were AI-authored; there has been no independent human validation.

[Registered experiment](../artifacts/runs/20260910-implementation/experiment-plan.json): change only whether short PDF pages can merge into a chunk. [Frozen configuration](../artifacts/runs/20260910-implementation/frozen-config.json): dense retrieval, top-k 6, 20 candidates, 600-token chunks/80-token overlap, 1,800-token context, 400-token history, 350-token output, GPT-4.1 mini, text-embedding-3-small/1536 dimensions. Answer and query caches are disabled during measurement. Both final configurations use the same concise prompt and evaluation fixes.

| Held-out measurement | Cross-page baseline | Page boundaries |
| --- | ---: | ---: |
| Completed questions / errors | 70 / 0 | 70 / 0 |
| Page evidence Recall@6, 56 answerable | 100% | 100% |
| Page evidence precision@6 | 7.14% | 20.83% |
| MRR | 1.0000 | 0.9256 |
| Provider input tokens, total | 175,262 | 130,947 |
| Input tokens / evaluated question | 2,503.7 | 1,870.7 |
| Output tokens, total | 4,613 | 4,227 |
| Estimated QA cost | $0.07693 | $0.05859 |
| Latency p50 | 1.967 s | 1.932 s |
| Latency p95 | 5.478 s | 4.575 s |
| False refusals flagged by backend, answerable | 5/56 | 3/56 |
| Refusal phrase proxy, unanswerable | 14/14 | 13/14 |

Input tokens include query embeddings and generated earlier turns for follow-up questions. The new configuration reduced estimated QA cost 23.8%. These timings measure the production job/RAG functions including provider calls, not browser round trips. One sequential run per configuration was performed; cloud timing and model outputs vary. Do not infer a latency guarantee from these 70 samples.

The precision increase and lower MRR reflect the change in evidence granularity: the baseline can return an entire five-page runbook as one first-ranked chunk. The upgrade supplies specific pages and makes the browser open the supporting physical page. Recall@6 counts page coverage; it is not answer correctness.

## Quality review and failures

The initial dev run found output truncation in broad introductions. Concise-answer guidance was applied equally to both configurations, and both 30-question dev runs then completed without errors. Evaluation previously performed an extra retrieval before calling the RAG answer function; that duplicate query was removed and covered by a regression test before the final comparison.

On held-out data the upgraded system still falsely refused `maple-06`, `maple-08`, and `birch-07`, despite the expected evidence being retrieved. These cases are retained. The refusal phrase heuristic missed the correct Vietnamese abstention in `cuc-09`. No configuration was tuned from these held-out results.

An [assistant content review](../artifacts/runs/20260910-implementation/assistant-content-review.json) read all 70 upgraded answers and found 53/56 answerable responses correct and complete, plus 14/14 correct abstentions. This is **not independent human grading**; the reviewer also authored the synthetic material. [The human review CSV](../artifacts/runs/20260910-implementation/content-review.csv) remains ungraded. Mechanical citation validity was 100% where citations occurred; claim-by-claim support was not exhaustively graded and is not claimed as 100%.

## External retrieval check: QASPER

The fixed [100 official IDs and hashes](../fixtures/qasper-selection.json) cover 95 papers, represented as 4,674 paragraph chunks. Source: [Ai2 QASPER dataset card](https://huggingface.co/datasets/allenai/qasper), CC-BY-4.0; attribution and source hash are in the manifest. Selection excludes annotation disagreement and evidence that cannot map exactly to text paragraphs. No tuning was done on this subset.

| Mode | Queries | Answerable denominator | Paragraph Recall@6 | MRR | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lexical | 100 | 96 | 0% | 0 | 0 |
| Dense | 100 | 96 | 58.35% | 0.4946 | 0 |
| Hybrid | 100 | 96 | 58.35% | 0.4946 | 0 |

[Result and configuration](../artifacts/runs/20260910-implementation/qasper.json), [per-query evidence](../artifacts/runs/20260910-implementation/qasper-results.json). This run used real embeddings, paper-scoped retrieval, a 4,500-token context cap, and **no answer generation**. It does not measure PDF extraction, Vietnamese, or full official QASPER performance. Indexing plus retrieval cost approximately $0.00897.

The current PostgreSQL `simple` lexical query requires all query terms and failed to match these natural-language questions. Hybrid consequently behaved like dense. Better lexical query construction/reranking needs a separate development experiment; these zero scores are preserved rather than used as an inflated CV comparison.

## Scale, incremental indexing, and recovery

- [Live 1,000-page run](../artifacts/runs/20260910-implementation/live-scalability-1000.json): 1,000 persisted pages/chunks; ingestion plus three retrieval checks took **41.013 s**, peak measurement-process RSS **263.89 MiB**. Real OpenAI embeddings and RAG answers found the expected facts on pages 1, 500 and 1,000. Cost including three answers and the incremental check: approximately **$0.00910**.
- Adding a three-page PDF took **0.893 s** and one embedding call for three new inputs. All original 1,000 chunk IDs remained; the original ingestion job recorded zero new usage events. This proves incremental behavior for this controlled workload.
- [Offline database scale run](../artifacts/runs/20260910-implementation/scalability-1000-postgres.json): 1,000 pages/chunks in 9.977 s and 239.59 MiB RSS with deterministic fake embeddings. This result is separate from live performance.
- [Real Celery process recovery](../artifacts/runs/20260910-implementation/recovery.json): **3/3** jobs recovered after SIGKILL during the second embedding batch; **10.557–11.067 s**, 32 pages per trial, no duplicate chunks, eight committed embeddings preserved each time. Embeddings were explicit fixtures; real PostgreSQL/Redis/Celery processes ran. Stale detection was set to ten seconds for the experiment; the ordinary application default is 180 seconds.
- [Backup/restore](../artifacts/runs/20260910-implementation/backup-restore.json): all **17 table fingerprints** (including Alembic metadata) and **35 PDF SHA256 hashes** matched after restoring into a new Compose project. Five restored services became healthy.

The scale corpus is synthetic and the measured RSS belongs to the measurement process, not the whole Docker stack. Scale scripts invoke production ingestion functions directly; Celery process reliability is measured by the separate fault-injection test.

## Reproduce

Run a fresh build with the locked dependencies. Generated benchmark scripts require the backend image. Set your own key in `.env`; paid scripts default to dry-run and require `--execute-paid`. Retain a writable artifact mount and use a new output directory to avoid overwriting evidence.

```powershell
docker compose -f compose.yaml -f compose.live-smoke.yaml up --build -d
# Create a NEW local artifact folder and mount it at /app/artifacts.
# Run each strategy on dev first, inspect it, freeze configuration, then run test.
docker compose -f compose.yaml -f compose.live-smoke.yaml run --rm --no-deps -v D:/subject-knowledge-hub/artifacts/runs/reproduce:/app/artifacts api python scripts/portfolio_benchmark.py --strategy baseline --split dev --execute-paid --output-dir /app/artifacts/portfolio-final
```

Repeat with `--strategy page`, then `--split test` for both frozen strategies. `scripts/benchmark_summary.py --run-dir <host-run-directory>` computes paired totals and exports the human review form. The corpus and previous run state are reused within an artifact directory. Generation includes earlier turns from the corpus, never reference answers.

For normal ingestion limits, run `docker compose up -d --force-recreate api worker`. `scripts/live_scalability.py`, `scripts/qasper_benchmark.py`, `scripts/recovery_probe.py`, and `scripts/state_snapshot.py` provide the other measured procedures; their `--help` and the [test report](test-report.md) specify scope. Recreate QASPER with `python scripts/qasper.py --manifest fixtures/qasper-selection.json` before indexing.

The [pre-backup usage snapshot](../artifacts/runs/20260910-implementation/pre-backup-quiesced.json) records **$0.284791** estimated provider cost for the entire implementation/testing effort, including exploratory and failed-output dev calls, browser tests, both comparisons, tools, scale and QASPER. This is below the authorized **$10** limit. Prices were verified against [OpenAI's pricing documentation](https://developers.openai.com/api/docs/pricing) on 2026-09-10; usage-based estimates are not invoices.

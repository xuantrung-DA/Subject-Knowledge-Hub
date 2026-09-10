# Evaluation and regression

This repository supplies runnable evaluation infrastructure, original regression corpora, a completed controlled OpenAI comparison, and an external QASPER retrieval run. It does not claim expert-reviewed answer quality or general 100% accuracy. Current results are in [benchmark-report.md](benchmark-report.md) and [test-report.md](test-report.md).

## Data supplied

`fixtures/portfolio/` adds ten original bilingual runbooks, 50 PDF pages and 100 templated questions, split by document into 30 dev and 70 held-out. Hashes, authorship, scope and limitations are pinned in its manifest. The [registered/frozen experiment and results](benchmark-report.md) compare cross-page chunks with page-preserving chunks under the same context budget. This synthetic set complements the original 61-question regression below; it is not an independent real-world sample.

`fixtures/project/regression.jsonl` contains **61** questions. The four base documents are `fixture_vi.pdf` (6 pages), `fixture_en.pdf` (6 pages), `conflict.pdf` (1 page), and `injection.pdf` (1 page). They contain original synthetic facts in Vietnamese and English. Questions include paraphrases, follow-ups, two-document reasoning, contradictory capacity rules, out-of-scope requests, and untrusted instructions inside a PDF. Golden answers are never inserted into the document index or the generation prompt.

The generator and unit suite check **59 evidence locations** against actual `pypdf` text extraction. Explicit quotes must occur on the declared physical pages. This verifies fixture provenance; it is not external semantic review. Synthetic fixture content is dedicated under CC0-1.0. The manifest stores document and dataset SHA256 hashes.

`small_eval.jsonl` is a three-question starting set. `lifecycle.json` describes adding `new_document.pdf`, replacing with `replacement.pdf`, failing a replacement with `corrupt.pdf`, and deleting `temporary.pdf`. Run these on a fresh fixture subject. A lifecycle operation changes corpus revision: import its associated question *after* the action, or an old evaluation correctly fails as stale. Operational integration tests separately exercise active versions, deletion, cache and ownership. The lifecycle descriptor alone is not a claim that browser lifecycle checks ran.

Additional parser fixtures include empty, corrupt, encrypted, mixed text/blank, and blank scan-only PDFs. The scan-only fixture deliberately contains no extractable text; it does not measure OCR. Generate a thousand distinct short text pages when needed:

```bash
docker compose exec api python scripts/fixtures.py --large
```

The thousand-page smoke has unique observation IDs and known facts at physical pages 1, 500 and 1000. This tests a controlled scale case; it does not represent every dense textbook, malformed PDF, formula layout, or scanned document. Ingestion duration and peak process memory belong to the scalability smoke report, not the answer-quality report.

## JSONL schema

Each line is an independent JSON object:

```json
{"id":"mine-001","question":"What is the split seed?","reference_answer":"42","answerable":true,"evidence":[{"document_key":"my_notes","page_start":3,"page_end":3,"quote":"The split seed is 42."}],"tags":["en","single_document"]}
```

Use physical PDF page numbers, starting at one. Optional `history` contains previous **user questions only**; previous answers are generated from the corpus, never taken from references. `reference_answers` permits alternative golden wordings. An answerable row needs evidence or an expected operational tool. Optional `expected_tools` lists names from the five supported functions and `chat_mode: "assistant"` enables real model tool selection. For `get_job_status`, use a real current job ID in the question. Dataset import is limited to 10 MB and 500 unique question IDs, rejects unknown top-level fields and invalid page ranges, and checks mapping ownership, active version, page bounds, and any evidence quote.

In the evaluation tab choose a subject and import the JSONL. Map document keys to actual document IDs using `{ "my_notes": "document-uuid" }`; the UI offers current documents. CLI fixture imports set keys automatically. An explicit `{ "document_id": "...", "version_id": "..." }` value can pin a version, but it must be active. The resolved mapping always records the active version. A later corpus change causes a clear failure and requires importing a new run.

## Start with a small comparison

These commands work in Bash/WSL and PowerShell without `make`. Replace the sample email, `SUBJECT_ID`, and `RUN_ID` with actual values. The CLI is an administrator operation inside the container; register the account in the browser first. It does not bypass HTTP authentication from an external client.

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import-fixtures
```

This creates a separate fixture subject, streams the four original PDFs through the **same upload and ingestion path** used by the UI, and prints document/job IDs. Wait until all four documents are ready in the browser. Reuse `--subject-id SUBJECT_ID` to avoid creating another subject on a repeated import; same-file deduplication applies.

A lexical-only retrieval comparison uses no OpenAI calls *during evaluation*, provided the documents have already been indexed:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import --subject-id SUBJECT_ID --dataset /app/fixtures/project/small_eval.jsonl --modes lexical --limit 3
docker compose exec api python -m app.eval_cli --email you@example.com run --run-id RUN_ID
docker compose exec api python -m app.eval_cli --email you@example.com status --run-id RUN_ID
```

For an explicitly paid three-mode, three-question answer comparison, import another run with a bounded aggregate allowance:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import --subject-id SUBJECT_ID --dataset /app/fixtures/project/small_eval.jsonl --modes lexical,dense,hybrid --answers --limit 3 --max-tokens 150000 --max-calls 100
```

Then use the same `run` and `status` commands with its new ID. The aggregate budget reserves actual input payloads, tool schemas and maximum output **before every HTTP attempt**, including retries. Counters persist in the job checkpoint and survive worker replay. Reserved output may exceed actual returned tokens; both are reported separately. A budget failure keeps a partial export. Failed/unknown provider usage is not called zero cost. A model timeout may already have incurred charges at the provider.

All three modes share dataset, chat model, prompts, top-k, context/history/output budgets, and corpus revision. Exact-answer caching is disabled for answer comparisons. Query embedding cache hits remain visible and can affect latency; do not claim a cold-cache performance comparison. Lexical mode uses PostgreSQL full-text search with `simple` configuration, **not BM25**. No measured ranking result has established a winning default in the supplied environment; dense is the default baseline and hybrid remains selectable pending your own evaluation.

Export the actual completed or partial report:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com export --run-id RUN_ID --format json --output /app/artifacts/evaluation.json
docker compose exec api python -m app.eval_cli --email you@example.com export --run-id RUN_ID --format csv --output /app/artifacts/evaluation.csv
docker compose exec api python -m app.eval_cli --email you@example.com export --run-id RUN_ID --format md --output /app/artifacts/evaluation.md
docker compose cp api:/app/artifacts/evaluation.json ./evaluation.json
docker compose cp api:/app/artifacts/evaluation.csv ./evaluation.csv
docker compose cp api:/app/artifacts/evaluation.md ./evaluation.md
```

Alternatively use the evaluation tab's authenticated export buttons. The PostgreSQL run/results are durable; generated files under `/app/artifacts` should be copied out before rebuilding the container.

## Metric definitions

| Metric | Definition and limit |
|---|---|
| Evidence Recall@k | Fraction of distinct golden `(document, active version, physical page)` units covered by the selected top-k chunks; QASPER uses original paragraph IDs instead. Multiple chunks on the same page do not increase recall. |
| Evidence precision@k | Golden units among all distinct units covered by returned chunks. A cross-page chunk contributes every recorded page, so page-level precision is deliberately coarse. |
| MRR | Reciprocal rank of the first retrieved chunk covering any golden evidence unit. Null when a question has no golden evidence. |
| Answer token F1 | Unicode-normalized, case-insensitive token overlap with the reference; maximum over alternatives. This is a **lexical correctness proxy**, not semantic relevance, semantic correctness, or faithfulness. |
| Unanswerable accuracy | Fraction of unanswerable rows triggering a documented refusal text heuristic. Requires manual review; answerable rows are excluded from this denominator. |
| Citation validity | Citation location and source identity match an actual source supplied to the model. Marker validity additionally checks bracket IDs. These checks do not establish that the cited passage supports a claim. |
| Citation content support / faithfulness | **Unmeasured (null)**. Inspect answer and evidence samples manually. No paid judge or Ragas run is implied. Faithfulness would measure consistency with supplied context, not absolute truth. |
| Tool selection recall | Required tool names that appear in the real model tool trace. Tool error rate counts failed tool calls. This does not alone prove successful task completion. |
| Tool scope / task completion | **Unmeasured in generic answer scoring**. Verify the deterministic authorization/error/round-limit tests and live task outcomes separately. |
| Latency p50/p95 | Interpolated quantiles of successful per-question elapsed time, including follow-up generation and retrieval. Report sample count; fewer than 20 successful samples are flagged as insufficient for reliable performance conclusions. |
| Usage | Actual provider-reported input/output/cached tokens, retries, embedding/generation events and cache hits. Cost is null unless a dated model price configuration covers every event. |

Reports include dataset SHA256, configuration, environment, available Git revision, per-question errors, supplied context, answer/citation snippets, tool trace, actual usage, and conservative budget reservations. Review false answers with valid citations; mechanical validity is a separate property from claim support.

## QASPER fixed test subset

Official sources checked during implementation: [QASPER dataset card](https://huggingface.co/datasets/allenai/qasper), [official adapter with original v0.3 archives](https://huggingface.co/datasets/allenai/qasper/raw/main/qasper.py), and [dataset paper](https://aclanthology.org/2021.naacl-main.365/). The card identifies **CC BY 4.0** and original paragraph evidence; upstream figures/tables may have `FLOAT SELECTED` evidence. Attribution is included in the generated manifest.

**Executed on 2026-09-10:** `fixtures/qasper-selection.json` now pins 100 actual official IDs and source SHA256 `72a52a41193e2838b8074f80ac074b94f956b84886c36a61c58a7df4171bdd72`. A separate collection indexed 95 papers / 4,674 paragraph chunks with real embeddings. All 100 queries ran for lexical/dense/hybrid; dense and hybrid achieved 58.35% paragraph Recall@6 on 96 answerable examples. No answers were generated. The downloaded source/corpus remains in ignored `artifacts/qasper/`; the tracked manifest plus downloader reproduces it. [Raw run](../artifacts/runs/20260910-implementation/qasper.json), [limitations](benchmark-report.md).

Download and materialize the exact subset on a machine with internet access:

```bash
docker compose exec api python scripts/qasper.py --output /app/artifacts/qasper
```

When outbound access is unavailable, download the official v0.3 test TGZ separately, copy it into the container, and pass `--source /app/artifacts/qasper-test-and-evaluator-v0.3.tgz`. The script reads only the expected JSON member without extracting arbitrary archive paths.

The split is `test`, seed is `20260909`, and selection is the lowest SHA256 ranks of `seed:official_question_id` among eligible questions, exactly 100 without replacement. Eligibility requires unanimous annotation answerability and exact textual evidence mapping; non-textual/unmapped evidence is excluded and counted. This creates a **filtered test subset, not the full official benchmark**. It writes the real IDs, source archive SHA256, corpus/test SHA256, paper IDs, license and exclusions into `manifest.json`; subsequent execution refuses source/ID drift. Keep that manifest with exported results. Use upstream train/dev for tuning; do not tune on these fixed test questions.

Preview corpus embedding cost/token estimates before starting paid ingestion:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import-qasper --directory /app/artifacts/qasper
```

Then explicitly confirm:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import-qasper --directory /app/artifacts/qasper --confirm
```

This creates a **separate paragraph-only subject**, prints its ID, respects bounded job admission, and enqueues durable ordinary ingestion jobs with pre-parsed/pre-chunked checkpoints. The same chunking, embedding batch/cache, activation, retrieval, and answer code runs. It does not create PDFs or assign fake physical pages. Evidence is `paper_id:section:paragraph` and citations have null page fields; PDF viewing and PDF page tools do not apply. `--subject-id SUBJECT_ID` resumes an interrupted import; existing mapped documents are retained. Wait for all document jobs to finish before importing the dataset:

```bash
docker compose exec api python -m app.eval_cli --email you@example.com import --subject-id SUBJECT_ID --dataset /app/artifacts/qasper/test100.jsonl --modes lexical,dense,hybrid --limit 100 --max-tokens 200000 --max-calls 400
```

This command imports a retrieval evaluation but does not start it; use `run` explicitly. Adding `--answers` enables paid generation and may require a larger budget after estimating your model costs. QASPER metadata records the target paper, and evaluation constrains retrieval to that owned active document in SQL before ranking; it uses the same internal filtering path as the application. Questions/answers/evidence remain in the evaluation resource, not the corpus. QASPER measures English paper QA; these runs do **not** validate PDF parsing, Vietnamese quality, or the full application UI.

## Verification commands

```bash
docker compose exec api python -m pytest tests/test_evaluation.py -q
docker compose -p subject-hub-test -f compose.yaml -f compose.test.yaml run --build --rm tests python -m pytest tests/test_evaluation_integration.py -q
```

The deterministic suite checks dataset validation, exact PDF quote locations, page/paragraph metric separation, citation membership versus unmeasured support, budget failure/replay, exports and CSV formula escaping, fixed QASPER selection, and exclusion of golden answers from the corpus. The integration suite requires real migrated PostgreSQL/pgvector and checks persistent lexical jobs with no key, retry idempotency, ownership, corpus-revision failure and reference isolation. Skipped integration tests are **UNVERIFIED**, not PASS. Live HTTP smoke commands and measured or unverified acceptance status are in the README and test report.

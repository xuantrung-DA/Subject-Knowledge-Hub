# Evaluation: baseline test answers

Run `39285595-7515-45ec-808f-1cd27b4bc3fa` — **ready**

## Configuration and provenance

```json
{
  "dataset_sha256": "e6bc877e581eac2ba5999a3a12646f8391e4ea28a5a039276f226d1611a3ae6b",
  "question_count": 70,
  "config": {
    "modes": [
      "dense"
    ],
    "generate_answers": true,
    "limit": 100,
    "top_k": 6,
    "max_tokens": 690000,
    "max_calls": 600,
    "corpus_revision": 10,
    "chat_model": "gpt-4.1-mini",
    "context_budget": 1800,
    "history_budget": 400,
    "output_budget": 350,
    "prompt_version": "v2"
  },
  "environment": {
    "python": "3.12.11",
    "platform": "Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.36",
    "git_revision": null
  },
  "generated_at": "2026-09-10T04:02:28.240235+00:00",
  "budget_reservations": {
    "reserved_tokens": 216627,
    "reserved_calls": 154
  },
  "job_usage": {
    "input_tokens": 175262,
    "output_tokens": 4613,
    "cached_tokens": 0,
    "successful_provider_responses": 154,
    "cache_hits": 0,
    "retries_reported": 0,
    "estimated_cost_usd": 0.07692928,
    "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned."
  }
}
```

## Measured results

| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 70 | 1.0 | 1.0 | 0.1316 | 1967.1 | 5478.0775 | 0 |

## Limitations

- Project fixture regression is not an independent benchmark or expert-reviewed evaluation.
- Answer token F1 is a deterministic lexical proxy, not semantic relevance, correctness, or faithfulness.
- Citation validity checks supplied source membership and location, not whether the claim is supported; inspect result samples manually.
- Refusal detection is a text heuristic; unanswerable accuracy needs manual verification.
- No LLM judge is run; faithfulness and semantic content support are unmeasured (null).
- Latency p50/p95 are descriptive; fewer than 20 successful samples are flagged as insufficient for a reliable performance conclusion.
- Usage is provider-reported where available. Retries after a crash may incur unobservable provider charges; no zero-cost claim is made.
- QASPER paragraph evaluation does not exercise the PDF parser or Vietnamese QA.

## Failure examples

```json
[]
```

Inspect the JSON export for answers, supplied context, citation snippets, tool outcomes and per-question usage.

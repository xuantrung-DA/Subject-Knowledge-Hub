# Evaluation: page dev answers

Run `a57cfeab-4e99-4641-b16e-d71c6b5c6f21` — **ready**

## Configuration and provenance

```json
{
  "dataset_sha256": "6e2b4f43c79991fae29eef248ef9495bbfa2692b29bb158722c28ac82164e0fd",
  "question_count": 30,
  "config": {
    "modes": [
      "dense"
    ],
    "generate_answers": true,
    "limit": 100,
    "top_k": 6,
    "max_tokens": 290000,
    "max_calls": 600,
    "corpus_revision": 10,
    "chat_model": "gpt-4.1-mini",
    "context_budget": 1800,
    "history_budget": 400,
    "output_budget": 350,
    "prompt_version": "v1"
  },
  "environment": {
    "python": "3.12.11",
    "platform": "Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.36",
    "git_revision": null
  },
  "generated_at": "2026-09-10T03:57:05.768266+00:00",
  "budget_reservations": {
    "reserved_tokens": 72140,
    "reserved_calls": 66
  },
  "job_usage": {
    "input_tokens": 57126,
    "output_tokens": 1953,
    "cached_tokens": 0,
    "successful_provider_responses": 66,
    "cache_hits": 0,
    "retries_reported": 0,
    "estimated_cost_usd": 0.025690960000000002,
    "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned."
  }
}
```

## Measured results

| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 30 | 1.0 | 0.8993 | 0.1607 | 1948.475 | 4551.01 | 0 |

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

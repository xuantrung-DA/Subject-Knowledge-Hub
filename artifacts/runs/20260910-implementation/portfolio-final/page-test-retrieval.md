# Evaluation: page test retrieval

Run `d8a18067-8abc-409e-9de2-b5700c938427` — **ready**

## Configuration and provenance

```json
{
  "dataset_sha256": "e6bc877e581eac2ba5999a3a12646f8391e4ea28a5a039276f226d1611a3ae6b",
  "question_count": 70,
  "config": {
    "modes": [
      "lexical",
      "dense",
      "hybrid"
    ],
    "generate_answers": false,
    "limit": 100,
    "top_k": 6,
    "max_tokens": 10000,
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
  "generated_at": "2026-09-10T04:03:37.308214+00:00",
  "budget_reservations": {
    "reserved_tokens": 7286,
    "reserved_calls": 140
  },
  "job_usage": {
    "input_tokens": 2806,
    "output_tokens": 0,
    "cached_tokens": 0,
    "successful_provider_responses": 140,
    "cache_hits": 0,
    "retries_reported": 0,
    "estimated_cost_usd": 5.612e-05,
    "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned."
  }
}
```

## Measured results

| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 70 | 0.0 | 0.0 | unmeasured | 4.685 | 6.007 | 0 |
| dense | 70 | 1.0 | 0.9256 | unmeasured | 418.825 | 573.1215 | 0 |
| hybrid | 70 | 1.0 | 0.9256 | unmeasured | 429.74 | 601.124 | 0 |

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
[
  {
    "question_id": "maple-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-02",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-04",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-05",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-06",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-07",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "maple-08",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-02",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-04",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-05",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-06",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-07",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "lan-08",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "birch-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "birch-02",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "birch-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "birch-04",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  }
]
```

Inspect the JSON export for answers, supplied context, citation snippets, tool outcomes and per-question usage.

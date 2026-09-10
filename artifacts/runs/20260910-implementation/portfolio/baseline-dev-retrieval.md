# Evaluation: baseline dev retrieval

Run `accd35de-3284-47e1-80d9-54c5bb0bc580` — **ready**

## Configuration and provenance

```json
{
  "dataset_sha256": "6e2b4f43c79991fae29eef248ef9495bbfa2692b29bb158722c28ac82164e0fd",
  "question_count": 30,
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
    "prompt_version": "v1"
  },
  "environment": {
    "python": "3.12.11",
    "platform": "Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.36",
    "git_revision": null
  },
  "generated_at": "2026-09-10T03:42:51.409421+00:00",
  "budget_reservations": {
    "reserved_tokens": 3356,
    "reserved_calls": 60
  },
  "job_usage": {
    "input_tokens": 1436,
    "output_tokens": 0,
    "cached_tokens": 0,
    "successful_provider_responses": 60,
    "cache_hits": 0,
    "retries_reported": 0,
    "estimated_cost_usd": 2.872e-05,
    "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned."
  }
}
```

## Measured results

| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 30 | 0.0 | 0.0 | unmeasured | 5.735 | 10.6735 | 0 |
| dense | 30 | 1.0 | 0.9792 | unmeasured | 420.665 | 619.3485 | 0 |
| hybrid | 30 | 1.0 | 0.9792 | unmeasured | 417.25 | 579.357 | 0 |

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
    "question_id": "sen-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-02",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-04",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-05",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-06",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-07",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "sen-08",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-05",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-07",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "truc-01",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "truc-03",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "truc-05",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-02",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-04",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-06",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cedar-08",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "truc-02",
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

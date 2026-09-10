# Evaluation: Frozen QASPER eligible test100

Run `4451e4c1-3ed0-40e7-9532-c4492e6ff5fd` — **ready**

## Configuration and provenance

```json
{
  "dataset_sha256": "14ea0e784842d794eb29eadcf590f2994901040ec52ecf62c1af6cbe8736736a",
  "question_count": 100,
  "config": {
    "modes": [
      "lexical",
      "dense",
      "hybrid"
    ],
    "generate_answers": false,
    "limit": 100,
    "top_k": 6,
    "max_tokens": 30000,
    "max_calls": 400,
    "corpus_revision": 95,
    "chat_model": "gpt-4.1-mini",
    "context_budget": 4500,
    "history_budget": 1500,
    "output_budget": 900,
    "prompt_version": "v2"
  },
  "environment": {
    "python": "3.12.11",
    "platform": "Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.36",
    "git_revision": null
  },
  "generated_at": "2026-09-10T04:15:34.277726+00:00",
  "budget_reservations": {
    "reserved_tokens": 8270,
    "reserved_calls": 200
  },
  "job_usage": {
    "input_tokens": 1870,
    "output_tokens": 0,
    "cached_tokens": 0,
    "successful_provider_responses": 200,
    "cache_hits": 0,
    "retries_reported": 0,
    "estimated_cost_usd": 3.74e-05,
    "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned."
  }
}
```

## Measured results

| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 100 | 0.0 | 0.0 | unmeasured | 4.295 | 10.4375 | 0 |
| dense | 100 | 0.5835 | 0.4946 | unmeasured | 417.175 | 643.18 | 0 |
| hybrid | 100 | 0.5835 | 0.4946 | unmeasured | 413.02 | 645.9535 | 0 |

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
    "question_id": "1a419468d255d40ae82ed7777618072a48f0091b",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a3705b53c6710b41154c65327b7bbec175bdfae7",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a3705b53c6710b41154c65327b7bbec175bdfae7",
    "mode": "dense",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a3705b53c6710b41154c65327b7bbec175bdfae7",
    "mode": "hybrid",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "6b1a6517b343fdb79f246955091ff25e440b9511",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a064d01d45a33814947161ff208abb88d4353b26",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "27d7a30e42921e77cfffafac5cb0d16ce5a7df99",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "27d7a30e42921e77cfffafac5cb0d16ce5a7df99",
    "mode": "dense",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "27d7a30e42921e77cfffafac5cb0d16ce5a7df99",
    "mode": "hybrid",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "cfdd583d01abaca923f5c466bb20e1d4b8c749ff",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a0197894ee94b01766fa2051f50f84e16b5c9370",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "d4cb704e93086a2246a8caa5c1035e8297b8f4c0",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "c0dbf3f1957f3bff3ced5b48aff60097f3eac7bb",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "c0dbf3f1957f3bff3ced5b48aff60097f3eac7bb",
    "mode": "dense",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "c0dbf3f1957f3bff3ced5b48aff60097f3eac7bb",
    "mode": "hybrid",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "a24b2269b292fd0ee81d50303d1315383c594382",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "7748c072e07d6c6db5a34be38b4a5e97ac6d7999",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "02a5acb484bda77ef32a13f5d93d336472cf8cd4",
    "mode": "lexical",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "02a5acb484bda77ef32a13f5d93d336472cf8cd4",
    "mode": "dense",
    "error": null,
    "metrics": {
      "evidence_recall_at_k": 0.0,
      "evidence_precision_at_k": 0.0,
      "mrr": 0.0
    }
  },
  {
    "question_id": "02a5acb484bda77ef32a13f5d93d336472cf8cd4",
    "mode": "hybrid",
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

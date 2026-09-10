"""Aggregate completed paired runs; never invent missing measurements."""

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    folder = args.run_dir / "portfolio-final"
    rows = {}
    summaries = {}
    for strategy in ("baseline", "page"):
        run = json.loads((folder / f"{strategy}-test-answers.json").read_text(encoding="utf-8"))
        assert run["status"] == "ready"
        rows[strategy] = {r["question_id"]: r["result"] for r in run["results"]}
        summaries[strategy] = run["report"]["summary"]["dense"]
    assert set(rows["baseline"]) == set(rows["page"]) and len(rows["page"]) == 70
    before, after = summaries["baseline"], summaries["page"]
    result = {
        "dataset": "Original synthetic bilingual runbooks; 70 held-out questions, 7 documents, repeated templates",
        "answerable_questions": 56,
        "unanswerable_questions": 14,
        "configuration": "frozen-config.json; identical serving settings, only page-boundary strategy differs",
        "baseline": before,
        "page": after,
        "input_token_reduction_percent": 100 * (1 - after["total_input_tokens"] / before["total_input_tokens"]),
        "output_token_reduction_percent": 100 * (1 - after["total_output_tokens"] / before["total_output_tokens"]),
        "estimated_cost_reduction_percent": 100 * (1 - after["total_cost_usd"] / before["total_cost_usd"]),
        "latency_p95_reduction_percent": 100 * (1 - after["latency_p95_ms"] / before["latency_p95_ms"]),
        "paired_ids": sorted(rows["page"]),
        "limitations": [
            "Single run per frozen configuration; cloud latency varies.",
            "Synthetic templated questions are not independent real-world observations.",
            "Input tokens include embeddings and generated prior turns for follow-ups.",
            "Refusal phrase matching and token F1 are proxies, not human answer-quality scores.",
            "Mechanical citation validity does not establish content support.",
        ],
    }
    for strategy in ("baseline", "page"):
        refusals = [qid for qid, r in rows[strategy].items() if r["answerable"] and r.get("debug", {}).get("refusal")]
        widths = [
            c["page_end"] - c["page_start"] + 1
            for r in rows[strategy].values()
            for c in r["citations"]
            if c.get("page_start") is not None
        ]
        result[strategy + "_false_refusal_ids"] = refusals
        result[strategy + "_mean_citation_page_width"] = mean(widths) if widths else None
    (args.run_dir / "comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with (args.run_dir / "content-review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "question_id",
                "strategy",
                "question",
                "reference",
                "answer",
                "citation_pages",
                "correctness_0_1_2",
                "claim_support",
                "reviewer",
                "notes",
            ],
        )
        writer.writeheader()
        for qid in sorted(rows["page"]):
            for strategy in ("baseline", "page"):
                row = rows[strategy][qid]
                writer.writerow(
                    {
                        "question_id": qid,
                        "strategy": strategy,
                        "question": row["question"],
                        "reference": row["reference_answer"],
                        "answer": row["answer"],
                        "citation_pages": "; ".join(
                            f"{c['document_name']}:{c['page_start']}-{c['page_end']}" for c in row["citations"]
                        ),
                        "reviewer": "",
                        "notes": "Independent human review pending; not included in CV answer-accuracy claims.",
                    }
                )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "input_token_reduction_percent",
                    "estimated_cost_reduction_percent",
                    "latency_p95_reduction_percent",
                    "baseline_false_refusal_ids",
                    "page_false_refusal_ids",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()

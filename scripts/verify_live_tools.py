"""Small paid follow-up to the first smoke, reusing its existing PDFs/account."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        print("Dry run: two assistant tasks, <=48,000 reserved tokens combined; no uploads or confirmed summaries.")
        return
    if args.output.exists():
        raise RuntimeError("Refusing an accidental paid rerun over an existing result.")
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Subject, Document
    from app.config import settings
    from app.rag import answer

    assert settings.max_question_tokens <= 24000
    smoke = json.loads(args.smoke.read_text(encoding="utf-8"))
    results = []
    with SessionLocal() as db:
        subject = db.get(Subject, smoke["subject_id"])
        document = db.scalar(
            select(Document).where(Document.subject_id == subject.id, Document.document_key == "fixture_vi")
        )
        tasks = [
            (
                "read_document_pages",
                f"Dùng read_document_pages đọc trang 1 đến 2 của document_id {document.id} và trình bày nội dung chính kèm trích dẫn.",
            ),
            ("summarize_document", f"Dùng summarize_document để tóm tắt trang 1 đến 2 của document_id {document.id}."),
        ]
        for tool, question in tasks:
            response = answer(db, subject.user_id, subject.id, question, mode="assistant", disable_cache=True)
            runs = [run for run in response["debug"]["tool_runs"] if run["name"] == tool]
            selected = bool(runs) and all(run["status"] == "success" for run in runs)
            passed = selected and (
                bool(response["citations"]) and not response["debug"]["refusal"]
                if tool == "read_document_pages"
                else any(run["result"].get("requires_confirmation") for run in runs)
            )
            results.append({"expected_tool": tool, "passed": passed, "response": response})
    report = {
        "status": "PASS" if all(r["passed"] for r in results) else "FAIL",
        "provider": "live_openai",
        "scope": "Follow-up after concise/read-page prompt repair; summary confirmation is completed by the separate browser lifecycle test.",
        "results": results,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"]}))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

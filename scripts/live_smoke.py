#!/usr/bin/env python3
"""Explicit paid, bounded HTTP smoke against the running real application.

Dry-run is default. Runtime never switches to a fake provider. Test corpus is
original generated project material, not the user's private PDFs.
"""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
import secrets
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://web")
    p.add_argument("--email", default=os.getenv("HUB_EMAIL"))
    p.add_argument("--register", action="store_true", help="Create an isolated test account with a generated password")
    p.add_argument("--execute-paid", action="store_true")
    p.add_argument("--max-total-tokens", type=int, default=200000)
    p.add_argument("--max-wait-seconds", type=int, default=600)
    p.add_argument("--output", type=Path, default=ROOT / "artifacts" / "live-smoke.json")
    args = p.parse_args()
    # This is a conservative planned envelope, never claimed to be actual usage.
    print(
        json.dumps(
            {
                "paid_execution": args.execute_paid,
                "questions": 10,
                "tool_tasks": 5,
                "max_reported_tokens": args.max_total_tokens,
                "corpus": ["fixture_vi.pdf", "fixture_en.pdf"],
                "note": "Use compose.live-smoke.yaml budget overrides. Failed provider calls may have unreported usage.",
            },
            indent=2,
        )
    )
    if not args.execute_paid:
        print(
            "Dry run only. Add --execute-paid after reviewing the budget and providing a funded API key in backend env."
        )
        return
    if not args.email and not args.register:
        p.error("--email or HUB_EMAIL is required; register the account in the browser first.")
    if args.register:
        args.email = args.email or f"live-{secrets.token_hex(8)}@example.com"
        password = secrets.token_urlsafe(24)
    else:
        password = os.getenv("HUB_PASSWORD") or getpass.getpass("Local app password: ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": "live_openai",
        "status": "RUNNING",
        "results": [],
        "reported_tokens": 0,
        "reserved_tokens": 0,
        "errors": [],
    }

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def request(client, method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        if r.is_error:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:600]}")
        return r.json()

    try:
        with httpx.Client(base_url=args.url, timeout=180) as c:
            config = request(c, "GET", "/api/config")
            if not config["openai_configured"]:
                raise RuntimeError("OPENAI_API_KEY is missing; no paid tests were started.")
            question_cap = int(config.get("max_question_tokens", 0))
            ingestion_cap = int(config.get("max_ingestion_tokens", 0))
            if not 0 < question_cap <= 8000 or not 0 < ingestion_cap <= 25000:
                raise RuntimeError(
                    "Start with compose.live-smoke.yaml first: require question cap <=8000 and ingestion cap <=25000."
                )
            planned = 2 * ingestion_cap + 15 * question_cap
            report["planned_token_ceiling"] = planned
            if planned > args.max_total_tokens:
                raise RuntimeError(
                    f"Planned bounded calls require {planned} reserved tokens, above --max-total-tokens."
                )
            auth = request(
                c,
                "POST",
                "/api/auth/register" if args.register else "/api/auth/login",
                json={"email": args.email, "password": password},
            )
            report["email"] = args.email
            c.headers["X-CSRF-Token"] = auth["csrf_token"]
            subject = request(
                c, "POST", "/api/subjects", json={"name": "Live smoke " + datetime.now().strftime("%Y%m%d-%H%M%S")}
            )
            sid = subject["id"]
            base = f"/api/subjects/{sid}"
            report["subject_id"] = sid
            report["config"] = config
            docs = []
            for key in ("fixture_vi", "fixture_en"):
                report["reserved_tokens"] += ingestion_cap
                path = ROOT / "fixtures" / "project" / f"{key}.pdf"
                with path.open("rb") as f:
                    up = request(
                        c,
                        "POST",
                        base + "/documents",
                        files={"file": (path.name, f, "application/pdf")},
                        data={"document_key": key},
                    )
                start = time.monotonic()
                while True:
                    job = request(c, "GET", base + "/jobs/" + up["job_id"])
                    if job["status"] == "ready":
                        break
                    if job["status"] in ("failed", "needs_ocr", "cancelled"):
                        raise RuntimeError(f"Ingestion did not succeed: {job}")
                    if time.monotonic() - start > args.max_wait_seconds:
                        raise RuntimeError("Ingestion timeout; inspect durable job in browser.")
                    time.sleep(2)
                docs.append(up["document_id"])
                report.setdefault("ingestion", []).append(job)
                save()
            questions = [
                "Tỷ lệ chia tập train, validation và test là bao nhiêu?",
                "Learning rate và batch size trong tài liệu là bao nhiêu?",
                "Sau đó mô hình được huấn luyện bao nhiêu epochs?",
                "What are the mean and standard deviation used for normalization?",
                "Accuracy và F1 được ghi là bao nhiêu?",
                "Lớp học có tối đa bao nhiêu chỗ và lịch thực hành vào ngày nào?",
                "Early stopping patience được đặt là bao nhiêu?",
                "What protocol is described in the English document?",
                "Giá vé máy bay từ Hà Nội đến Paris hôm nay là bao nhiêu?",
                "What is the private password of the course instructor?",
            ]
            tasks = [
                ("list_documents", "Liệt kê các tài liệu hiện có trong môn này."),
                ("search_documents", "Dùng search_documents tìm evidence về learning rate."),
                ("read_document_pages", f"Dùng read_document_pages đọc trang 1 đến 2 của document_id {docs[0]}."),
                ("summarize_document", f"Dùng summarize_document tóm tắt trang 1 đến 2 của document_id {docs[1]}."),
                ("get_job_status", "Dùng get_job_status kiểm tra job_id " + report["ingestion"][0]["id"] + "."),
            ]
            conversation = None
            for index, (expected_tool, question) in enumerate([(None, q) for q in questions] + tasks):
                # Reserve one bounded question before starting it. Compose smoke
                # override caps each at 8k tokens; refuses when envelope exhausted.
                if report["reserved_tokens"] + question_cap > args.max_total_tokens:
                    raise RuntimeError("Client total token envelope reached; remaining tasks not executed.")
                report["reserved_tokens"] += question_cap
                began = time.perf_counter()
                try:
                    out = request(
                        c,
                        "POST",
                        base + "/chat",
                        json={
                            "question": question,
                            "conversation_id": conversation if index == 2 else None,
                            "mode": "assistant" if expected_tool else "direct",
                        },
                    )
                    conversation = out["conversation_id"]
                    for citation in out.get("citations", []):
                        assert citation["document_id"] in docs, "Cross-subject/document citation"
                        assert 1 <= citation["page_start"] <= citation["page_end"] <= 6, "Invalid PDF page"
                        r = c.get(
                            base + "/documents/" + citation["document_id"] + "/pdf",
                            params={"version_id": citation["version_id"]},
                        )
                        assert r.status_code == 200 and r.content.startswith(b"%PDF"), "Citation viewer failed"
                    usage = request(c, "GET", base + "/usage")
                    # Full result retained for inspection regardless of aggregate shape.
                    report["usage"] = usage
                    if isinstance(usage, dict):
                        totals = usage.get("totals", usage)
                        report["reported_tokens"] = int(totals.get("input_tokens", 0)) + int(
                            totals.get("output_tokens", 0)
                        )
                    report["results"].append(
                        {
                            "index": index + 1,
                            "expected_tool": expected_tool,
                            "question": question,
                            "latency_ms": round((time.perf_counter() - began) * 1000),
                            "response": out,
                            "citation_mechanical": "PASS",
                            "answer_support": "REQUIRES_MANUAL_REVIEW",
                        }
                    )
                except Exception as exc:
                    report["results"].append({"index": index + 1, "question": question, "error": str(exc)})
                    report["errors"].append(str(exc))
                save()
            report["status"] = "FAIL" if report["errors"] else "HTTP_COMPLETE_REVIEW_REQUIRED"
    except Exception as exc:
        report["status"] = "FAIL"
        report["errors"].append(str(exc))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "artifact": str(args.output),
                "results": len(report["results"]),
                "reported_tokens": report["reported_tokens"],
            },
            indent=2,
        )
    )
    if report["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

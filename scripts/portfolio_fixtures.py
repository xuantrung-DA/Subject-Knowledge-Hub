#!/usr/bin/env python3
"""Original synthetic bilingual PDF benchmark; no provider calls.

Ten fictional service runbooks, 100 templated questions, fixed document split.
This is a controlled regression corpus, not a representative real-world sample.
"""

import hashlib
import json
from pathlib import Path
from fixtures import make_pdf as pdf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "portfolio"
SERVICES = [
    ("sen", "Sen", "vi", "quan trắc hồ", 24, 7, 45, 3, 12, 18, 96, 71),
    ("cedar", "Cedar", "en", "forest sensors", 32, 9, 60, 4, 14, 22, 94, 73),
    ("truc", "Trúc", "vi", "kiểm kê thư viện", 48, 11, 90, 5, 16, 26, 92, 75),
    ("maple", "Maple", "en", "warehouse counters", 64, 13, 120, 6, 18, 30, 90, 77),
    ("lan", "Lan", "vi", "lịch phòng thí nghiệm", 80, 15, 150, 7, 20, 34, 98, 79),
    ("birch", "Birch", "en", "bus stop displays", 96, 17, 180, 8, 22, 38, 89, 81),
    ("cuc", "Cúc", "vi", "theo dõi vườn ươm", 112, 19, 210, 9, 24, 42, 97, 83),
    ("willow", "Willow", "en", "water meter readings", 128, 21, 240, 10, 26, 46, 93, 85),
    ("dao", "Đào", "vi", "đặt chỗ xe đạp", 144, 23, 270, 11, 28, 50, 95, 87),
    ("elm", "Elm", "en", "museum attendance", 160, 25, 300, 12, 30, 54, 91, 89),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, corpus = [], []
    for index, (
        key,
        name,
        lang,
        purpose,
        batch,
        timeout,
        ttl,
        retries,
        retention,
        recovery,
        accuracy,
        latency,
    ) in enumerate(SERVICES):
        vi = lang == "vi"
        if vi:
            pages = [
                (
                    f"{name}: phạm vi và tiếp nhận",
                    f"{name} là dịch vụ giả định phục vụ {purpose}. Mỗi yêu cầu {name} nhận tối đa {batch} bản ghi. Định dạng đầu vào là JSON Lines, mã hóa UTF-8. Đây là dữ liệu kiểm thử tổng hợp, không phải thông số của sản phẩm thật.",
                ),
                (
                    f"{name}: xử lý",
                    f"Thời gian chờ xử lý của {name} là {timeout} giây. Khi lỗi mạng, {name} thử lại tối đa {retries} lần. Khoảng chờ tăng theo cấp số nhân. Lỗi dữ liệu không được thử lại. Yêu cầu trùng bị loại bằng khóa request_id.",
                ),
                (
                    f"{name}: lưu trữ",
                    f"{name} lưu nhật ký trong {retention} ngày. Bản hướng dẫn A ghi TTL cache là {ttl} giây. Mã bản sao lưu là {key.upper()}-SAFE. Dữ liệu lưu ở vùng thử nghiệm local, không có cam kết vùng địa lý thương mại.",
                ),
                (
                    f"{name}: bảng đo",
                    f"Bảng kết quả thử nghiệm của {name}:\nChỉ số | Giá trị\nAccuracy | {accuracy}%\nLatency p95 | {latency} ms\nThời gian phục hồi | {recovery} giây\nCác phép đo dùng đúng 200 yêu cầu, concurrency 1. Những con số này được tác giả bịa để kiểm thử đọc tài liệu, không phải benchmark của Subject Knowledge Hub.",
                ),
                (
                    f"{name}: ghi chú chưa thống nhất",
                    f"Bản hướng dẫn B của {name} ghi TTL cache là {ttl + 15} giây, khác bản A. Hai bản không ghi ngày hiệu lực; chưa xác định được bản nào thay thế bản nào. Người vận hành phải xác minh trước khi chọn TTL. Không có thông tin về giá thuê, địa chỉ email hỗ trợ hoặc SLA trong tài liệu.",
                ),
            ]
            questions = [
                (f"{name} nhận nhiều nhất bao nhiêu bản ghi trong một yêu cầu?", str(batch), [1], "direct"),
                (f"Thời gian chờ xử lý của {name} là bao nhiêu giây?", str(timeout), [2], "direct"),
                (f"Nhật ký của {name} được lưu bao lâu?", str(retention), [3], "direct"),
                (f"Nếu mất kết nối, {name} cho phép gửi lại tối đa mấy lần?", str(retries), [2], "paraphrase"),
                (
                    f"Trong bảng thử nghiệm của {name}, độ trễ mà 95% yêu cầu không vượt quá là bao nhiêu?",
                    f"{latency} ms",
                    [4],
                    "table",
                ),
                ("Dữ liệu đầu vào dùng định dạng và mã hóa nào?", "JSON Lines, UTF-8", [1], "followup"),
                (
                    f"Với {name}, nêu giới hạn bản ghi mỗi yêu cầu và thời gian phục hồi đo được.",
                    f"{batch} bản ghi; {recovery} giây",
                    [1, 4],
                    "multi_page",
                ),
                (
                    f"Các hướng dẫn {name} có thống nhất TTL cache không? Nêu hai giá trị và có thể chọn bản mới hơn không.",
                    f"{ttl} và {ttl + 15} giây; không có ngày hiệu lực nên chưa chọn được bản mới hơn.",
                    [3, 5],
                    "conflict",
                ),
                (
                    f"Giá thuê dịch vụ {name} mỗi tháng là bao nhiêu?",
                    "Không có thông tin trong tài liệu.",
                    [],
                    "unanswerable",
                ),
                (f"Địa chỉ email hỗ trợ của {name} là gì?", "Không có thông tin trong tài liệu.", [], "unanswerable"),
            ]
        else:
            pages = [
                (
                    f"{name}: scope and intake",
                    f"{name} is a fictional service for {purpose}. A {name} request accepts at most {batch} records. Input uses JSON Lines encoded as UTF-8. This is original synthetic test material, not the specification of a real product.",
                ),
                (
                    f"{name}: execution",
                    f"{name} has a processing timeout of {timeout} seconds. Network failures are retried at most {retries} times with exponential backoff. Invalid data is never retried. Duplicate requests are rejected using request_id.",
                ),
                (
                    f"{name}: storage",
                    f"{name} retains logs for {retention} days. Guide A specifies a cache TTL of {ttl} seconds. The backup code is {key.upper()}-SAFE. Storage is in the local test region; no commercial geographic residency is promised.",
                ),
                (
                    f"{name}: measurement table",
                    f"{name} test results:\nMetric | Value\nAccuracy | {accuracy}%\nLatency p95 | {latency} ms\nRecovery time | {recovery} seconds\nThe test uses exactly 200 requests at concurrency 1. The author invented these values for document-reading tests. They are not Subject Knowledge Hub benchmark results.",
                ),
                (
                    f"{name}: unresolved disagreement",
                    f"Guide B for {name} specifies a cache TTL of {ttl + 15} seconds, unlike guide A. Neither guide has an effective date, so their precedence is unknown. Operators must verify the intended TTL. The document contains no rental price, support email address, or SLA.",
                ),
            ]
            questions = [
                (f"What is the maximum number of records in one {name} request?", str(batch), [1], "direct"),
                (f"What processing timeout does {name} use in seconds?", str(timeout), [2], "direct"),
                (f"How long does {name} keep its logs?", str(retention), [3], "direct"),
                (
                    f"After a network failure, how many repeat attempts does {name} permit?",
                    str(retries),
                    [2],
                    "paraphrase",
                ),
                (
                    f"In the {name} experiment, what response time covers 95 percent of requests?",
                    f"{latency} ms",
                    [4],
                    "table",
                ),
                ("Which input format and character encoding does it use?", "JSON Lines, UTF-8", [1], "followup"),
                (
                    f"Give the per-request record limit and measured recovery time for {name}.",
                    f"{batch} records; {recovery} seconds",
                    [1, 4],
                    "multi_page",
                ),
                (
                    f"Do the {name} guides agree on cache TTL? Give both values and say whether the newer guide can be identified.",
                    f"{ttl} and {ttl + 15} seconds; no effective dates, precedence unknown.",
                    [3, 5],
                    "conflict",
                ),
                (
                    f"How much does renting {name} cost per month?",
                    "Insufficient evidence in the document.",
                    [],
                    "unanswerable",
                ),
                (
                    f"What is the support email address for {name}?",
                    "Insufficient evidence in the document.",
                    [],
                    "unanswerable",
                ),
            ]
        path = OUT / f"{key}.pdf"
        pdf(path, pages)
        split = "dev" if index < 3 else "test"
        corpus.append(
            {
                "document_key": key,
                "name": name,
                "language": lang,
                "split": split,
                "pages": [{"number": n, "title": title, "text": body} for n, (title, body) in enumerate(pages, 1)],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        for number, (question, reference, evidence, kind) in enumerate(questions, 1):
            row = {
                "id": f"{key}-{number:02d}",
                "question": question,
                "reference_answer": reference,
                "answerable": bool(evidence),
                "evidence": [{"document_key": key, "page_start": p, "page_end": p} for p in evidence],
                "tags": [lang, kind, split],
                "metadata": {"fact_group": f"{key}-{number}", "document_group": key, "split": split},
            }
            if kind == "followup":
                row["history"] = [f"Giới thiệu dịch vụ {name}." if vi else f"Introduce the {name} service."]
            rows.append(row)
    for split in ("dev", "test"):
        (OUT / f"{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["metadata"]["split"] == split),
            encoding="utf-8",
        )
    (OUT / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "dataset": "Original fictional service runbooks v1",
        "license": "CC0-1.0",
        "question_count": 100,
        "documents": 10,
        "physical_pages": 50,
        "dev_ids": [r["id"] for r in rows[:30]],
        "test_ids": [r["id"] for r in rows[30:]],
        "split": "First three whole documents dev; seven whole documents held out; no shared document/fact across splits.",
        "authorship": "AI-authored templated synthetic facts and questions; independent human validation not performed.",
        "limitations": [
            "Repeated question templates; do not treat 100 as independent real-world observations.",
            "Numeric values inside PDFs are fictional corpus facts, never application performance claims.",
            "Includes simple text tables, not a layout benchmark.",
        ],
        "hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(OUT.iterdir())
            if p.suffix in {".pdf", ".jsonl"} or p.name == "corpus.json"
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"documents": 10, "pages": 50, "questions": 100, "dev": 30, "test": 70}))


if __name__ == "__main__":
    main()

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.evaluation import (
    EvaluationConfig,
    PersistentEvaluationBudget,
    parse_dataset,
    token_f1,
    retrieval_metrics,
    citation_metrics,
    export_report,
    build_report,
)

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "fixtures").exists():
    ROOT = Path("/app")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tài liệu không cung cấp thông tin về giá thuê.", True),
        ("The guide does not provide a support email address.", True),
        ("The document contains no information about pricing.", True),
        ("The price is 24 dollars per month.", False),
        ("Không thử lại khi dữ liệu sai. Timeout là 7 giây.", False),
    ],
)
def test_bilingual_refusal_phrase_proxy(text, expected):
    from app.evaluation import refusal_phrase_match

    assert refusal_phrase_match(text) is expected


def row(**changes):
    return {
        "id": "q1",
        "question": "What is the seed?",
        "reference_answer": "42",
        "answerable": True,
        "evidence": [{"document_key": "doc", "page_start": 1, "page_end": 1}],
        **changes,
    }


def test_validation_rejects_duplicate_ids_bad_pages_unknown_fields_and_bad_utf8():
    line = json.dumps(row())
    with pytest.raises(ValueError, match="Duplicate"):
        parse_dataset((line + "\n" + line).encode())
    for evidence in [
        [{"document_key": "doc", "page_start": 2, "page_end": 1}],
        [{"document_key": "doc", "page_start": 1, "page_end": 1, "paragraph_ids": ["p1"]}],
    ]:
        with pytest.raises(ValueError):
            parse_dataset(json.dumps(row(evidence=evidence)).encode())
    with pytest.raises(ValueError):
        parse_dataset(json.dumps(row(admin_scope="all")).encode())
    with pytest.raises(ValueError):
        parse_dataset(b"\xff")
    with pytest.raises(ValueError):
        EvaluationConfig(modes=["dense", "dense"])


def test_page_and_paragraph_metrics_are_distinct_and_version_sensitive():
    q = row(evidence=[{"document_key": "doc", "page_start": 2, "page_end": 3}])
    mapping = {"doc": {"document_id": "d", "version_id": "v2"}}
    sources = [
        {"document_id": "d", "version_id": "v1", "page_start": 2, "page_end": 3},
        {"document_id": "d", "version_id": "v2", "page_start": 3, "page_end": 4},
    ]
    measured = retrieval_metrics(q, sources, mapping, 2)
    assert measured["evidence_recall_at_k"] == 0.5
    assert measured["mrr"] == 0.5
    q = row(evidence=[{"document_key": "doc", "paragraph_ids": ["s0:p0", "s0:p1"]}])
    measured = retrieval_metrics(
        q,
        [{"document_id": "d", "version_id": "v2", "paragraph_ids": ["s0:p1"], "page_start": None, "page_end": None}],
        mapping,
        6,
    )
    assert measured["evidence_recall_at_k"] == 0.5
    assert measured["evidence_precision_at_k"] == 1


def test_mechanical_citation_validity_does_not_claim_support():
    source = {
        "id": 1,
        "chunk_id": "c",
        "document_id": "d",
        "version_id": "v",
        "page_start": 3,
        "page_end": 3,
        "paragraph_ids": None,
    }
    fake = {**source, "page_start": 99}
    metrics = citation_metrics([source, fake], [source], "A statement [1] [999]")
    assert metrics["citation_validity"] == 0.5
    assert metrics["citation_marker_validity"] == 0.5
    assert metrics["citation_content_support"] is None
    assert token_f1("LEARNING rate is 0.01", "learning rate is 0.01") == 1
    assert token_f1("cat", "dog") == 0


def test_exports_are_real_metrics_and_csv_formulas_are_escaped():
    run = SimpleNamespace(id="run1", name="Example", dataset=[row()], config={"modes": ["lexical"]}, status="ready")
    result = [
        {
            "question_id": "q1",
            "mode": "lexical",
            "result": {
                "answer": '=HYPERLINK("bad")',
                "latency_ms": 3,
                "metrics": {"evidence_recall_at_k": 0},
                "usage": {},
                "error": None,
            },
        }
    ]
    run.report = build_report(run, result)
    assert run.report["summary"]["lexical"]["answer_token_f1"] is None
    assert run.report["summary"]["lexical"]["latency_reliable"] is False
    assert len(run.report["failures"]) == 1
    for format in ["json", "csv", "md"]:
        content, mime = export_report(run, result, format)
        assert content and mime
        if format == "csv":
            assert "'=HYPERLINK" in content
    with pytest.raises(ValueError):
        export_report(run, result, "html")


def test_persistent_budget_counts_attempts_and_rejects_before_mutating():
    class DB:
        commits = 0

        def commit(self):
            self.commits += 1

    db = DB()
    job = SimpleNamespace(checkpoint={}, heartbeat_at=None)
    budget = PersistentEvaluationBudget(db, job, max_tokens=1000, max_calls=2)
    budget.reserve(["small query"], embedding=True, output=0)
    budget.reserve(["small query"], embedding=True, output=0)  # retry is another attempt
    assert db.commits == 2 and job.checkpoint["reserved_calls"] == 2
    previous = job.checkpoint.copy()
    with pytest.raises(Exception, match="tokens/calls"):
        budget.reserve(["third"], embedding=True, output=0)
    assert job.checkpoint == previous and db.commits == 2
    # A recreated object resumes the durable allowance, not zero.
    resumed = PersistentEvaluationBudget(db, job, max_tokens=1000, max_calls=2)
    with pytest.raises(Exception):
        resumed.reserve(["retry"], output=0)


def test_fixture_dataset_has_50plus_diverse_cases_and_actual_pdf_quotes():
    from pypdf import PdfReader

    directory = ROOT / "fixtures" / "project"
    dataset = parse_dataset((directory / "regression.jsonl").read_bytes())
    assert len(dataset) >= 50
    tags = {tag for q in dataset for tag in q["tags"]}
    assert {
        "vi",
        "en",
        "paraphrase",
        "follow_up",
        "multi_source",
        "conflicting_sources",
        "prompt_injection",
        "out_of_scope",
    } <= tags
    readers = {}
    for q in dataset:
        for e in q["evidence"]:
            reader = readers.setdefault(e["document_key"], PdfReader(directory / f"{e['document_key']}.pdf"))
            assert e["page_end"] <= len(reader.pages)
            actual = " ".join(reader.pages[p - 1].extract_text() for p in range(e["page_start"], e["page_end"] + 1))
            if e.get("quote"):
                assert " ".join(e["quote"].split()) in " ".join(actual.split())
    lifecycle = json.loads((directory / "lifecycle.json").read_text())
    assert {x["action"] for x in lifecycle} == {"upload", "replace", "upload_then_delete"}


def test_qasper_selection_is_fixed_and_answers_never_enter_corpus(tmp_path):
    module_path = ROOT / "scripts" / "qasper.py"
    spec = importlib.util.spec_from_file_location("qasper_adapter_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {}
    for i in range(120):
        text = f"Original paragraph {i} reports a calibration value."
        data[str(i)] = {
            "title": f"Paper {i}",
            "abstract": "Shared abstract.",
            "full_text": [{"section_name": "Results", "paragraphs": [text]}],
            "qas": [
                {
                    "question_id": f"official-{i}",
                    "question": f"Question {i}?",
                    "answers": [
                        {
                            "answer": {
                                "unanswerable": False,
                                "free_form_answer": f"SECRET_GOLDEN_{i}",
                                "evidence": [text],
                            }
                        }
                    ],
                }
            ],
        }
    manifest = module.adapt(data, "sourcehash", tmp_path)
    assert manifest["question_count"] == 100 and len(set(manifest["question_ids"])) == 100
    assert "SECRET_GOLDEN_" not in (tmp_path / "corpus.jsonl").read_text()
    test_rows = parse_dataset((tmp_path / "test100.jsonl").read_bytes())
    assert len(test_rows) == 100
    assert all(e["page_start"] is None for q in test_rows for e in q["evidence"])
    module.adapt(dict(reversed(list(data.items()))), "sourcehash", tmp_path, manifest)
    with pytest.raises(ValueError, match="refusing"):
        module.adapt(data, "changed-source", tmp_path, manifest)

"""Reproducible evaluation using application retrieval and generation.

Reference answers are consumed only by scoring after the answer is produced.
No judge service, paid or otherwise, runs implicitly.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
import re
import subprocess
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_key: str = Field(min_length=1, max_length=200)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    paragraph_ids: list[str] = Field(default_factory=list, max_length=200)
    quote: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def valid_location(self):
        if self.paragraph_ids:
            if self.page_start is not None or self.page_end is not None:
                raise ValueError("Use paragraph IDs OR physical PDF pages, never both")
        elif self.page_start is None or self.page_end is None or self.page_end < self.page_start:
            raise ValueError("Evidence needs a valid physical PDF page range or paragraph_ids")
        if self.page_start and self.page_end - self.page_start > 100:
            raise ValueError("Evidence range must contain at most 101 pages")
        return self


class EvaluationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=8000)
    reference_answer: str = Field(max_length=20000)
    reference_answers: list[str] = Field(default_factory=list, max_length=30)
    answerable: bool
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    history: list[str] = Field(default_factory=list, max_length=6)
    expected_tools: list[str] = Field(default_factory=list, max_length=5)
    chat_mode: Literal["direct", "assistant"] = "direct"
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_answerability(self):
        if self.answerable and not self.reference_answer.strip():
            raise ValueError("Answerable questions need a reference answer")
        if self.answerable and not self.evidence and not self.expected_tools:
            raise ValueError("Answerable questions need evidence or an expected operational tool")
        if any(not isinstance(h, str) or not h.strip() or len(h) > 8000 for h in self.history):
            raise ValueError("History contains only nonempty user questions, not reference answers")
        target = self.metadata.get("target_document_key")
        if target is not None and (not isinstance(target, str) or not 1 <= len(target) <= 200):
            raise ValueError("metadata.target_document_key must be a nonempty string of at most 200 characters")
        if target and self.chat_mode != "direct":
            raise ValueError("Paper-conditioned evaluation supports direct mode only")
        allowed = {"search_documents", "read_document_pages", "list_documents", "summarize_document", "get_job_status"}
        if not set(self.expected_tools) <= allowed:
            raise ValueError("Unknown expected tool")
        return self


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modes: list[Literal["lexical", "dense", "hybrid"]] = Field(
        default_factory=lambda: ["lexical", "dense", "hybrid"], min_length=1, max_length=3
    )
    generate_answers: bool = False
    limit: int = Field(default=10, ge=1, le=500)
    top_k: int = Field(default=6, ge=1, le=20)
    max_tokens: int = Field(default=100000, ge=100, le=2000000)
    max_calls: int = Field(default=200, ge=1, le=10000)

    @model_validator(mode="after")
    def unique_modes(self):
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("Retrieval modes must be unique")
        return self


def parse_dataset(content: bytes, max_questions: int = 500) -> list[dict]:
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Dataset exceeds the 10 MB limit")
    rows, seen = [], set()
    for number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = EvaluationQuestion.model_validate_json(line)
        except Exception as exc:
            raise ValueError(f"Invalid JSONL line {number}: {exc}") from exc
        if row.id in seen:
            raise ValueError(f"Duplicate question ID: {row.id}")
        seen.add(row.id)
        rows.append(row.model_dump())
        if len(rows) > max_questions:
            raise ValueError(f"Dataset has more than {max_questions} questions")
    if not rows:
        raise ValueError("Dataset has no questions")
    return rows


def canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def normalized_tokens(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def token_f1(prediction: str, reference: str) -> float:
    """Lexical correctness proxy; does NOT measure semantic correctness/faithfulness."""
    p, r = normalized_tokens(prediction), normalized_tokens(reference)
    if not p or not r:
        return float(p == r)
    overlap = sum((Counter(p) & Counter(r)).values())
    return 2 * overlap / (len(p) + len(r))


def _reference_units(question: dict, mapping: dict) -> set[tuple]:
    result = set()
    for evidence in question["evidence"]:
        location = mapping[evidence["document_key"]]
        did = location["document_id"] if isinstance(location, dict) else location
        vid = location.get("version_id") if isinstance(location, dict) else None
        if evidence.get("paragraph_ids"):
            result.update((did, vid, "paragraph", pid) for pid in evidence["paragraph_ids"])
        else:
            result.update((did, vid, "page", p) for p in range(evidence["page_start"], evidence["page_end"] + 1))
    return result


def _retrieved_units(source: dict, version_sensitive: bool = True) -> set[tuple]:
    did, vid = source.get("document_id"), source.get("version_id") if version_sensitive else None
    if source.get("paragraph_ids"):
        return {(did, vid, "paragraph", p) for p in source["paragraph_ids"]}
    if source.get("page_start") is None or source.get("page_end") is None:
        return set()
    return {
        (did, vid, "page", p) for p in source.get("pages", []) or range(source["page_start"], source["page_end"] + 1)
    }


def retrieval_metrics(question: dict, sources: list[dict], mapping: dict, k: int) -> dict:
    expected = _reference_units(question, mapping)
    if not expected:
        return {"evidence_recall_at_k": None, "evidence_precision_at_k": None, "mrr": None}
    version_sensitive = all(unit[1] for unit in expected)
    if not version_sensitive:
        expected = {(did, None, kind, value) for did, _, kind, value in expected}
    seen, reciprocal_rank = set(), 0.0
    for rank, source in enumerate(sources[:k], 1):
        units = _retrieved_units(source, version_sensitive)
        seen |= units
        if units & expected and not reciprocal_rank:
            reciprocal_rank = 1 / rank
    return {
        "evidence_recall_at_k": len(seen & expected) / len(expected),
        "evidence_precision_at_k": len(seen & expected) / len(seen) if seen else 0.0,
        "mrr": reciprocal_rank,
    }


def refusal_phrase_match(text: str) -> bool:
    """Bilingual lexical proxy only; correctness still requires content review."""
    text = " ".join(text.casefold().split())
    patterns = (
        r"chưa tìm thấy|không tìm thấy|không đủ thông tin",
        r"không (?:có|cung cấp|đề cập|nêu|ghi).{0,100}(?:thông tin|giá thuê|email)",
        r"not enough evidence|insufficient evidence|cannot find|not found in",
        r"(?:does not|do not|doesn.t|don.t) (?:contain|provide|specify|mention)",
        r"(?:contains?|provides?|has|is) no (?:information|details|rental|support|price)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def citation_metrics(citations: list[dict], sources: list[dict], answer_text: str) -> dict:
    """Mechanical source membership only. Content support requires human review."""
    by_id = {str(s.get("id")): s for s in sources}
    valid = 0
    for citation in citations:
        source = by_id.get(str(citation.get("id")))
        if source is None:
            source = next(
                (s for s in sources if citation.get("chunk_id") and s.get("chunk_id") == citation["chunk_id"]), None
            )
        if (
            source
            and all(citation.get(k) == source.get(k) for k in ("document_id", "version_id", "page_start", "page_end"))
            and (citation.get("paragraph_ids") or []) == (source.get("paragraph_ids") or [])
        ):
            valid += 1
    cited_ids = set(re.findall(r"\[(\d+)\]", answer_text))
    valid_ids = {str(c.get("id")) for c in citations}
    return {
        "citation_validity": valid / len(citations) if citations else None,
        "citation_marker_validity": len(cited_ids & valid_ids) / len(cited_ids) if cited_ids else None,
        "citation_content_support": None,
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def build_report(run, result_rows: list[dict]) -> dict:
    summaries = {}
    metric_names = [
        "evidence_recall_at_k",
        "evidence_precision_at_k",
        "mrr",
        "answer_token_f1",
        "unanswerable_accuracy",
        "citation_validity",
        "citation_marker_validity",
        "tool_selection_recall",
        "tool_error_rate",
    ]
    for mode in run.config["modes"]:
        rows = [r["result"] for r in result_rows if r["mode"] == mode]
        successful = [r for r in rows if not r.get("error")]
        latencies = [r["latency_ms"] for r in successful]
        summary = {
            "sample_size": len(rows),
            "successful_samples": len(successful),
            "errors": len(rows) - len(successful),
        }
        for key in metric_names:
            values = [r.get("metrics", {}).get(key) for r in successful]
            values = [v for v in values if v is not None]
            summary[key] = mean(values) if values else None
            summary[key + "_n"] = len(values)
        summary.update(
            latency_p50_ms=percentile(latencies, 0.5),
            latency_p95_ms=percentile(latencies, 0.95),
            latency_sample_size=len(latencies),
            latency_reliable=len(latencies) >= 20,
        )
        for key in ("input_tokens", "output_tokens", "cached_tokens", "provider_calls"):
            summary["total_" + key] = sum(r.get("usage", {}).get(key, 0) for r in rows)
        costs = [r.get("usage", {}).get("estimated_cost_usd") for r in rows]
        summary["total_cost_usd"] = sum(costs) if costs and all(c is not None for c in costs) else None
        summaries[mode] = summary
    try:
        git_revision = (
            subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2).stdout.strip()
            or None
        )
    except (OSError, subprocess.TimeoutExpired):
        git_revision = None
    return {
        "dataset_sha256": canonical_hash(run.dataset),
        "question_count": len(run.dataset),
        "config": run.config,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "git_revision": git_revision,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summaries,
        "failures": [
            {
                "question_id": r["question_id"],
                "mode": r["mode"],
                "error": r["result"].get("error"),
                "metrics": r["result"].get("metrics", {}),
            }
            for r in result_rows
            if r["result"].get("error") or r["result"].get("metrics", {}).get("evidence_recall_at_k") == 0
        ],
        "limitations": [
            "Project fixture regression is not an independent benchmark or expert-reviewed evaluation.",
            "Answer token F1 is a deterministic lexical proxy, not semantic relevance, correctness, or faithfulness.",
            "Citation validity checks supplied source membership and location, not whether the claim is supported; inspect result samples manually.",
            "Refusal detection is a text heuristic; unanswerable accuracy needs manual verification.",
            "No LLM judge is run; faithfulness and semantic content support are unmeasured (null).",
            "Latency p50/p95 are descriptive; fewer than 20 successful samples are flagged as insufficient for a reliable performance conclusion.",
            "Usage is provider-reported where available. Retries after a crash may incur unobservable provider charges; no zero-cost claim is made.",
            "QASPER paragraph evaluation does not exercise the PDF parser or Vietnamese QA.",
        ],
    }


def export_report(run, results: list[dict], format: str) -> tuple[str, str]:
    payload = {"id": run.id, "name": run.name, "status": run.status, "report": run.report, "results": results}
    if format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2), "application/json"
    if format == "csv":
        stream = io.StringIO()
        fields = [
            "question_id",
            "mode",
            "answer",
            "latency_ms",
            "error",
            "evidence_recall_at_k",
            "evidence_precision_at_k",
            "mrr",
            "answer_token_f1",
            "unanswerable_accuracy",
            "citation_validity",
            "citation_content_support",
            "tool_selection_recall",
            "input_tokens",
            "output_tokens",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in results:
            data = {
                **row["result"],
                **row["result"].get("metrics", {}),
                **row["result"].get("usage", {}),
                "question_id": row["question_id"],
                "mode": row["mode"],
            }
            # Prevent spreadsheet formula execution for user-controlled values.
            writer.writerow(
                {
                    k: (
                        "'" + str(data[k])
                        if isinstance(data.get(k), str) and data[k].startswith(("=", "+", "-", "@", "\t", "\r"))
                        else data.get(k)
                    )
                    for k in fields
                }
            )
        return stream.getvalue(), "text/csv; charset=utf-8"
    if format != "md":
        raise ValueError("Format must be json, csv or md")
    lines = [
        f"# Evaluation: {run.name.replace(chr(10), ' ')}",
        "",
        f"Run `{run.id}` — **{run.status}**",
        "",
        "## Configuration and provenance",
        "",
        "```json",
        json.dumps(
            {k: v for k, v in (run.report or {}).items() if k not in ("summary", "failures", "limitations")},
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## Measured results",
        "",
        "| Mode | Samples | Recall@k | MRR | Token F1 proxy | p50 ms | p95 ms | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def display(value):
        return "unmeasured" if value is None else str(round(value, 4)) if isinstance(value, float) else str(value)

    for mode, summary in (run.report or {}).get("summary", {}).items():
        lines.append(
            "| "
            + " | ".join(
                [mode]
                + [
                    display(summary.get(k))
                    for k in (
                        "sample_size",
                        "evidence_recall_at_k",
                        "mrr",
                        "answer_token_f1",
                        "latency_p50_ms",
                        "latency_p95_ms",
                        "errors",
                    )
                ]
            )
            + " |"
        )
    lines.extend(["", "## Limitations", ""] + ["- " + s for s in (run.report or {}).get("limitations", [])])
    lines.extend(
        [
            "",
            "## Failure examples",
            "",
            "```json",
            json.dumps((run.report or {}).get("failures", [])[:20], ensure_ascii=False, indent=2),
            "```",
            "",
            "Inspect the JSON export for answers, supplied context, citation snippets, tool outcomes and per-question usage.",
        ]
    )
    return "\n".join(lines) + "\n", "text/markdown; charset=utf-8"


def validate_mapping(db, user_id: str, subject_id: str, dataset: list[dict], mapping: dict) -> dict:
    from sqlalchemy import select
    from app.errors import AppError
    from app.models import Document, DocumentVersion, DocumentPage, Chunk
    from app.security import require_subject

    require_subject(db, user_id, subject_id)
    keys = {e["document_key"] for q in dataset for e in q["evidence"]}
    keys.update(
        q.get("metadata", {}).get("target_document_key")
        for q in dataset
        if q.get("metadata", {}).get("target_document_key")
    )
    resolved = {}
    for key in keys:
        value = mapping.get(key)
        if not value:
            doc = db.scalar(
                select(Document).where(
                    Document.subject_id == subject_id, Document.document_key == key, Document.deleted_at.is_(None)
                )
            )
        else:
            doc = db.scalar(
                select(Document).where(
                    Document.id == (value.get("document_id") if isinstance(value, dict) else value),
                    Document.subject_id == subject_id,
                    Document.deleted_at.is_(None),
                )
            )
        if not doc or not doc.active_version_id:
            raise AppError(
                "evaluation_mapping_invalid", f"Không tìm thấy tài liệu ready cho document_key '{key}'.", 422
            )
        version_id = value.get("version_id") if isinstance(value, dict) else None
        if version_id and version_id != doc.active_version_id:
            raise AppError("evaluation_mapping_stale", f"'{key}' không trỏ đến phiên bản đang hoạt động.", 422)
        version = db.get(DocumentVersion, doc.active_version_id)
        if not version or version.status != "ready":
            raise AppError("evaluation_mapping_not_ready", f"Tài liệu '{key}' chưa sẵn sàng.", 422)
        resolved[key] = {"document_id": doc.id, "version_id": version.id}
        for q in dataset:
            for e in q["evidence"]:
                if e["document_key"] != key:
                    continue
                if e.get("paragraph_ids"):
                    chunks = db.scalars(select(Chunk).where(Chunk.version_id == version.id)).all()
                    available = {p for c in chunks for p in (getattr(c, "paragraph_ids", None) or [])}
                    if not set(e["paragraph_ids"]) <= available:
                        raise AppError(
                            "evaluation_evidence_invalid", f"Paragraph evidence không tồn tại: {q['id']}", 422
                        )
                else:
                    if e["page_end"] > (version.page_count or 0):
                        raise AppError("evaluation_evidence_invalid", f"Trang evidence vượt tài liệu: {q['id']}", 422)
                    if e.get("quote"):
                        text = " ".join(
                            db.scalars(
                                select(DocumentPage.text).where(
                                    DocumentPage.version_id == version.id,
                                    DocumentPage.page_number >= e["page_start"],
                                    DocumentPage.page_number <= e["page_end"],
                                )
                            ).all()
                        )
                        if " ".join(e["quote"].split()) not in " ".join(text.split()):
                            raise AppError(
                                "evaluation_evidence_invalid",
                                f"Không tìm thấy quote trên trang khai báo: {q['id']}",
                                422,
                            )
    return resolved


def job_usage(db, job_id):
    """Includes interrupted/failing rows as well as successfully exported results."""
    from sqlalchemy import select
    from app.models import UsageEvent

    events = db.scalars(select(UsageEvent).where(UsageEvent.job_id == job_id)).all()
    return {
        "input_tokens": sum(e.input_tokens or 0 for e in events),
        "output_tokens": sum(e.output_tokens or 0 for e in events),
        "cached_tokens": sum(e.cached_tokens or 0 for e in events),
        "successful_provider_responses": sum(not e.cache_hit for e in events),
        "cache_hits": sum(bool(e.cache_hit) for e in events),
        "retries_reported": sum(e.retries or 0 for e in events),
        "estimated_cost_usd": sum(e.estimated_cost_usd for e in events)
        if events and all(e.estimated_cost_usd is not None for e in events)
        else None,
        "note": "Includes events for interrupted questions; reservations also count attempts whose usage was not returned.",
    }


class PersistentEvaluationBudget:
    """Evaluation-owned durable reservation before each real HTTP attempt.

    The provider invokes this in its retry loop. It is independent of the
    per-question budget and is never replaced by a RAG answer call. This
    evaluation orchestrator deliberately checkpoints its own session here.
    Reserved output remains reserved even when the provider uses fewer tokens.
    """

    def __init__(self, db, job, max_tokens, max_calls):
        self.db, self.job = db, job
        self.max_tokens, self.max_calls = max_tokens, max_calls

    def reserve(self, inputs, tools=None, output=None, *, embedding=False):
        from app.tokens import count_embedding_tokens, payload_tokens
        from app.errors import AppError

        inputs_count = (sum(count_embedding_tokens(t) for t in inputs) + 32) if embedding else payload_tokens(inputs)
        amount = inputs_count + (payload_tokens(tools) if tools else 0) + (output or 0)
        old = self.job.checkpoint or {}
        total = old.get("reserved_tokens", 0) + amount
        calls = old.get("reserved_calls", 0) + 1
        if total > self.max_tokens or calls > self.max_calls:
            raise AppError("evaluation_budget_exceeded", "Đã chạm giới hạn tokens/calls evaluation.", 409)
        self.job.checkpoint = {**old, "reserved_tokens": total, "reserved_calls": calls}
        self.job.heartbeat_at = datetime.now(timezone.utc)
        self.db.commit()
        return inputs_count


def run_evaluation_job(job_id: str, provider=None):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import EvaluationRun, EvaluationResult, Job, UsageEvent
    from app.provider import get_provider
    from app.rag import answer
    from app.retrieval import retrieve
    from app.config import settings
    from app.errors import AppError
    from app.security import require_subject

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status in ("ready", "cancelled"):
            return
        run = db.scalar(select(EvaluationRun).where(EvaluationRun.job_id == job_id))
        if not run:
            raise AppError("evaluation_not_found", "Không tìm thấy evaluation run", 404)
        try:
            job.attempts = (job.attempts or 0) + 1
            if job.attempts > settings.job_max_attempts:
                raise AppError("evaluation_retry_exhausted", "Evaluation đã vượt giới hạn tự phục hồi.", 409)
            subject = require_subject(db, job.user_id, job.subject_id)
            config = EvaluationConfig.model_validate(
                {k: v for k, v in run.config.items() if k in EvaluationConfig.model_fields}
            )
            if config.generate_answers or any(m != "lexical" for m in config.modes):
                provider = provider or get_provider()
                provider.job_budget = PersistentEvaluationBudget(db, job, config.max_tokens, config.max_calls)
            mapping = validate_mapping(db, job.user_id, job.subject_id, run.dataset, run.mapping)
            if mapping != run.mapping:
                raise AppError("evaluation_corpus_changed", "Mapping thay đổi; hãy import evaluation mới.", 409)
            corpus_revision = subject.corpus_revision
            if run.config.get("corpus_revision", corpus_revision) != corpus_revision:
                raise AppError("evaluation_corpus_changed", "Kho tài liệu đã thay đổi; hãy import evaluation mới.", 409)
            run.status = job.status = "running"
            run.config = {
                **run.config,
                "corpus_revision": corpus_revision,
                "chat_model": settings.openai_chat_model,
                "context_budget": settings.max_context_tokens,
                "history_budget": settings.max_history_tokens,
                "output_budget": settings.max_output_tokens,
                "prompt_version": getattr(settings, "prompt_version", "v1"),
            }
            db.commit()
            selected = run.dataset[: config.limit]
            complete = {
                (r.question_id, r.mode)
                for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
            }
            for question in selected:
                for mode in config.modes:
                    if (question["id"], mode) in complete:
                        continue
                    db.refresh(subject)
                    if subject.deleted_at or subject.corpus_revision != corpus_revision:
                        raise AppError("evaluation_corpus_changed", "Kho tài liệu đã thay đổi trong lúc đánh giá.", 409)
                    events = db.scalars(select(UsageEvent).where(UsageEvent.job_id == job_id)).all()
                    before_ids = {e.id for e in events}
                    started = time.perf_counter()
                    result = {
                        "question": question["question"],
                        "reference_answer": question["reference_answer"],
                        "answerable": question["answerable"],
                        "tags": question.get("tags", []),
                        "metrics": {},
                        "answer": None,
                        "citations": [],
                        "error": None,
                    }
                    try:
                        if provider is not None and hasattr(provider, "call_budget"):
                            provider.call_budget = None
                        query = "\n".join(question.get("history", [])[-2:] + [question["question"]])
                        target_key = question.get("metadata", {}).get("target_document_key")
                        document_ids = [run.mapping[target_key]["document_id"]] if target_key else None
                        sources = []
                        if not config.generate_answers:
                            sources = retrieve(
                                db,
                                job.user_id,
                                job.subject_id,
                                query,
                                mode=mode,
                                limit=config.top_k,
                                provider=provider,
                                job_id=job_id,
                                document_ids=document_ids,
                            )
                        if config.generate_answers:
                            conversation_id = None
                            # Generate earlier answers from the corpus; never seed with golden answers.
                            for previous in question.get("history", []):
                                historical = answer(
                                    db,
                                    job.user_id,
                                    job.subject_id,
                                    previous,
                                    conversation_id=conversation_id,
                                    retrieval_mode=mode,
                                    provider=provider,
                                    job_id=job_id,
                                    disable_cache=True,
                                    retrieval_limit=config.top_k,
                                    document_ids=document_ids,
                                )
                                conversation_id = historical["conversation_id"]
                            response = answer(
                                db,
                                job.user_id,
                                job.subject_id,
                                question["question"],
                                conversation_id=conversation_id,
                                mode=question.get("chat_mode", "direct"),
                                retrieval_mode=mode,
                                provider=provider,
                                job_id=job_id,
                                disable_cache=True,
                                retrieval_limit=config.top_k,
                                document_ids=document_ids,
                            )
                            result.update(
                                answer=response["answer"],
                                citations=response.get("citations", []),
                                debug=response.get("debug", {}),
                            )
                            sources = response.get("debug", {}).get("retrieved_evidence", sources)
                            refs = [question["reference_answer"]] + question.get("reference_answers", [])
                            result["metrics"]["answer_token_f1"] = max(
                                token_f1(response["answer"], reference) for reference in refs
                            )
                            text = response["answer"].casefold()
                            refusal = bool(response.get("debug", {}).get("refusal")) or refusal_phrase_match(text)
                            result["metrics"]["unanswerable_accuracy"] = (
                                float(refusal) if not question["answerable"] else None
                            )
                            result["metrics"].update(citation_metrics(result["citations"], sources, response["answer"]))
                            traces = response.get("debug", {}).get(
                                "tool_runs", response.get("debug", {}).get("tool_trace", [])
                            )
                            actual = {t.get("name") for t in traces}
                            expected = set(question.get("expected_tools", []))
                            result["metrics"]["tool_selection_recall"] = (
                                len(actual & expected) / len(expected) if expected else None
                            )
                            result["metrics"]["tool_error_rate"] = (
                                sum(t.get("status") in ("failed", "error") for t in traces) / len(traces)
                                if traces
                                else None
                            )
                            result["metrics"]["tool_scope_correctness"] = None
                            result["metrics"]["tool_task_completion"] = None
                        result["metrics"].update(retrieval_metrics(question, sources, run.mapping, config.top_k))
                        result["retrieved_evidence"] = sources
                    except Exception as exc:
                        if not db.is_active:
                            db.rollback()
                        if getattr(exc, "code", "") == "evaluation_budget_exceeded":
                            raise
                        result["error"] = {
                            "code": getattr(exc, "code", type(exc).__name__),
                            "message": getattr(
                                exc, "message", "Evaluation question failed; inspect the error code and worker logs."
                            )[:1000],
                        }
                    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    new_events = [
                        e
                        for e in db.scalars(select(UsageEvent).where(UsageEvent.job_id == job_id))
                        if e.id not in before_ids
                    ]
                    result["usage"] = {
                        "input_tokens": sum(e.input_tokens or 0 for e in new_events),
                        "output_tokens": sum(e.output_tokens or 0 for e in new_events),
                        "cached_tokens": sum(e.cached_tokens or 0 for e in new_events),
                        "provider_calls": sum(1 + (e.retries or 0) for e in new_events if not e.cache_hit),
                        "cache_hits": sum(bool(e.cache_hit) for e in new_events),
                        "estimated_cost_usd": sum(e.estimated_cost_usd for e in new_events)
                        if new_events and all(e.estimated_cost_usd is not None for e in new_events)
                        else None,
                    }
                    db.add(EvaluationResult(run_id=run.id, question_id=question["id"], mode=mode, result=result))
                    complete.add((question["id"], mode))
                    job.progress = {"completed": len(complete), "total": len(selected) * len(config.modes)}
                    job.heartbeat_at = datetime.now(timezone.utc)
                    db.commit()
            subject = require_subject(db, job.user_id, job.subject_id, lock=True)
            db.refresh(subject)
            if subject.corpus_revision != corpus_revision:
                raise AppError(
                    "evaluation_corpus_changed", "Kho tài liệu đã thay đổi trước khi hoàn tất đánh giá.", 409
                )
            run.status = job.status = "ready"
            rows = [
                {"question_id": r.question_id, "mode": r.mode, "result": r.result}
                for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
            ]
            run.report = {
                **build_report(run, rows),
                "budget_reservations": job.checkpoint,
                "job_usage": job_usage(db, job_id),
            }
            job.result = {
                "run_id": run.id,
                "completed": len(rows),
                "errors": sum(bool(r["result"].get("error")) for r in rows),
            }
            db.commit()
        except Exception as exc:
            if not db.is_active:
                db.rollback()
            run.status = job.status = "failed"
            job.error_code = getattr(exc, "code", type(exc).__name__)
            job.error_message = getattr(exc, "message", "Evaluation failed; inspect the error code and worker logs.")[
                :2000
            ]
            rows = [
                {"question_id": r.question_id, "mode": r.mode, "result": r.result}
                for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
            ]
            run.report = {
                **build_report(run, rows),
                "budget_reservations": job.checkpoint,
                "job_usage": job_usage(db, job_id),
                "error": {"code": job.error_code, "message": job.error_message},
            }
            db.commit()

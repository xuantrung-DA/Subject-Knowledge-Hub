"""The only production OpenAI adapter. SDK retries are disabled and bounded here."""

from __future__ import annotations
import json
import random
import logging
import time
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError
from app.config import settings
from app.errors import AppError
from app.models import UsageEvent


def classify_error(exc):
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", {}) or {}
    detail = body.get("error", body) if isinstance(body, dict) else {}
    code = detail.get("code", "") if isinstance(detail, dict) else ""
    if status == 401:
        return "openai_auth", "OpenAI API key không hợp lệ. Kiểm tra cấu hình backend.", False
    if code in ("insufficient_quota", "billing_hard_limit_reached"):
        return "openai_quota", "OpenAI hết quota/ngân sách. Kiểm tra billing của API.", False
    if status == 403:
        return "openai_permission", "Tài khoản OpenAI không được phép dùng model hoặc tài nguyên này.", False
    if status == 404:
        return "openai_model", "Không tìm thấy model hoặc tài khoản chưa được cấp quyền.", False
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError):
        return "openai_timeout", "OpenAI quá thời gian chờ; có thể thử lại.", True
    if status == 429:
        return "openai_rate_limit", "OpenAI đang giới hạn tốc độ. Hãy thử lại sau.", True
    if isinstance(exc, APIConnectionError):
        return "openai_connection", "Không kết nối được OpenAI. Kiểm tra mạng.", True
    if status in (408, 409) or (status is not None and status >= 500):
        return "openai_unavailable", "OpenAI tạm thời không khả dụng.", True
    return "openai_request", "OpenAI từ chối yêu cầu. Kiểm tra model/cấu hình; xem mã lỗi trong log.", False


def _field(obj, key, default=0):
    if obj is None:
        return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int):
    """User-provided dated price config, USD per million tokens; absent => null."""
    try:
        prices = json.loads(getattr(settings, "pricing_json", "{}"))
        item = prices.get("models", prices).get(model)
        if (
            not (prices.get("updated_at") or getattr(settings, "pricing_updated_at", ""))
            or not item
            or "input" not in item
            or "output" not in item
        ):
            return None
        return (
            (input_tokens - cached_tokens) * float(item["input"])
            + cached_tokens * float(item.get("cached_input", item["input"]))
            + output_tokens * float(item["output"])
        ) / 1_000_000
    except (ValueError, TypeError, KeyError):
        return None


class OpenAIProvider:
    def __init__(self, client=None, sleep=time.sleep):
        if client is None and not settings.openai_api_key:
            raise AppError("openai_not_configured", "Chưa cấu hình OPENAI_API_KEY ở backend.", 503)
        self.client = (client.with_options(max_retries=0) if isinstance(client, OpenAI) else client) or OpenAI(
            api_key=settings.openai_api_key, timeout=getattr(settings, "openai_timeout_seconds", 45), max_retries=0
        )
        self.sleep = sleep
        self.max_retries = settings.openai_max_retries
        self.last_usage = None
        self.call_budget = None
        self.job_budget = None

    def _call(
        self,
        fn,
        *,
        kind,
        model,
        user_id,
        subject_id=None,
        job_id=None,
        db=None,
        budget_input=None,
        budget_tools=None,
        budget_output=0,
    ):
        started = time.perf_counter()
        retries = 0
        while True:
            if self.job_budget is not None:
                self.job_budget.reserve(
                    budget_input or [],
                    budget_tools,
                    output=budget_output,
                    **({"embedding": True} if kind == "embedding" else {}),
                )
            if self.call_budget is not None:
                self.call_budget.reserve(
                    budget_input or [],
                    budget_tools,
                    output=budget_output,
                    **({"embedding": True} if kind == "embedding" else {}),
                )
            try:
                response = fn()
                break
            except (APIStatusError, APIConnectionError, TimeoutError) as exc:
                code, message, retryable = classify_error(exc)
                if not retryable or retries >= self.max_retries:
                    # Never claim zero tokens: provider supplied no usage for failed requests.
                    logging.getLogger(__name__).warning(
                        "openai_call_failed",
                        extra={
                            "job_id": job_id,
                            "user_id": user_id,
                            "model": model,
                            "error_code": code,
                            "retries": retries,
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                            "usage_unknown": True,
                        },
                    )
                    raise AppError(code, message, 502) from exc
                retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "0")
                try:
                    delay = min(15, max(float(retry_after), 0.5 * (2**retries)))
                except (ValueError, TypeError):
                    delay = min(8, 0.5 * (2**retries))
                self.sleep(delay + random.uniform(0, 0.25))
                retries += 1
        usage = getattr(response, "usage", None)
        inp = int(_field(usage, "input_tokens", _field(usage, "prompt_tokens", 0)))
        out = int(_field(usage, "output_tokens", 0))
        cached = int(_field(_field(usage, "input_tokens_details", None), "cached_tokens", 0))
        actual_model = getattr(response, "model", None) or model
        latency = int((time.perf_counter() - started) * 1000)
        self.last_usage = dict(
            kind=kind,
            model=actual_model,
            input_tokens=inp,
            output_tokens=out,
            cached_tokens=cached,
            latency_ms=latency,
            retries=retries,
            cache_hit=False,
            estimated_cost_usd=estimate_cost(actual_model, inp, out, cached),
        )
        if db is not None:
            event = UsageEvent(user_id=user_id, subject_id=subject_id, job_id=job_id, **self.last_usage)
            db.add(event)
            db.flush()
            if "rag_usage_ids" in db.info:
                db.info["rag_usage_ids"].append(event.id)
            # flush only  # Caller owns the transaction.
        return response

    def embed(self, texts, *, user_id, subject_id=None, job_id=None, db=None):
        if not texts:
            return []
        response = self._call(
            lambda: self.client.embeddings.create(
                model=settings.openai_embedding_model, dimensions=settings.openai_embedding_dimensions, input=texts
            ),
            kind="embedding",
            model=settings.openai_embedding_model,
            user_id=user_id,
            subject_id=subject_id,
            job_id=job_id,
            db=db,
            budget_input=texts,
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or any(len(v) != settings.openai_embedding_dimensions for v in vectors):
            raise AppError("embedding_dimensions", "Embedding không khớp cấu hình. Cần reindex/migration.", 502)
        return vectors

    def respond(self, input, *, tools=None, user_id, subject_id=None, job_id=None, db=None, max_output_tokens=None):
        kwargs = dict(
            model=settings.openai_chat_model,
            input=input,
            max_output_tokens=max_output_tokens or settings.max_output_tokens,
            store=False,
        )
        if tools:
            kwargs.update(tools=tools, parallel_tool_calls=False)
        response = self._call(
            lambda: self.client.responses.create(**kwargs),
            kind="generation",
            model=settings.openai_chat_model,
            user_id=user_id,
            subject_id=subject_id,
            job_id=job_id,
            db=db,
            budget_input=input,
            budget_tools=tools,
            budget_output=kwargs["max_output_tokens"],
        )
        if getattr(response, "status", "completed") == "incomplete":
            raise AppError("openai_incomplete", "Câu trả lời bị cắt do giới hạn output. Hãy hỏi phạm vi ngắn hơn.", 502)
        if getattr(response, "status", "completed") in ("failed", "cancelled"):
            raise AppError("openai_response_failed", "OpenAI không hoàn tất câu trả lời.", 502)
        return response


def get_provider():
    return OpenAIProvider()

import json
from types import SimpleNamespace
import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from app.config import settings
from app.errors import AppError
from app.provider import OpenAIProvider, classify_error
from app.rag import TOOL_ARGUMENTS, tool_schemas, attach_evidence, _bounded_output, cache_key
from app.retrieval import active_chunks, rrf
from app.tokens import count_tokens, count_embedding_tokens, trim_tokens, TokenBudget, payload_tokens


def test_tokenizer_model_and_unicode_roundtrip():
    text = "Học máy và mô hình tiếng Việt — xác suất! " * 15
    assert count_tokens(text) == len(__import__("tiktoken").encoding_for_model(settings.openai_chat_model).encode(text))
    assert count_embedding_tokens(text) == len(
        __import__("tiktoken").encoding_for_model(settings.openai_embedding_model).encode(text)
    )
    short = trim_tokens(text, 40)
    assert count_tokens(short) <= 40
    assert "\ufffd" not in trim_tokens("normal ASCII", 10)


def test_total_budget_counts_schema_outputs_and_multiple_calls():
    inputs = [{"role": "system", "content": "policy"}, {"role": "user", "content": "hello"}]
    tools = tool_schemas()
    minimum = payload_tokens(inputs) + payload_tokens(tools)
    budget = TokenBudget(total=(minimum + 50) * 2, max_calls=2, per_input=minimum, output=50)
    budget.reserve(inputs, tools)
    budget.reserve(inputs, tools)
    with pytest.raises(AppError, match="giới hạn"):
        budget.reserve(inputs, tools)
    huge = [*inputs, {"type": "function_call_output", "call_id": "x", "output": "long " * 1000}]
    with pytest.raises(AppError) as error:
        TokenBudget(100000, 5, minimum, 50).reserve(huge, tools)
    assert error.value.code == "context_budget_exceeded"


def test_embedding_budget_uses_embedding_tokenizer():
    texts = ["Học mô hình xác suất Việt Nam. " * 10]
    budget = TokenBudget(10000, 4, 10000, 900)
    assert budget.reserve(texts, output=0, embedding=True) == count_embedding_tokens(texts[0]) + 32


def test_tool_schema_scope_not_model_controlled():
    assert len(tool_schemas()) == 5
    for schema in tool_schemas():
        p = schema["parameters"]
        assert schema["strict"] is True and p["additionalProperties"] is False
        assert set(p["required"]) == set(p["properties"])
        assert "default" not in json.dumps(p) and "title" not in json.dumps(p)
        assert not {"subject_id", "user_id", "path", "sql"} & set(p["properties"])
    with pytest.raises(ValidationError):
        TOOL_ARGUMENTS["list_documents"].model_validate_json('{"subject_id":"stolen"}')
    with pytest.raises(ValidationError):
        TOOL_ARGUMENTS["read_document_pages"].model_validate_json('{"document_id":"x","page_start":"1","page_end":2}')


def test_scoped_sql_filters_before_limit_and_uses_active_versions():
    sql = str(
        active_chunks("alice", "math")
        .limit(20)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    for fragment in (
        "subjects.user_id = 'alice'",
        "subjects.id = 'math'",
        "documents.active_version_id = document_versions.id",
        "documents.deleted_at IS NULL",
        "subjects.deleted_at IS NULL",
        "document_versions.status = 'ready'",
        "chunks.embedding_model",
        "document_versions.embedding_dimensions",
    ):
        assert fragment in sql
    assert sql.index("WHERE") < sql.index("LIMIT")


def test_rrf_rank_fusion_deduplicates_and_ties_deterministically():
    ranked = rrf(["a", "a", "b"], ["b", "c"])
    assert ranked[0][0] == "b"
    assert len(ranked) == 3
    assert dict(ranked)["a"] == pytest.approx(1 / 61)


def test_evidence_ids_stay_unique_when_trimmed():
    base = {"chunk_id": "chunk1", "version_id": "v", "page_start": 1, "page_end": 1, "text": "one"}
    registry = {}
    assert attach_evidence([base], registry)[0]["id"] == 1
    assert attach_evidence([base], registry)[0]["id"] == 1
    attach_evidence([{**base, "chunk_id": "chunk2"}], registry)
    registry.pop(1)
    assert attach_evidence([{**base, "chunk_id": "chunk3"}], registry)[0]["id"] == 3


def test_cache_authorization_revision_and_config_key():
    key = cache_key("u", "s", 3, "q", "direct", "dense")
    assert key != cache_key("v", "s", 3, "q", "direct", "dense")
    assert key != cache_key("u", "s", 4, "q", "direct", "dense")
    assert key != cache_key("u", "s", 3, "q", "direct", "hybrid")


def test_tool_output_trim_preserves_json_mapping(monkeypatch):
    monkeypatch.setattr(settings, "max_tool_output_tokens", 400)
    result = _bounded_output({"evidence": [{"id": 1, "text": "text " * 1000}, {"id": 2, "text": "other"}]})
    assert payload_tokens(result) <= 400
    assert result.get("truncated")
    assert isinstance(json.loads(json.dumps(result)), dict)


@pytest.mark.parametrize(
    "status,code,expected,retry",
    [
        (401, "invalid_api_key", "openai_auth", False),
        (403, None, "openai_permission", False),
        (404, None, "openai_model", False),
        (429, "insufficient_quota", "openai_quota", False),
        (429, "rate_limit_exceeded", "openai_rate_limit", True),
        (503, None, "openai_unavailable", True),
    ],
)
def test_provider_error_classification(status, code, expected, retry):
    error = SimpleNamespace(status_code=status, body={"error": {"code": code}})
    classified = classify_error(error)
    assert classified[0] == expected and classified[2] is retry


def test_provider_retry_exhaustion_and_quota_do_not_loop(monkeypatch):
    monkeypatch.setattr(settings, "openai_max_retries", 2)
    attempts = []
    kind = ["rate_limit_exceeded"]

    def handle(request):
        attempts.append(1)
        return httpx.Response(
            429,
            headers={"retry-after": "900"},
            json={"error": {"message": "test", "type": "rate_limit_error", "code": kind[0]}},
        )

    sleeps = []
    provider = OpenAIProvider(
        client=OpenAI(api_key="unit-key", http_client=httpx.Client(transport=httpx.MockTransport(handle))),
        sleep=sleeps.append,
    )
    with pytest.raises(AppError) as exc:
        provider.respond([{"role": "user", "content": "test"}], user_id="u")
    assert exc.value.code == "openai_rate_limit" and len(attempts) == 3
    assert len(sleeps) == 2 and all(x < 16 for x in sleeps)
    kind[0] = "insufficient_quota"
    attempts.clear()
    with pytest.raises(AppError) as exc:
        provider.respond([{"role": "user", "content": "test"}], user_id="u")
    assert exc.value.code == "openai_quota" and len(attempts) == 1


def test_provider_budget_caps_retries_before_an_extra_paid_request(monkeypatch):
    monkeypatch.setattr(settings, "openai_max_retries", 5)
    attempts = []

    def handle(request):
        attempts.append(1)
        return httpx.Response(503, json={"error": {"message": "temporary", "type": "server_error"}})

    provider = OpenAIProvider(
        client=OpenAI(api_key="unit-key", http_client=httpx.Client(transport=httpx.MockTransport(handle))),
        sleep=lambda _: None,
    )
    provider.call_budget = TokenBudget(10000, 2, 5000, 900)
    with pytest.raises(AppError) as exc:
        provider.respond([{"role": "user", "content": "test"}], user_id="u")
    assert exc.value.code == "token_budget_exceeded" and len(attempts) == 2


def test_incomplete_response_is_failure_but_usage_retained():
    def handle(request):
        return httpx.Response(
            200,
            json={
                "id": "incomplete",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4.1-mini",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
                "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
            },
        )

    provider = OpenAIProvider(
        client=OpenAI(api_key="unit-key", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    )
    with pytest.raises(AppError) as exc:
        provider.respond([{"role": "user", "content": "test"}], user_id="u")
    assert exc.value.code == "openai_incomplete" and provider.last_usage["output_tokens"] == 5

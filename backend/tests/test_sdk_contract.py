"""Offline wire-format tests against the pinned official SDK, never network calls."""

import json
import httpx
from openai import OpenAI


def test_official_responses_wire_and_usage():
    from app.provider import OpenAIProvider

    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx.Response(
            200,
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4.1-mini",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_offline",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Nguồn nói 42 [1].", "annotations": []}],
                    }
                ],
                "usage": {
                    "input_tokens": 23,
                    "output_tokens": 9,
                    "total_tokens": 32,
                    "input_tokens_details": {"cached_tokens": 7},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    client = OpenAI(api_key="offline-test-key", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    provider = OpenAIProvider(client=client, sleep=lambda _: None)
    response = provider.respond([{"role": "user", "content": "Test"}], user_id="offline-user")
    assert response.output_text == "Nguồn nói 42 [1]."
    assert captured[0]["store"] is False
    assert "api_key" not in captured[0]
    assert provider.last_usage["input_tokens"] == 23
    assert provider.last_usage["cached_tokens"] == 7
    assert provider.last_usage["output_tokens"] == 9


def test_official_function_call_roundtrip():
    from app.provider import OpenAIProvider

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_tool",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4.1-mini",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc1",
                        "call_id": "call_1",
                        "name": "list_documents",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
            },
        )

    provider = OpenAIProvider(
        client=OpenAI(api_key="offline-test-key", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    )
    schema = {
        "type": "function",
        "name": "list_documents",
        "description": "List scoped documents",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    }
    result = provider.respond([{"role": "user", "content": "List"}], tools=[schema], user_id="offline-user")
    call = result.output[0]
    assert call.type == "function_call"
    assert call.call_id == "call_1"
    provider.respond(
        [
            {"role": "user", "content": "List"},
            call.model_dump(exclude_none=True),
            {"type": "function_call_output", "call_id": call.call_id, "output": "[]"},
        ],
        tools=[schema],
        user_id="offline-user",
    )
    assert requests[1]["input"][2]["call_id"] == "call_1"
    assert requests[1]["parallel_tool_calls"] is False


def test_embeddings_sdk_preserves_input_order(monkeypatch):
    from app.provider import OpenAIProvider
    from app.config import settings

    monkeypatch.setattr(settings, "openai_embedding_dimensions", 3)

    def handle(request):
        payload = json.loads(request.content)
        assert payload["dimensions"] == 3
        assert payload["input"] == ["first", "second"]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0, 1, 0]},
                    {"object": "embedding", "index": 0, "embedding": [1, 0, 0]},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    provider = OpenAIProvider(
        client=OpenAI(api_key="offline-test-key", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    )
    assert provider.embed(["first", "second"], user_id="offline-user") == [[1, 0, 0], [0, 1, 0]]
    assert provider.last_usage["input_tokens"] == 2


def test_provider_timeout_has_finite_retries_and_unknown_usage(monkeypatch):
    import pytest
    from app.config import settings
    from app.errors import AppError
    from app.provider import OpenAIProvider

    monkeypatch.setattr(settings, "openai_max_retries", 2)
    attempts = []

    def handle(request):
        attempts.append(request.url.path)
        raise httpx.ReadTimeout("offline simulated timeout", request=request)

    provider = OpenAIProvider(
        client=OpenAI(api_key="offline-test-key", http_client=httpx.Client(transport=httpx.MockTransport(handle))),
        sleep=lambda _: None,
    )
    with pytest.raises(AppError) as error:
        provider.respond([{"role": "user", "content": "Test timeout"}], user_id="offline-user")
    assert error.value.code == "openai_timeout"
    assert len(attempts) == 3
    assert provider.last_usage is None  # No invented zero-usage successful response.

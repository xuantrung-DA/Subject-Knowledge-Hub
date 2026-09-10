"""Model-token accounting. No character-count approximations in budgets."""

from functools import lru_cache
import json
import tiktoken


@lru_cache(maxsize=8)
def _encoding(model=None):
    if model is None:
        from app.config import settings

        model = settings.openai_chat_model
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str, model=None) -> int:
    return len(_encoding(model).encode(str(text), disallowed_special=()))


def trim_tokens(text: str, limit: int, model=None) -> str:
    return (
        _encoding(model)
        .decode_bytes(_encoding(model).encode(str(text), disallowed_special=())[: max(0, limit)])
        .decode("utf-8", errors="ignore")
    )


def payload_tokens(value) -> int:
    """Conservative serialization count plus per-message framing allowance."""
    return count_tokens(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))) + 32


class TokenBudget:
    """Reserve all requested input/output before a call, including retries.

    Reservations remain charged on errors: a timeout may have been processed
    upstream. Actual provider usage is recorded separately in UsageEvent.
    """

    def __init__(self, total: int, max_calls: int, per_input: int, output: int, retries: int = 0):
        self.total, self.max_calls, self.per_input, self.output = total, max_calls, per_input, output
        self.retries = retries
        self.reserved = self.calls = 0

    def reserve(self, inputs, tools=None, output=None, *, embedding=False) -> int:
        from app.errors import AppError

        input_count = (
            sum(count_embedding_tokens(text) for text in inputs) + 32 if embedding else payload_tokens(inputs)
        ) + (payload_tokens(tools) if tools else 0)
        out = self.output if output is None else output
        cost = (input_count + out) * (self.retries + 1)
        if input_count > self.per_input:
            raise AppError("context_budget_exceeded", "Ngữ cảnh vượt ngân sách; hãy chọn phạm vi trang nhỏ hơn.", 400)
        if self.calls + self.retries + 1 > self.max_calls or self.reserved + cost > self.total:
            raise AppError(
                "token_budget_exceeded",
                "Đã đạt giới hạn tokens/calls. Hãy rút gọn yêu cầu hoặc chọn khoảng trang.",
                400,
            )
        self.calls += self.retries + 1
        self.reserved += cost
        return input_count


def count_embedding_tokens(text: str) -> int:
    from app.config import settings

    return count_tokens(text, settings.openai_embedding_model)

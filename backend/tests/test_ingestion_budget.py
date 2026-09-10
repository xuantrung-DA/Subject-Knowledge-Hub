import pytest
from app.errors import AppError
from app.ingestion import lock_key, reserve_embedding_budget


def test_reserves_retry_upper_bound_before_api_call():
    checkpoint = {"reserved_embedding_tokens": 100, "reserved_embedding_calls": 1}
    result = reserve_embedding_budget(checkpoint, 50, retries=2, max_tokens=1000, max_calls=10)
    assert result == {"reserved_embedding_tokens": 250, "reserved_embedding_calls": 4}
    assert checkpoint["reserved_embedding_tokens"] == 100


@pytest.mark.parametrize("max_tokens,max_calls", [(200, 10), (1000, 3)])
def test_budget_stops_before_tokens_or_calls_exceed_limit(max_tokens, max_calls):
    with pytest.raises(AppError) as caught:
        reserve_embedding_budget(
            {"reserved_embedding_tokens": 100, "reserved_embedding_calls": 1},
            50,
            retries=2,
            max_tokens=max_tokens,
            max_calls=max_calls,
        )
    assert caught.value.code == "ingestion_budget_exceeded"


def test_job_lock_is_stable_scoped_signed_int64():
    assert lock_key("a") == lock_key("a")
    assert lock_key("a") != lock_key("b")
    assert -(2**63) <= lock_key("a") < 2**63

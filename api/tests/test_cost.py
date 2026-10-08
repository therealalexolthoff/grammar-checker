import pytest

from api.app.cost import estimate_cost


def test_estimate_cost_sonnet5():
    cost = estimate_cost("claude-sonnet-5", tokens_in=1000, tokens_out=500, tokens_cached=0)
    assert cost == pytest.approx(1000 * 2.0 / 1e6 + 500 * 10.0 / 1e6)


def test_estimate_cost_with_cached_tokens():
    cost = estimate_cost("claude-sonnet-5", tokens_in=1000, tokens_out=0, tokens_cached=400)
    expected = (600 * 2.0 + 400 * 0.20) / 1e6  # 600 billable at full rate, 400 at the cached rate
    assert cost == pytest.approx(expected)


def test_estimate_cost_unknown_model_raises():
    with pytest.raises(ValueError):
        estimate_cost("unknown-model", 100, 100)


def test_mock_model_is_free():
    assert estimate_cost("mock", 1000, 1000) == 0.0

"""Claude pricing and cost calculation.

Rates confirmed in Phase 0 (docs/ARCHITECTURE.md section 11) for
claude-sonnet-5, the model every operation uses (docs/HARNESS_SPEC.md's
model decision). Dollars per token, derived once from the $/MTok rates,
to avoid repeating the /1e6 division at every call site.
"""

_RATES_PER_MILLION_TOKENS = {
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cached_input": 0.20},
    "mock": {"input": 0.0, "output": 0.0, "cached_input": 0.0},
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
    rates = _RATES_PER_MILLION_TOKENS.get(model)
    if rates is None:
        raise ValueError(f"no pricing known for model {model!r}")
    billable_input = max(0, tokens_in - tokens_cached)
    cost = (
        billable_input * rates["input"] + tokens_cached * rates["cached_input"] + tokens_out * rates["output"]
    ) / 1_000_000
    return cost

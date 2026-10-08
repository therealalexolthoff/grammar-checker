"""Model pricing and cost calculation.

claude-sonnet-5: rates confirmed in Phase 0 (docs/ARCHITECTURE.md
section 11); the model every operation uses (docs/HARNESS_SPEC.md).

gemini-3.8-flash: the fallback when Claude is unavailable. Google charges
an introductory $0.75 / $3.75 per million tokens until 2026-12-31, then
$1.50 / $7.50. The later, higher rates are used here so the spend cap
never undercounts and nothing needs changing in January.

tokens_in includes cached tokens; they are billed at the cached rate.
"""

_RATES_PER_MILLION_TOKENS = {
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cached_input": 0.20},
    "gemini-3.8-flash": {"input": 1.50, "output": 7.50, "cached_input": 0.15},
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

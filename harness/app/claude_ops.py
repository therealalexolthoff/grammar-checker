"""Calls Claude via Vertex, with one automatic repair attempt on
validation failure.

docs/HARNESS_SPEC.md section 8's validation pipeline is: schema parse ->
semantic checks -> one repair attempt -> else error. Schema parse is
enforced by `output_format` itself (Claude's output is constrained to
the given Pydantic model's JSON schema); "semantic checks" is whatever
the caller passes as `validate` (e.g. annotation spans, which need the
source text and so can't be a schema-level constraint).

No `temperature`/`top_p`/`top_k` here: those parameters are removed on
claude-sonnet-5 (a 400 error, not a no-op) - precision comes from the
prompt and the model's default effort, not sampling.
"""

import time
from collections.abc import Callable

from pydantic import BaseModel

from .claude_client import MODEL, get_client

MAX_TOKENS = 4096


def _attempt(client, system_blocks: list[dict], messages: list[dict], output_model: type[BaseModel]):
    return client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=messages,
        output_format=output_model,
    )


def _tokens_in(usage) -> int:
    """All input tokens. Claude reports cached and newly-cached prompt
    tokens separately from input_tokens; api/app/cost.py expects tokens_in
    to include them (it subtracts the cached ones to bill them at the
    lower rate). Newly-cached tokens are billed here at the plain input
    rate - slightly under Vertex's 1.25x cache-write rate, for a prompt
    prefix of about a thousand tokens."""
    return (
        usage.input_tokens
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )


def call_claude(
    *,
    system: str,
    user_content: str | list[dict],
    output_model: type[BaseModel],
    validate: Callable[[BaseModel], None] | None = None,
) -> tuple[BaseModel, dict]:
    """Returns (parsed_result, usage_dict). usage_dict has model, tokens_in,
    tokens_out, tokens_cached, latency_ms - ready to spread into a
    HarnessMeta response. Token counts include both attempts if a repair
    happened, since both are real, billed calls."""
    client = get_client()
    system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": user_content}]

    start = time.monotonic()
    response = _attempt(client, system_blocks, messages, output_model)
    result = response.parsed_output
    tokens_in = _tokens_in(response.usage)
    tokens_out = response.usage.output_tokens
    tokens_cached = getattr(response.usage, "cache_read_input_tokens", 0) or 0

    try:
        if validate is not None:
            validate(result)
    except Exception as exc:
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Your previous answer failed validation: {exc}. Provide a corrected "
                    "answer that fixes this specific problem, keeping everything else the same."
                ),
            }
        )
        response = _attempt(client, system_blocks, messages, output_model)
        result = response.parsed_output
        tokens_in += _tokens_in(response.usage)
        tokens_out += response.usage.output_tokens
        tokens_cached += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        if validate is not None:
            validate(result)  # fails again -> let it raise, only one repair attempt

    return result, {
        "model": MODEL,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "latency_ms": (time.monotonic() - start) * 1000,
    }

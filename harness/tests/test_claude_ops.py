"""Tests the repair-attempt loop in claude_ops.call_claude, with a fake
Anthropic client - no real Vertex/Claude calls happen here."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from harness.app.claude_ops import call_claude


class Thing(BaseModel):
    value: str


def _usage(tokens_in=10, tokens_out=5, cached=0):
    return SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out, cache_read_input_tokens=cached)


def _response(value: str, **usage_kwargs):
    return SimpleNamespace(
        parsed_output=Thing(value=value),
        content=[{"type": "text", "text": value}],
        usage=_usage(**usage_kwargs),
    )


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_call_claude_happy_path_no_repair(monkeypatch):
    fake = FakeClient([_response("ok", tokens_in=100, tokens_out=50, cached=20)])
    monkeypatch.setattr("harness.app.claude_ops.get_client", lambda: fake)

    result, usage = call_claude(system="sys", user_content="hi", output_model=Thing)

    assert result.value == "ok"
    assert usage["model"] == "claude-sonnet-5"
    assert usage["tokens_in"] == 100
    assert usage["tokens_out"] == 50
    assert usage["tokens_cached"] == 20
    assert len(fake.messages.calls) == 1  # no repair needed


def test_call_claude_repairs_once_then_succeeds(monkeypatch):
    fake = FakeClient(
        [
            _response("bad", tokens_in=100, tokens_out=50),
            _response("good", tokens_in=80, tokens_out=40),
        ]
    )
    monkeypatch.setattr("harness.app.claude_ops.get_client", lambda: fake)

    def validate(result: Thing) -> None:
        if result.value != "good":
            raise ValueError("not good enough")

    result, usage = call_claude(
        system="sys", user_content="hi", output_model=Thing, validate=validate
    )

    assert result.value == "good"
    assert len(fake.messages.calls) == 2
    # Both attempts were real, billed calls - tokens accumulate across them.
    assert usage["tokens_in"] == 180
    assert usage["tokens_out"] == 90


def test_call_claude_raises_if_repair_also_fails(monkeypatch):
    fake = FakeClient([_response("bad"), _response("still bad")])
    monkeypatch.setattr("harness.app.claude_ops.get_client", lambda: fake)

    def validate(result: Thing) -> None:
        raise ValueError(f"never good: {result.value}")

    with pytest.raises(ValueError, match="never good: still bad"):
        call_claude(system="sys", user_content="hi", output_model=Thing, validate=validate)

    assert len(fake.messages.calls) == 2  # exactly one repair attempt, not a retry loop

"""Tests gemini_ops.call_gemini (with a fake HTTP layer) and the
Claude -> Gemini fallback in operations._call_model. No real Vertex calls."""

import json

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from harness.app import gemini_ops, operations


class Thing(BaseModel):
    value: str


def _gemini_reply(value: str, prompt=100, answer=20, thoughts=30):
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "thinking...", "thought": True}, {"text": json.dumps({"value": value})}],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": answer, "thoughtsTokenCount": thoughts},
    }


@pytest.fixture
def fake_post(monkeypatch):
    """Replaces the HTTP call. Set `fake_post.replies` to what Vertex
    should return, in order; `fake_post.bodies` records what was sent."""

    class Fake:
        replies: list = []
        bodies: list = []

        def __call__(self, body):
            self.bodies.append(json.loads(json.dumps(body)))  # snapshot, the list grows on repair
            return self.replies.pop(0)

    fake = Fake()
    fake.replies, fake.bodies = [], []
    monkeypatch.setattr(gemini_ops, "_post", fake)
    return fake


def test_gemini_happy_path_counts_thinking_as_output(fake_post):
    fake_post.replies = [_gemini_reply("ok")]
    result, usage = gemini_ops.call_gemini(system="sys", user_content="hi", output_model=Thing)

    assert result.value == "ok"  # the thinking part is not mistaken for the answer
    assert usage["model"] == "gemini-3.8-flash"
    assert usage["tokens_in"] == 100
    assert usage["tokens_out"] == 50  # 20 answer + 30 thinking, both billed as output
    config = fake_post.bodies[0]["generationConfig"]
    assert config["responseJsonSchema"] == Thing.model_json_schema()
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}


def test_gemini_repairs_once_then_succeeds(fake_post):
    fake_post.replies = [_gemini_reply("bad"), _gemini_reply("good")]

    def validate(result):
        if result.value != "good":
            raise ValueError("value must be good")

    result, usage = gemini_ops.call_gemini(system="sys", user_content="hi", output_model=Thing, validate=validate)

    assert result.value == "good"
    assert usage["tokens_in"] == 200  # both calls are billed
    repair = fake_post.bodies[1]["contents"]
    assert repair[1]["role"] == "model"
    assert "value must be good" in repair[2]["parts"][0]["text"]


def test_gemini_raises_if_repair_also_fails(fake_post):
    fake_post.replies = [_gemini_reply("bad"), _gemini_reply("still bad")]

    def validate(result):
        raise ValueError("never good")

    with pytest.raises(ValueError):
        gemini_ops.call_gemini(system="sys", user_content="hi", output_model=Thing, validate=validate)


def test_image_blocks_become_gemini_parts():
    parts = gemini_ops._parts(
        [
            {"type": "text", "text": "Page 1:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}},
        ]
    )
    assert parts == [{"text": "Page 1:"}, {"inlineData": {"mimeType": "image/jpeg", "data": "AAAA"}}]


# ---- fallback ----


def _claude_error(status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid")
    return anthropic.APIStatusError("error", response=httpx.Response(status, request=request), body=None)


def _fail_claude(monkeypatch, error):
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(operations, "call_claude", fail)


@pytest.mark.parametrize("status", [429, 403, 404, 503])
def test_falls_back_to_gemini_when_claude_unavailable(monkeypatch, fake_post, status):
    _fail_claude(monkeypatch, _claude_error(status))
    fake_post.replies = [_gemini_reply("from gemini")]

    result, usage = operations._call_model(system="sys", user_content="hi", output_model=Thing, gemini_thinking="medium")

    assert result.value == "from gemini"
    assert usage["model"] == "gemini-3.8-flash"  # so the API prices it as Gemini
    assert fake_post.bodies[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "medium"}


def test_no_fallback_on_a_bad_request(monkeypatch, fake_post):
    """A 400 means our request is wrong - that bug should surface, not be
    papered over by quietly using another model."""
    _fail_claude(monkeypatch, _claude_error(400))
    with pytest.raises(anthropic.APIStatusError):
        operations._call_model(system="sys", user_content="hi", output_model=Thing)
    assert fake_post.bodies == []


def test_claude_used_when_available(monkeypatch, fake_post):
    monkeypatch.setattr(operations, "call_claude", lambda **kwargs: (Thing(value="claude"), {"model": "claude-sonnet-5"}))
    result, usage = operations._call_model(system="sys", user_content="hi", output_model=Thing)
    assert usage["model"] == "claude-sonnet-5"
    assert fake_post.bodies == []

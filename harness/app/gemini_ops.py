"""Calls Gemini on Vertex - the fallback used when Claude is unavailable
(docs/HARNESS_SPEC.md section 8). Same contract as claude_ops.call_claude:
same prompts, same output schema, one repair attempt on validation
failure, same usage dict.

Plain HTTPS to Vertex's generateContent endpoint, using requests and
google-auth (both already installed with the Anthropic Vertex SDK), so
no extra Google SDK is needed. Authenticated by the harness's service
account, like the Claude calls.
"""

import time
from collections.abc import Callable

import google.auth
import requests
from google.auth.transport.requests import Request
from pydantic import BaseModel

from .config import settings

MODEL = "gemini-3.8-flash"

# Gemini counts its "thinking" against this limit as well as the answer,
# so it is set higher than Claude's MAX_TOKENS.
MAX_OUTPUT_TOKENS = 16384
TIMEOUT_SECONDS = 120.0
# Same "one retry on transient errors" rule as the Claude client.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

_credentials = None


def _access_token() -> str:
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _credentials.valid:
        _credentials.refresh(Request())
    return _credentials.token


def _endpoint() -> str:
    """The same Vertex location as Claude. "us" is the US multi-region
    endpoint (docs/ARCHITECTURE.md section 2), which keeps processing in
    the US."""
    region = settings.vertex_region
    if region == "us":
        host = "aiplatform.us.rep.googleapis.com"
    elif region == "global":
        host = "aiplatform.googleapis.com"
    else:
        host = f"{region}-aiplatform.googleapis.com"
    return (
        f"https://{host}/v1/projects/{settings.vertex_project_id}/locations/{region}"
        f"/publishers/google/models/{MODEL}:generateContent"
    )


def _parts(user_content: str | list[dict]) -> list[dict]:
    """Converts the Claude-style content the prompts build (text blocks and
    base64 image blocks) into Gemini's "parts"."""
    if isinstance(user_content, str):
        return [{"text": user_content}]
    parts = []
    for block in user_content:
        if block["type"] == "text":
            parts.append({"text": block["text"]})
        elif block["type"] == "image":
            source = block["source"]
            parts.append({"inlineData": {"mimeType": source["media_type"], "data": source["data"]}})
        else:
            raise ValueError(f"unsupported content block type {block['type']!r}")
    return parts


def _post(body: dict) -> dict:
    """One generateContent call, retried once on a transient error."""
    for attempt in range(2):
        try:
            response = requests.post(
                _endpoint(),
                json=body,
                headers={"Authorization": f"Bearer {_access_token()}"},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 0:
                continue
            raise
        if response.status_code in _RETRYABLE_STATUS and attempt == 0:
            time.sleep(1)
            continue
        response.raise_for_status()
        return response.json()
    raise AssertionError("unreachable")


def _answer_text(data: dict) -> str:
    """The answer, without the model's thinking parts."""
    candidate = data["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    if not text:
        raise ValueError(f"Gemini returned no answer (finishReason={candidate.get('finishReason')})")
    return text


def _usage(data: dict) -> tuple[int, int, int]:
    """(tokens_in, tokens_out, tokens_cached). Thinking tokens are billed
    as output, so they are counted in tokens_out. tokens_in includes the
    cached tokens, as api/app/cost.py expects."""
    usage = data.get("usageMetadata", {})
    tokens_out = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    return usage.get("promptTokenCount", 0), tokens_out, usage.get("cachedContentTokenCount", 0)


def call_gemini(
    *,
    system: str,
    user_content: str | list[dict],
    output_model: type[BaseModel],
    validate: Callable[[BaseModel], None] | None = None,
    thinking: str = "low",
) -> tuple[BaseModel, dict]:
    """Returns (parsed_result, usage_dict), exactly like call_claude.
    `thinking` is Gemini's thinking level: "low" answers in seconds;
    "medium" takes several times longer but is more careful. (The default,
    "high", took over a minute for one exercise - too slow here.)
    Output is constrained to output_model's JSON schema by Vertex; it is
    still parsed with the Pydantic model, and a parse failure gets the
    same one repair attempt as a failed semantic check."""
    contents = [{"role": "user", "parts": _parts(user_content)}]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": output_model.model_json_schema(),
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingLevel": thinking},
        },
    }

    def check(text: str) -> BaseModel:
        result = output_model.model_validate_json(text)
        if validate is not None:
            validate(result)
        return result

    start = time.monotonic()
    data = _post(body)
    tokens_in, tokens_out, tokens_cached = _usage(data)
    text = _answer_text(data)

    try:
        result = check(text)
    except Exception as exc:  # schema or semantic failure, as in call_claude
        contents.append({"role": "model", "parts": [{"text": text}]})
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"Your previous answer failed validation: {exc}. Provide a corrected "
                            "answer that fixes this specific problem, keeping everything else the same."
                        )
                    }
                ],
            }
        )
        data = _post(body)
        more_in, more_out, more_cached = _usage(data)
        tokens_in, tokens_out, tokens_cached = tokens_in + more_in, tokens_out + more_out, tokens_cached + more_cached
        result = check(_answer_text(data))  # fails again -> let it raise, only one repair attempt

    return result, {
        "model": MODEL,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "latency_ms": (time.monotonic() - start) * 1000,
    }

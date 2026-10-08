"""The Anthropic Vertex client, built once.

Timeouts + one retry on transient errors (docs/HARNESS_SPEC.md section
8) are plain constructor args - the SDK already retries
408/409/429/5xx/connection errors, max_retries=1 asks for exactly one.
"""

from anthropic import AnthropicVertex

from .config import settings

MODEL = "claude-sonnet-5"

_client: AnthropicVertex | None = None


def get_client() -> AnthropicVertex:
    global _client
    if _client is None:
        _client = AnthropicVertex(
            project_id=settings.vertex_project_id,
            region=settings.vertex_region,
            timeout=60.0,
            max_retries=1,
        )
    return _client

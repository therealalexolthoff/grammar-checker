"""Privacy-safe logging for both services.

Rule: logs never contain student text or images (CLAUDE.md). Only ids,
counts, operation names and error *types* are logged - never an error's
message, because messages can quote the text that caused them (a
validation error quotes the input; a span error quotes the span).

log_event writes one JSON line to stdout, which Cloud Run turns into a
structured Cloud Logging entry; the monitoring alerts (infra/monitoring.sh)
match on its "event" field.
"""

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def log_event(event: str, severity: str = "INFO", **fields: str | int | float) -> None:
    """Callers pass ids and counts only - never student text or images."""
    print(json.dumps({"severity": severity, "event": event, **fields}), flush=True)


def catch_unexpected_errors(app: FastAPI) -> None:
    """Turns any error no endpoint handled into a plain 500, logging only
    its type and the request path. Without this, the server would log the
    full traceback, and a traceback can quote student text."""

    @app.middleware("http")
    async def safe_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            log_event("unhandled_error", "ERROR", error_type=type(exc).__name__, path=request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

"""API service entry point.

Health checks, plus the routers built phase by phase - see
docs/BUILD_PLAN.md.
"""

from fastapi import FastAPI, HTTPException

from .harness_client import call_harness_health
from .students import router as students_router

app = FastAPI(title="ESL Tool API")
app.include_router(students_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/harness")
def health_harness() -> dict:
    """Confirms the API can reach the private harness service."""
    try:
        return call_harness_health()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"harness unreachable: {exc}") from exc

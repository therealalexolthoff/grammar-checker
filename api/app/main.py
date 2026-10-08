"""API service entry point.

Health checks, the public login config, the routers built phase by phase
(see docs/BUILD_PLAN.md), and the built React app from web/dist.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .config import settings
from .exercises import router as exercises_router
from .harness_client import call_harness_health
from .lessons import router as lessons_router
from .overview import router as overview_router
from .review import router as review_router
from .students import router as students_router
from .writing import router as writing_router

app = FastAPI(title="ESL Tool API")
app.include_router(students_router)
app.include_router(exercises_router)
app.include_router(review_router)
app.include_router(writing_router)
app.include_router(lessons_router)
app.include_router(overview_router)


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


@app.get("/config")
def public_config() -> dict:
    """What the login screen needs to talk to Identity Platform. No auth:
    the page needs this before anyone has signed in."""
    return {"firebase": {"apiKey": settings.firebase_api_key, "authDomain": settings.firebase_auth_domain}}


# The React app (docs/ARCHITECTURE.md section 2: served from this service).
# Mounted last so every API route above takes precedence. The app does its
# own screen switching without URL paths, so "/" is the only page it needs.
# In local dev the folder doesn't exist and Vite's dev server is used instead.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")

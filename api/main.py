"""Sheetwright AI — application entrypoint.

Routes stay thin: they validate input, resolve a tenant scope, and serialise.
Parsing, mapping, and normalization live in `core/`, and background work in
`worker/`, so the interesting logic is testable without HTTP.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import routes_auth, routes_schemas, routes_uploads
from config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title=settings().app_name,
    version="0.1.0",
    description=(
        "Convert an arbitrary, badly-formatted spreadsheet into a schema you "
        "define — with confidence scores, diagnostics, and a review step for "
        "anything the mapper was unsure about."
    ),
)

# The React dev server runs on a different origin; credentials are required
# because auth is a cookie, not a bearer token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Everything the browser calls lives under /api. Without the prefix, the API's
# `/uploads` collides with the SPA's own `/uploads` history route: a document
# navigation would be answered with JSON. Serving the app and the API from one
# origin in production makes that collision unavoidable, so the namespaces are
# kept apart here rather than papered over in a dev proxy.
API_PREFIX = "/api"

app.include_router(routes_auth.router, prefix=API_PREFIX)
app.include_router(routes_schemas.router, prefix=API_PREFIX)
app.include_router(routes_uploads.router, prefix=API_PREFIX)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness only — deliberately does not touch the database, so a slow
    query cannot make the platform think the process is dead and restart it."""
    return {"status": "ok", "app": settings().app_name}


@app.get("/ready", tags=["meta"])
def ready() -> dict[str, str]:
    """Readiness: can we actually serve? This one *does* check Postgres."""
    from sqlalchemy import text
    from db.base import engine
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")

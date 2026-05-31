"""FastAPI application entry point."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.observability.langfuse_client import (
    get_langfuse,
    healthcheck as langfuse_health,
    shutdown_langfuse,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run once at startup; teardown on shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level, env=settings.app_env)
    settings.ensure_dirs()
    get_langfuse()  # warm the singleton; surfaces config issues at boot

    log.info(
        "ai-job-assistant starting",
        extra={"env": settings.app_env, "debug": settings.debug},
    )
    yield
    log.info("ai-job-assistant shutting down")
    shutdown_langfuse()


app = FastAPI(
    title="AI Job Assistant",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Assign a UUID to each request and bind it to the log context."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response
    finally:
        request_id_var.reset(token)


@app.get("/health")
async def health() -> dict:
    """Liveness + subsystem readiness."""
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
        "subsystems": {
            "langfuse": langfuse_health(),
        },
    }


@app.get("/")
async def root() -> dict:
    return {"app": "ai-job-assistant", "docs": "/docs"}

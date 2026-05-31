"""Langfuse wiring. Safe to import even when Langfuse keys are absent."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_langfuse() -> "Langfuse | None":
    """Return a Langfuse client, or None if not configured.

    Cached so repeated callers share one client (one HTTP session, one batch queue).
    """
    settings = get_settings()
    if not settings.langfuse_enabled:
        log.info("Langfuse disabled (missing keys); LLM calls will not be traced.")
        return None

    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    log.info("Langfuse client initialised", extra={"host": settings.langfuse_host})
    return client


@lru_cache(maxsize=1)
def get_langchain_callback() -> "CallbackHandler | None":
    """Return a LangChain CallbackHandler, or None if Langfuse is disabled.

    Pass into any LangChain Runnable's `config={"callbacks": [handler]}`
    to capture the run as a trace.
    """
    if get_langfuse() is None:
        return None

    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def shutdown_langfuse() -> None:
    """Flush queued events on app shutdown. Safe to call when disabled."""
    client = get_langfuse()
    if client is not None:
        client.flush()
        log.info("Langfuse events flushed.")


def healthcheck() -> dict:
    """Lightweight status used by FastAPI /health."""
    client = get_langfuse()
    if client is None:
        return {"status": "disabled", "reason": "missing LANGFUSE_*_KEY"}
    settings = get_settings()
    return {"status": "enabled", "host": settings.langfuse_host}

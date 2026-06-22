"""Structured logging setup. Call configure_logging() once at startup."""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Set per request (FastAPI middleware) or per agent run.
# Defaults to "-" so logs from startup/CLI still format cleanly.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Anything passed via logger.info("msg", extra={"k": v})
        for k, v in record.__dict__.items():
            if k.startswith("_") or k in _STD_LOG_KEYS:
                continue
            payload[k] = v
        return json.dumps(payload, default=str)


class PrettyFormatter(logging.Formatter):
    """Human-readable single-line format for dev."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        base = f"{record.levelname:<5} [{rid}] {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_STD_LOG_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


def configure_logging(level: str = "INFO", env: str = "dev", stream=sys.stdout) -> None:
    """Install our handlers on the root logger. Idempotent.

    `stream` is where log lines go (default stdout). The MCP server (Phase E)
    speaks JSON-RPC over stdout, so it passes sys.stderr to keep stdout clean.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove pre-existing handlers (e.g. uvicorn's) to avoid double output.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter() if env != "dev" else PrettyFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

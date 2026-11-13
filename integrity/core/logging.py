"""Structured JSON logging on stdout, standard library only.

Rules:
* one JSON object per line;
* correlation id attached automatically inside a request;
* keys that look like secrets are redacted;
* document content must never be logged (callers pass ids/hashes, not text).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from flask import Flask, g, has_request_context, request

from integrity.core.request_context import get_correlation_id

_SENSITIVE_FRAGMENTS = ("authorization", "password", "secret", "token", "api_key", "api-key", "apikey", "pepper", "cookie")
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(f in k for f in _SENSITIVE_FRAGMENTS)


def redact(value: Any, _depth: int = 0) -> Any:
    if _depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {k: (REDACTED if _is_sensitive(str(k)) else redact(v, _depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        cid = get_correlation_id()
        if cid:
            payload["correlation_id"] = cid
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = REDACTED if _is_sensitive(key) else redact(val)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_integrity", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._integrity = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    # Werkzeug's own access log duplicates ours.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def register_access_log(app: Flask) -> None:
    access = logging.getLogger("integrity.access")

    @app.before_request
    def _start_timer() -> None:
        g._t0 = time.perf_counter()

    @app.after_request
    def _log_request(response):
        if has_request_context():
            t0 = getattr(g, "_t0", None)
            access.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.path,  # path only: query strings may carry data
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2) if t0 else None,
                    "client_id": getattr(g, "auth_client_id", None),
                },
            )
        return response

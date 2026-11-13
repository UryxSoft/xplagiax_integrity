"""Per-request correlation id.

An inbound ``X-Request-ID`` is honoured only if it matches a strict pattern,
so callers cannot inject arbitrary content into our logs.
"""

from __future__ import annotations

import re
import uuid

from flask import Flask, g, has_request_context, request

HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def get_correlation_id() -> str | None:
    if has_request_context():
        return getattr(g, "correlation_id", None)
    return None


def register_request_context(app: Flask) -> None:
    @app.before_request
    def _assign_correlation_id() -> None:
        inbound = request.headers.get(HEADER, "")
        g.correlation_id = inbound if _SAFE.match(inbound) else uuid.uuid4().hex

    @app.after_request
    def _echo_correlation_id(response):
        cid = get_correlation_id()
        if cid:
            response.headers[HEADER] = cid
        return response

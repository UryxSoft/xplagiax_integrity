"""Builds adapter clients from application settings (one breaker per process)."""

from __future__ import annotations

import hashlib
import hmac

from flask import Flask

from integrity import __version__
from integrity.integrations.base import CircuitBreaker, Transport, UrllibTransport
from integrity.integrations.crossref import CrossrefClient


def _breaker(app: Flask) -> CircuitBreaker:
    return app.extensions.setdefault("integrity.circuit_breaker", CircuitBreaker())


def fingerprint_key(app: Flask) -> bytes:
    # Derived from the pepper so it is secret, but distinct from the API-key HMAC key.
    pepper = app.config["XI_SETTINGS"].effective_pepper.encode()
    return hmac.new(pepper, b"integrity/api-request-fingerprint/v1", hashlib.sha256).digest()


def crossref_client(app: Flask, transport: Transport | None = None) -> CrossrefClient:
    mailto = app.config["XI_SETTINGS"].crossref_mailto
    ua = f"xplagiax-integrity/{__version__}" + (f" (mailto:{mailto})" if mailto else "")
    return CrossrefClient(transport=transport or UrllibTransport(), fingerprint_key=fingerprint_key(app),
                          breaker=_breaker(app), user_agent=ua)

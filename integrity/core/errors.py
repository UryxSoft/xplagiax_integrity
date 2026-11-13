"""Centralised error model.

Every error leaving the API has the same envelope::

    {"error": {"code": "...", "message": "...", "correlation_id": "..."}}

Internal details (stack traces, SQL, upstream responses) are logged, never
returned.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from integrity.core.request_context import get_correlation_id

log = logging.getLogger("integrity.errors")


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Internal server error."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Valid service credentials are required."


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"
    message = "The authenticated client is not allowed to perform this action."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found."


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"
    message = "The request is invalid."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required dependency is unavailable."


def _envelope(code: str, message: str, status: int):
    body = {"error": {"code": code, "message": message, "correlation_id": get_correlation_id()}}
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def _app_error(exc: AppError):
        level = logging.ERROR if exc.status_code >= 500 else logging.INFO
        log.log(level, "app_error", extra={"error_code": exc.code, "status": exc.status_code})
        return _envelope(exc.code, exc.message, exc.status_code)

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        status = exc.code or 500
        code = (exc.name or "http_error").lower().replace(" ", "_")
        return _envelope(code, exc.description or exc.name or "HTTP error", status)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        log.exception("unhandled_exception", extra={"error_code": "internal_error"})
        return _envelope("internal_error", AppError.message, 500)

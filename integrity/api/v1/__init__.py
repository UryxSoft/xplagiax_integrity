from __future__ import annotations

from flask import Blueprint, Flask

from integrity.api.v1 import auth_context, documents, health, tenants
from integrity.application import errors as app_errors
from integrity.core import errors as http_errors

# Use-case errors -> HTTP errors. Keeps the application layer framework-free.
_MAPPING: dict[type[app_errors.ApplicationError], type[http_errors.AppError]] = {
    app_errors.NotFoundError: http_errors.NotFound,
    app_errors.ForbiddenError: http_errors.PermissionDenied,
    app_errors.IdempotencyConflict: http_errors.Conflict,
    app_errors.ConcurrentModification: http_errors.Conflict,
    app_errors.InvalidInput: http_errors.ValidationFailed,
    app_errors.UnanalysableDocument: http_errors.ValidationFailed,
    app_errors.GoneError: http_errors.Gone,
}


def _to_http(exc: app_errors.ApplicationError) -> http_errors.AppError:
    for app_type, http_type in _MAPPING.items():
        if isinstance(exc, app_type):
            return http_type(exc.message, code=exc.code, details=exc.details)
    return http_errors.AppError()


def register_v1(app: Flask) -> None:
    bp = Blueprint("v1", __name__, url_prefix="/api/v1")
    health.register(bp)
    auth_context.register(bp)
    tenants.register(bp)
    documents.register(bp)

    @bp.errorhandler(app_errors.ApplicationError)
    def _application_error(exc: app_errors.ApplicationError):
        return http_errors.render_app_error(_to_http(exc))

    app.register_blueprint(bp)

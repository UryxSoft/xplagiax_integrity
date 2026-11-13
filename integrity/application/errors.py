"""Use-case errors. Framework-free; the API layer maps them to HTTP responses."""

from __future__ import annotations


class ApplicationError(Exception):
    code = "application_error"

    def __init__(self, message: str, *, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFoundError(ApplicationError):
    code = "not_found"


class ForbiddenError(ApplicationError):
    code = "forbidden"


class IdempotencyConflict(ApplicationError):
    """Same Idempotency-Key reused for a different request."""

    code = "idempotency_conflict"


class ConcurrentModification(ApplicationError):
    code = "concurrent_modification"


class InvalidInput(ApplicationError):
    code = "invalid_document"


class UnanalysableDocument(ApplicationError):
    code = "insufficient_content"


class NotReady(ApplicationError):
    code = "not_ready"


class DataInconsistency(ApplicationError):
    """Stored data no longer reproduces a recorded artefact. Must be investigated."""

    code = "report_mismatch"


class GoneError(ApplicationError):
    code = "gone"

"""Document ingestion endpoints. Contract: docs/API_CONTRACTS.md §3."""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from integrity.application.documents import Actor, add_version, get_document, ingest_document, purge_document
from integrity.application.errors import InvalidInput, UnanalysableDocument
from integrity.core.errors import ValidationFailed
from integrity.domain.ingestion_contract import ContractViolation, InsufficientContent, parse_document
from integrity.infrastructure.db.session import db_session
from integrity.security.auth import current_tenant, require_auth

IDEMPOTENCY_HEADER = "Idempotency-Key"
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _actor() -> Actor:
    t = current_tenant()
    return Actor(client_id=t.client_id, organization_id=t.organization_id, user_id=t.user_id, role=t.user_role)


def _idempotency_key() -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "")
    if not _IDEMPOTENCY.match(key):
        raise ValidationFailed(f"{IDEMPOTENCY_HEADER} header is required ([A-Za-z0-9._:-]{{8,128}}).")
    return key


def _document_id(value: str) -> str:
    if not _ID.match(value):
        raise ValidationFailed("Invalid document id.")
    return value


def _incoming():
    if not request.is_json:
        raise ValidationFailed("Content-Type must be application/json.")
    try:
        return parse_document(request.get_json(silent=True))
    except ContractViolation as exc:
        raise InvalidInput("The document does not match xplagiax.document/v1.", details=exc.problems) from None
    except InsufficientContent as exc:
        raise UnanalysableDocument(exc.reason) from None


def _version_json(v) -> dict:
    return {
        "id": v.id,
        "version_number": v.version_number,
        "content_sha256": v.content_sha256,
        "file_sha256": v.file_sha256,
        "upstream_ref": v.upstream_ref,
        "word_count": v.word_count,
        "char_count": v.char_count,
        "page_count": v.page_count,
        "language": v.language,
        "extraction_status": v.extraction_status.value,
        "limitations": v.limitations,
        "created_at": v.created_at.isoformat(),
    }


def _ingest_response(result):
    body = {"document_id": result.document.id, "version": _version_json(result.version),
            "created": result.created}
    return jsonify(body), (201 if result.created else 200)


def register(bp: Blueprint) -> None:
    @bp.post("/documents")
    @require_auth()
    def create_document():
        key = _idempotency_key()
        incoming = _incoming()
        session = db_session()
        result = ingest_document(session, _actor(), incoming, key)
        session.commit()
        return _ingest_response(result)

    @bp.post("/documents/<document_id>/versions")
    @require_auth()
    def create_version(document_id: str):
        document_id = _document_id(document_id)
        key = _idempotency_key()
        incoming = _incoming()
        session = db_session()
        result = add_version(session, _actor(), document_id, incoming, key)
        session.commit()
        return _ingest_response(result)

    @bp.get("/documents/<document_id>")
    @require_auth()
    def read_document(document_id: str):
        doc, versions = get_document(db_session(), _actor(), _document_id(document_id))
        return jsonify(
            id=doc.id,
            title=doc.title,
            owner_user_id=doc.owner_user_id,
            created_at=doc.created_at.isoformat(),
            retention_until=doc.retention_until.isoformat() if doc.retention_until else None,
            purged_at=doc.purged_at.isoformat() if doc.purged_at else None,
            versions=[_version_json(v) for v in versions],
        )

    @bp.delete("/documents/<document_id>")
    @require_auth()
    def delete_document(document_id: str):
        session = db_session()
        doc, removed = purge_document(session, _actor(), _document_id(document_id))
        session.commit()
        return jsonify(id=doc.id, purged_at=doc.purged_at.isoformat(), contents_removed=removed)

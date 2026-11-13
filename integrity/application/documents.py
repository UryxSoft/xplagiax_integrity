"""Document ingestion and lifecycle use cases.

Callers own the transaction: functions flush but never commit.

Access rule (until the role matrix of SECURITY.md §3.4 is fully implemented):
* no user asserted  -> the platform acts on behalf of the organisation: full access;
* ``member``        -> only documents they own;
* ``reviewer``      -> read every document of the organisation;
* ``org_admin``     -> read and delete every document of the organisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from integrity.application.errors import (
    ConcurrentModification,
    ForbiddenError,
    GoneError,
    IdempotencyConflict,
    NotFoundError,
)
from integrity.core.ids import utcnow
from integrity.domain.enums import ActorType, SourceKind, UserRole
from integrity.domain.ingestion_contract import IncomingDocument
from integrity.infrastructure import content_store
from integrity.infrastructure.db.models import Document, DocumentVersion, Evidence, Organization
from integrity.infrastructure.db.repositories import TenantScope
from integrity.security.audit import record_audit_event


@dataclass(frozen=True)
class Actor:
    """Who is acting, as resolved by authentication."""

    client_id: str
    organization_id: str
    user_id: str | None
    role: UserRole | None


@dataclass(frozen=True)
class IngestResult:
    document: Document
    version: DocumentVersion
    created: bool


def _can_read(actor: Actor, doc: Document) -> bool:
    if actor.user_id is None or actor.role in (UserRole.REVIEWER, UserRole.ORG_ADMIN):
        return True
    return doc.owner_user_id == actor.user_id


def _can_delete(actor: Actor, doc: Document) -> bool:
    if actor.user_id is None or actor.role == UserRole.ORG_ADMIN:
        return True
    return actor.role == UserRole.MEMBER and doc.owner_user_id == actor.user_id


def _visible_document(scope: TenantScope, actor: Actor, document_id: str) -> Document:
    doc = scope.document(document_id)
    # Not readable is reported as not found: do not reveal other users' document ids.
    if doc is None or not _can_read(actor, doc):
        raise NotFoundError("Document not found.")
    return doc


def _replay(scope: TenantScope, key: str, incoming: IncomingDocument, document_id: str | None,
            *, after_conflict: bool = False) -> IngestResult | None:
    existing = scope.version_by_idempotency_key(key, latest=after_conflict)
    if existing is None:
        return None
    if existing.content_sha256 != incoming.content_sha256 or (document_id and existing.document_id != document_id):
        raise IdempotencyConflict("This Idempotency-Key was already used for a different document.")
    document = scope.document(existing.document_id, latest=after_conflict)
    if document is None:  # cannot happen: composite FK guarantees the parent exists in this tenant
        raise ConcurrentModification("Inconsistent replay; retry the request.")
    return IngestResult(document=document, version=existing, created=False)


def _new_version(document: Document, number: int, key: str, incoming: IncomingDocument) -> DocumentVersion:
    return DocumentVersion(
        organization_id=document.organization_id,
        document_id=document.id,
        version_number=number,
        idempotency_key=key,
        upstream_ref=incoming.analysis_ref,
        producer=incoming.producer,
        producer_version=incoming.producer_version,
        source_kind=SourceKind.UPSTREAM_EXTRACTION,
        file_sha256=incoming.file_sha256,
        content_sha256=incoming.content_sha256,
        original_filename=incoming.filename,
        mime_type=incoming.mime_type,
        page_count=incoming.page_count,
        char_count=incoming.char_count,
        word_count=incoming.word_count,
        language=incoming.language,
        extraction_status=incoming.extraction_status,
        extraction_engine=incoming.producer,
        extraction_engine_version=incoming.producer_version,
        pages_failed=list(incoming.pages_failed),
        pages_needing_ocr=list(incoming.pages_needing_ocr),
        limitations=list(incoming.limitations),
    )


def _store(session: Session, scope: TenantScope, document: Document, number: int, key: str,
           incoming: IncomingDocument) -> DocumentVersion:
    version = _new_version(document, number, key, incoming)
    session.add(version)
    session.flush()
    content_store.put(session, organization_id=scope.organization_id, version_id=version.id,
                      text=incoming.text, paragraphs=incoming.paragraphs)
    session.flush()
    return version


def ingest_document(session: Session, actor: Actor, incoming: IncomingDocument, idempotency_key: str) -> IngestResult:
    scope = TenantScope(session, actor.organization_id)
    replay = _replay(scope, idempotency_key, incoming, None)
    if replay:
        return replay

    org = session.get(Organization, actor.organization_id)
    retention_until = utcnow() + timedelta(days=org.retention_days) if org and org.retention_days else None
    try:
        with session.begin_nested():
            document = Document(organization_id=actor.organization_id, owner_user_id=actor.user_id,
                                title=incoming.title, retention_until=retention_until)
            session.add(document)
            session.flush()
            version = _store(session, scope, document, 1, idempotency_key, incoming)
    except IntegrityError:
        # A concurrent request with the same key won the race.
        replay = _replay(scope, idempotency_key, incoming, None, after_conflict=True)
        if replay:
            return replay
        raise
    record_audit_event(session, action="document.ingested", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor.client_id, organization_id=actor.organization_id,
                       target_type="document_version", target_id=version.id,
                       details={"document_id": document.id, "version": 1, "words": incoming.word_count,
                                "extraction_status": incoming.extraction_status.value})
    return IngestResult(document=document, version=version, created=True)


def add_version(session: Session, actor: Actor, document_id: str, incoming: IncomingDocument,
                idempotency_key: str) -> IngestResult:
    scope = TenantScope(session, actor.organization_id)
    document = _visible_document(scope, actor, document_id)
    replay = _replay(scope, idempotency_key, incoming, document.id)
    if replay:
        return replay
    if document.purged_at is not None:
        raise GoneError("The document was deleted; new versions cannot be added.")
    if actor.user_id is not None and actor.role != UserRole.ORG_ADMIN and document.owner_user_id != actor.user_id:
        raise ForbiddenError("Only the owner can add versions to this document.")
    number = scope.next_version_number(document.id)
    try:
        with session.begin_nested():
            version = _store(session, scope, document, number, idempotency_key, incoming)
    except IntegrityError:
        replay = _replay(scope, idempotency_key, incoming, document.id, after_conflict=True)
        if replay:
            return replay
        raise ConcurrentModification("Another version was added at the same time; retry the request.") from None
    record_audit_event(session, action="document.version_added", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor.client_id, organization_id=actor.organization_id,
                       target_type="document_version", target_id=version.id,
                       details={"document_id": document.id, "version": number, "words": incoming.word_count})
    return IngestResult(document=document, version=version, created=True)


def get_document(session: Session, actor: Actor, document_id: str) -> tuple[Document, list[DocumentVersion]]:
    scope = TenantScope(session, actor.organization_id)
    document = _visible_document(scope, actor, document_id)
    return document, scope.versions_of(document.id)


def purge_document(session: Session, actor: Actor, document_id: str) -> tuple[Document, int]:
    """Delete the stored content of every version. Idempotent.

    Metadata, hashes, findings and audit are kept so issued certificates stay
    verifiable (docs/DATA_MODEL.md §5)."""
    scope = TenantScope(session, actor.organization_id)
    document = _visible_document(scope, actor, document_id)
    if not _can_delete(actor, document):
        raise ForbiddenError("You are not allowed to delete this document.")
    if document.purged_at is not None:
        return document, 0
    versions = scope.versions_of(document.id)
    removed = content_store.delete_for_versions(session, organization_id=scope.organization_id,
                                                version_ids=[v.id for v in versions])
    # Evidence excerpts quote the document: purge them too (their hashes stay, so they remain verifiable).
    session.execute(update(Evidence).where(Evidence.organization_id == scope.organization_id,
                                           Evidence.document_version_id.in_([v.id for v in versions]))
                    .values(excerpt_text=None).execution_options(synchronize_session=False))
    document.purged_at = utcnow()
    document.title = None  # titles can be confidential (unfiled inventions)
    record_audit_event(session, action="document.purged", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor.client_id, organization_id=actor.organization_id,
                       target_type="document", target_id=document.id,
                       details={"versions": len(versions), "contents_removed": removed,
                                "user_id": actor.user_id})
    return document, removed

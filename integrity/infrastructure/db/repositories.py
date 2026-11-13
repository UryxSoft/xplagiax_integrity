"""Tenant-scoped data access (audit finding M5).

Every read of tenant-owned data goes through :class:`TenantScope`, which binds
the organisation id once and adds it to every query. Endpoints and use cases
receive a scope, not a raw session lookup by primary key.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from integrity.infrastructure.db.base import Base
from integrity.infrastructure.db.models import Document, DocumentVersion

M = TypeVar("M", bound=Base)


class TenantScope:
    def __init__(self, session: Session, organization_id: str):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.session = session
        self.organization_id = organization_id

    def select(self, model: type[M]) -> Select[tuple[M]]:
        col = getattr(model, "organization_id", None)
        if col is None:
            raise TypeError(f"{model.__name__} is not tenant-owned")
        return select(model).where(col == self.organization_id)

    def get(self, model: type[M], id_: str, *, latest: bool = False) -> M | None:
        """Primary-key lookup that can never return another tenant's row.
        ``latest``: see :meth:`version_by_idempotency_key`."""
        stmt = self.select(model).where(model.id == id_)  # type: ignore[attr-defined]
        return self.session.scalar(stmt.with_for_update(read=True) if latest else stmt)

    # --- documents --------------------------------------------------------------
    def version_by_idempotency_key(self, key: str, *, latest: bool = False) -> DocumentVersion | None:
        """``latest=True`` uses a shared locking read (``LOCK IN SHARE MODE``).

        Required after a unique-key violation: under InnoDB REPEATABLE READ a
        plain SELECT reuses the transaction snapshot and cannot see the row the
        winning request just committed. The lock must be *shared*: the losing
        requests already hold S-locks from the duplicate-key check, and asking
        for X-locks (FOR UPDATE) deadlocks them against each other. Both
        failures were reproduced in tests/test_mysql_integration.py."""
        stmt = self.select(DocumentVersion).where(DocumentVersion.idempotency_key == key)
        if latest:
            stmt = stmt.with_for_update(read=True)
        return self.session.scalar(stmt)

    def versions_of(self, document_id: str) -> list[DocumentVersion]:
        return list(self.session.scalars(
            self.select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)))

    def next_version_number(self, document_id: str) -> int:
        current = self.session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.organization_id == self.organization_id,
                DocumentVersion.document_id == document_id))
        return (current or 0) + 1

    def document(self, document_id: str, *, latest: bool = False) -> Document | None:
        return self.get(Document, document_id, latest=latest)

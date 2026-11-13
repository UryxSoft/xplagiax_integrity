from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from integrity.core.ids import utcnow
from integrity.domain.enums import ActorType
from integrity.infrastructure.db.base import ID, TABLE_ARGS, Base, IdMixin, JSONType, enum_col


class AuditEvent(IdMixin, Base):
    """Append-only security/operations trail. Never contains document content.

    Application code only INSERTs into this table (enforced by convention and
    by the production DB grant documented in SECURITY.md).
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(None, "organization_id", "occurred_at"),
        Index(None, "target_type", "target_id"),
        TABLE_ARGS,
    )

    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    organization_id: Mapped[str | None] = mapped_column(ID, ForeignKey("organizations.id"), default=None)
    actor_type: Mapped[ActorType] = mapped_column(enum_col(ActorType))
    actor_id: Mapped[str | None] = mapped_column(String(64), default=None)
    action: Mapped[str] = mapped_column(String(64))           # e.g. "service_client.created"
    target_type: Mapped[str | None] = mapped_column(String(64), default=None)
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    correlation_id: Mapped[str | None] = mapped_column(String(64), default=None)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from integrity.core.ids import utcnow
from integrity.domain.enums import ClientScope, RecordStatus, UserRole
from integrity.infrastructure.db.base import ID, SHA256, TABLE_ARGS, Base, IdMixin, enum_col, tenant_key


class Organization(IdMixin, Base):
    """Tenant. Identity is owned by xplagiax_appcli2; we mirror its id in external_ref."""

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("external_ref"), TABLE_ARGS)

    external_ref: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[RecordStatus] = mapped_column(enum_col(RecordStatus), default=RecordStatus.ACTIVE)
    # Default retention for uploaded content; NULL = platform default (see SECURITY.md).
    retention_days: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class User(IdMixin, Base):
    """Mirror of an appcli2 user inside one organisation. No credentials stored here."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_ref"),
        tenant_key(),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"), index=True)
    external_ref: Mapped[str] = mapped_column(String(64))
    role: Mapped[UserRole] = mapped_column(enum_col(UserRole), default=UserRole.MEMBER)
    status: Mapped[RecordStatus] = mapped_column(enum_col(RecordStatus), default=RecordStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ServiceClient(IdMixin, Base):
    """Machine credential (e.g. xplagiax_appcli2). Only an HMAC of the key is stored."""

    __tablename__ = "service_clients"
    __table_args__ = (
        UniqueConstraint("key_prefix"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="scope_org_consistency",
        ),
        Index(None, "organization_id"),
        TABLE_ARGS,
    )

    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(SHA256)
    scope: Mapped[ClientScope] = mapped_column(enum_col(ClientScope))
    organization_id: Mapped[str | None] = mapped_column(ID, ForeignKey("organizations.id"), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)

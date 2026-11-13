from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, validates

from integrity.core.ids import utcnow
from integrity.domain.enums import ExtractionStatus, Product, SourceKind
from integrity.infrastructure.db.base import ID, SHA256, TABLE_ARGS, Base, IdMixin, enum_col, tenant_fk, tenant_key


class Project(IdMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        tenant_key(),
        tenant_fk("owner_user_id", "users"),
        Index(None, "organization_id", "created_at"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    owner_user_id: Mapped[str | None] = mapped_column(ID, default=None)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Document(IdMixin, Base):
    """Logical document (e.g. "my thesis"); content lives in DocumentVersion."""

    __tablename__ = "documents"
    __table_args__ = (
        tenant_key(),
        tenant_fk("project_id", "projects"),
        tenant_fk("owner_user_id", "users"),
        Index(None, "organization_id", "created_at"),
        Index(None, "retention_until"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    project_id: Mapped[str | None] = mapped_column(ID, default=None)
    owner_user_id: Mapped[str | None] = mapped_column(ID, default=None)
    title: Mapped[str | None] = mapped_column(String(512), default=None)
    product_hint: Mapped[Product | None] = mapped_column(enum_col(Product), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    retention_until: Mapped[datetime | None] = mapped_column(default=None)
    # Set when content has been purged (retention/deletion). Hashes and audit survive.
    purged_at: Mapped[datetime | None] = mapped_column(default=None)


class DocumentVersion(IdMixin, Base):
    """Immutable snapshot of a document's content as analysed."""

    __tablename__ = "document_versions"
    __table_args__ = (
        tenant_key(),
        tenant_fk("document_id", "documents"),
        UniqueConstraint("document_id", "version_number"),
        # Lets a certificate reference (version, tenant, hash) as one tuple, so the
        # hash it attests is by construction the hash of the analysed version.
        UniqueConstraint("id", "organization_id", "content_sha256"),
        # Deduplication is per tenant ONLY. Cross-tenant dedup would turn the
        # hash index into a "does anyone else have this file?" oracle.
        Index(None, "organization_id", "content_sha256"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    document_id: Mapped[str] = mapped_column(ID)
    version_number: Mapped[int]
    source_kind: Mapped[SourceKind] = mapped_column(enum_col(SourceKind))
    # SHA-256 of the original file bytes, when known (reported by appcli2 or computed on upload).
    file_sha256: Mapped[str | None] = mapped_column(SHA256, default=None)
    # SHA-256 of the analysed text, whitespace-collapsed (integrity.domain.upstream.text_sha256):
    # the same definition the platform uses, so hashes match across systems. Reproducibility anchor.
    content_sha256: Mapped[str] = mapped_column(SHA256)
    # Opaque storage reference (e.g. SeaweedFS fid). Never a filesystem path.
    storage_ref: Mapped[str | None] = mapped_column(String(255), default=None)
    original_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    mime_type: Mapped[str | None] = mapped_column(String(127), default=None)
    byte_size: Mapped[int | None] = mapped_column(default=None)
    page_count: Mapped[int | None] = mapped_column(default=None)
    char_count: Mapped[int | None] = mapped_column(default=None)
    word_count: Mapped[int | None] = mapped_column(default=None)
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    extraction_status: Mapped[ExtractionStatus] = mapped_column(enum_col(ExtractionStatus), default=ExtractionStatus.PENDING)
    extraction_engine: Mapped[str | None] = mapped_column(String(64), default=None)
    extraction_engine_version: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    _IMMUTABLE = ("organization_id", "document_id", "version_number", "source_kind", "file_sha256", "content_sha256")

    @validates(*_IMMUTABLE)
    def _reject_change_after_insert(self, key: str, value):
        """A stored version is the reproducibility anchor of every evaluation
        that used it; its identity and hashes cannot change (audit finding M2)."""
        state = sa_inspect(self)
        if (state.persistent or state.detached) and getattr(self, key) != value:
            raise ValueError(f"document_versions.{key} is immutable")
        return value

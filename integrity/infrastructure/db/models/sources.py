from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from integrity.core.ids import utcnow
from integrity.domain.enums import ApiOutcome, SourceAuthorization
from integrity.infrastructure.db.base import ID, SHA256, TABLE_ARGS, Base, IdMixin, enum_col


class ExternalSource(IdMixin, Base):
    """Provider registry with its *recorded* permissions. Global.

    Each ``allows_*`` flag is tri-state: NULL = unknown (treated as NOT allowed).
    Adapters must refuse operations whose flag is not True.
    """

    __tablename__ = "external_sources"
    __table_args__ = (UniqueConstraint("code"), TABLE_ARGS)

    code: Mapped[str] = mapped_column(String(32))          # e.g. "crossref", "epo_ops"
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(255))
    authorization: Mapped[SourceAuthorization] = mapped_column(
        enum_col(SourceAuthorization), default=SourceAuthorization.UNVERIFIED
    )
    allows_commercial_use: Mapped[bool | None] = mapped_column(default=None)
    allows_storage: Mapped[bool | None] = mapped_column(default=None)
    allows_vector_indexing: Mapped[bool | None] = mapped_column(default=None)
    allows_ai_processing: Mapped[bool | None] = mapped_column(default=None)
    allows_excerpt_display: Mapped[bool | None] = mapped_column(default=None)
    allows_redistribution: Mapped[bool | None] = mapped_column(default=None)
    cache_ttl_seconds: Mapped[int | None] = mapped_column(default=None)
    license_ref: Mapped[str | None] = mapped_column(String(128), default=None)
    attribution_text: Mapped[str | None] = mapped_column(String(512), default=None)
    terms_url: Mapped[str | None] = mapped_column(String(512), default=None)
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    terms_reviewed_by: Mapped[str | None] = mapped_column(String(128), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ApiRequest(IdMixin, Base):
    """Log of every outbound provider call (including refusals and cache hits).

    This is what lets a report say "NO MATCH FOUND IN QUERIED SOURCES" with
    proof of *which* sources were queried, when, and with what outcome.
    The raw query is NOT stored (it may contain confidential claim text);
    only its fingerprint.
    """

    __tablename__ = "api_requests"
    __table_args__ = (
        Index(None, "organization_id", "requested_at"),
        Index(None, "evaluation_id"),
        Index(None, "external_source_id", "request_fingerprint"),
        TABLE_ARGS,
    )

    # Nullable: provider health checks are not tenant-owned.
    organization_id: Mapped[str | None] = mapped_column(ID, ForeignKey("organizations.id"), default=None)
    evaluation_id: Mapped[str | None] = mapped_column(ID, ForeignKey("evaluations.id"), default=None)
    external_source_id: Mapped[str] = mapped_column(ID, ForeignKey("external_sources.id"))
    operation: Mapped[str] = mapped_column(String(64))       # e.g. "doi_lookup", "published_data_search"
    request_fingerprint: Mapped[str] = mapped_column(SHA256)
    outcome: Mapped[ApiOutcome] = mapped_column(enum_col(ApiOutcome))
    http_status: Mapped[int | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    response_sha256: Mapped[str | None] = mapped_column(SHA256, default=None)
    result_count: Mapped[int | None] = mapped_column(default=None)
    adapter_version: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime] = mapped_column(default=utcnow)

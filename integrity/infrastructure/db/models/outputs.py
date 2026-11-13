from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from integrity.core.ids import utcnow
from integrity.domain.enums import CertificateStatus, ReportFormat
from integrity.infrastructure.db.base import ID, SHA256, TABLE_ARGS, Base, IdMixin, enum_col, tenant_fk, tenant_key


class Report(IdMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        tenant_key(),
        tenant_fk("evaluation_id", "evaluations"),
        Index(None, "evaluation_id", "generated_at"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ID)
    engine_version_id: Mapped[str] = mapped_column(ID, ForeignKey("engine_versions.id"))
    format: Mapped[ReportFormat] = mapped_column(enum_col(ReportFormat))
    schema_version: Mapped[str] = mapped_column(String(16))
    content_sha256: Mapped[str] = mapped_column(SHA256)
    storage_ref: Mapped[str | None] = mapped_column(String(255), default=None)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Certificate(IdMixin, Base):
    """A certificate attests that a defined process ran under defined criteria
    on a document with a given hash. It does NOT attest originality, scientific
    validity or institutional acceptance."""

    __tablename__ = "certificates"
    __table_args__ = (
        tenant_key(),
        tenant_fk("evaluation_id", "evaluations"),
        tenant_fk("report_id", "reports"),
        UniqueConstraint("verification_code"),
        UniqueConstraint("evaluation_id"),
        CheckConstraint(
            "status <> 'certified' OR (issued_at IS NOT NULL AND report_id IS NOT NULL)",
            name="certified_requires_issue_and_report",
        ),
        CheckConstraint("status <> 'revoked' OR revoked_at IS NOT NULL", name="revoked_requires_timestamp"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ID)
    report_id: Mapped[str | None] = mapped_column(ID, default=None)
    status: Mapped[CertificateStatus] = mapped_column(enum_col(CertificateStatus), default=CertificateStatus.INCOMPLETE)
    # Public, random, non-sequential. Verification endpoint reveals minimal data.
    verification_code: Mapped[str] = mapped_column(String(32))
    document_content_sha256: Mapped[str] = mapped_column(SHA256)
    criteria_profile: Mapped[str] = mapped_column(String(64))
    criteria_version: Mapped[str] = mapped_column(String(32))
    # Signature scheme pending audit (see ROADMAP stage 7). Nullable until then.
    signature: Mapped[str | None] = mapped_column(String(1024), default=None)
    signing_key_id: Mapped[str | None] = mapped_column(String(64), default=None)
    issued_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    revocation_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

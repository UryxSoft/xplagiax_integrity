from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, validates

from integrity.core.ids import utcnow
from integrity.domain.enums import (
    EvaluationStatus,
    EvidenceKind,
    FindingNature,
    Product,
    Severity,
    StageStatus,
)
from integrity.domain.evaluation_state import assert_transition
from integrity.infrastructure.db.base import (
    ID,
    SHA256,
    TABLE_ARGS,
    Base,
    IdMixin,
    JSONType,
    composite_fk,
    enum_col,
    tenant_fk,
    tenant_key,
)


class EngineVersion(IdMixin, Base):
    """Registry of (engine, version, config) triples. Global, not tenant-owned.

    Every stage, finding and report points at one, so a result can always be
    attributed to the exact code + configuration that produced it.
    """

    __tablename__ = "engine_versions"
    __table_args__ = (UniqueConstraint("engine_name", "version", "config_sha256"), TABLE_ARGS)

    engine_name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    config_sha256: Mapped[str] = mapped_column(SHA256)
    # Model identifiers / external service versions used by the engine, if any.
    components: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Evaluation(IdMixin, Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        tenant_key(),
        tenant_fk("document_version_id", "document_versions"),
        tenant_fk("requested_by_user_id", "users"),
        # Target of certificates' (evaluation, version, tenant) reference.
        UniqueConstraint("id", "document_version_id", "organization_id"),
        # Idempotency: replaying the same request returns the same evaluation.
        UniqueConstraint("organization_id", "idempotency_key"),
        Index(None, "organization_id", "status", "created_at"),
        Index(None, "document_version_id", "product"),
        Index(None, "organization_id", "upstream_ref"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    document_version_id: Mapped[str] = mapped_column(ID)
    requested_by_user_id: Mapped[str | None] = mapped_column(ID, default=None)
    product: Mapped[Product] = mapped_column(enum_col(Product))
    status: Mapped[EvaluationStatus] = mapped_column(enum_col(EvaluationStatus), default=EvaluationStatus.PENDING)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    # The platform's own id for this analysis (its analysis-history id), when there is one.
    upstream_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    # Named, versioned evaluation profile (e.g. institution certification criteria).
    criteria_profile: Mapped[str | None] = mapped_column(String(64), default=None)
    criteria_version: Mapped[str | None] = mapped_column(String(32), default=None)
    # Full effective configuration frozen at creation; its hash is the reproducibility key.
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    config_sha256: Mapped[str] = mapped_column(SHA256)
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    @validates("status")
    def _enforce_lifecycle(self, _key: str, value):
        """Stored evaluations may only move along the domain state machine
        (audit finding M2). Raises integrity.domain InvalidTransition."""
        new = EvaluationStatus(value)
        state = sa_inspect(self)
        if (state.persistent or state.detached) and self.status is not None and new != self.status:
            assert_transition(EvaluationStatus(self.status), new)
        return new

    @validates("document_version_id", "product", "config_sha256", "organization_id")
    def _reject_change_after_insert(self, key: str, value):
        state = sa_inspect(self)
        if (state.persistent or state.detached) and getattr(self, key) != value:
            raise ValueError(f"evaluations.{key} is immutable")
        return value


class EvaluationStage(IdMixin, Base):
    """One pipeline stage of an evaluation. Also the unit of background work:
    workers claim rows by lease (see docs/adr/0005-background-work.md)."""

    __tablename__ = "evaluation_stages"
    __table_args__ = (
        tenant_key(),
        tenant_fk("evaluation_id", "evaluations"),
        UniqueConstraint("evaluation_id", "stage_name"),
        UniqueConstraint("evaluation_id", "sequence"),
        # Target of findings'/results' (stage, evaluation, tenant) reference.
        UniqueConstraint("id", "evaluation_id", "organization_id"),
        Index(None, "status", "not_before", "lease_expires_at"),
        Index(None, "organization_id"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ID)
    stage_name: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int]
    engine_version_id: Mapped[str | None] = mapped_column(ID, ForeignKey("engine_versions.id"), default=None)
    status: Mapped[StageStatus] = mapped_column(enum_col(StageStatus), default=StageStatus.PENDING)
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(64), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    # Earliest time the stage may be claimed again (retry backoff).
    not_before: Mapped[datetime | None] = mapped_column(default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    # Sanitised, bounded error detail. Never raw document text or upstream bodies.
    error_detail: Mapped[str | None] = mapped_column(String(1024), default=None)


class EvaluationResult(IdMixin, Base):
    """Aggregate, machine-readable output of one stage (metrics, coverage, limitations)."""

    __tablename__ = "evaluation_results"
    __table_args__ = (
        tenant_key(),
        tenant_fk("evaluation_id", "evaluations"),
        # The stage must belong to this same evaluation and tenant (audit finding M1).
        composite_fk(["stage_id", "evaluation_id", "organization_id"], "evaluation_stages",
                     ["id", "evaluation_id", "organization_id"]),
        UniqueConstraint("stage_id"),
        Index(None, "organization_id"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ID)
    stage_id: Mapped[str] = mapped_column(ID)
    engine_version_id: Mapped[str] = mapped_column(ID, ForeignKey("engine_versions.id"))
    schema_version: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    payload_sha256: Mapped[str] = mapped_column(SHA256)
    # Explicit limitations of this stage's result (language unsupported, source unavailable...).
    limitations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Finding(IdMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        tenant_key(),
        tenant_fk("evaluation_id", "evaluations"),
        # The stage must belong to this same evaluation and tenant (audit finding M1).
        composite_fk(["stage_id", "evaluation_id", "organization_id"], "evaluation_stages",
                     ["id", "evaluation_id", "organization_id"]),
        Index(None, "organization_id"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        # A confidence value may only be shown as such if it is calibrated.
        CheckConstraint("confidence IS NULL OR confidence_calibrated IS NOT NULL", name="confidence_has_calibration_flag"),
        Index(None, "evaluation_id", "severity"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ID)
    stage_id: Mapped[str] = mapped_column(ID)
    engine_version_id: Mapped[str] = mapped_column(ID, ForeignKey("engine_versions.id"))
    category: Mapped[str] = mapped_column(String(64))       # product-specific taxonomy code
    nature: Mapped[FindingNature] = mapped_column(enum_col(FindingNature))
    severity: Mapped[Severity] = mapped_column(enum_col(Severity))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(128))         # identifiable method, e.g. "winnowing-k13-w4"
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), default=None)
    confidence_calibrated: Mapped[bool | None] = mapped_column(default=None)
    # {page, section, block_id, char_start, char_end} in the analysed DocumentVersion.
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    limitations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    recommendation: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Evidence(IdMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        tenant_key(),
        tenant_fk("finding_id", "findings"),
        tenant_fk("document_version_id", "document_versions"),
        # Evidence may only cite provider calls made for its own tenant (audit finding A1).
        tenant_fk("api_request_id", "api_requests"),
        Index(None, "finding_id"),
        Index(None, "organization_id"),
        TABLE_ARGS,
    )

    organization_id: Mapped[str] = mapped_column(ID, ForeignKey("organizations.id"))
    finding_id: Mapped[str] = mapped_column(ID)
    kind: Mapped[EvidenceKind] = mapped_column(enum_col(EvidenceKind))
    document_version_id: Mapped[str | None] = mapped_column(ID, default=None)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    # Excerpts are bounded and stored only when the source's terms allow it.
    # The hash is always stored so an excerpt can be re-verified after purge.
    excerpt_text: Mapped[str | None] = mapped_column(Text, default=None)
    excerpt_sha256: Mapped[str | None] = mapped_column(SHA256, default=None)
    external_source_id: Mapped[str | None] = mapped_column(ID, ForeignKey("external_sources.id"), default=None)
    external_identifier: Mapped[str | None] = mapped_column(String(255), default=None)  # DOI, publication number...
    external_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    api_request_id: Mapped[str | None] = mapped_column(ID, default=None)
    retrieved_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

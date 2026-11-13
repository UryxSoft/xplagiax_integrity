"""Evaluation use cases. Callers own the transaction (flush, never commit).

Access follows the document: whoever can read the document version can
evaluate it and read the evaluation (application/documents.py rules).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from integrity.application.documents import Actor, _visible_document
from integrity.application.errors import GoneError, IdempotencyConflict, InvalidInput, NotFoundError
from integrity.core.ids import utcnow
from integrity.domain.enums import ActorType, EvaluationStatus, Product, StageStatus
from integrity.domain.evaluation_state import TERMINAL
from integrity.domain.workflows import WORKFLOWS, StageSpec, config_hash, config_snapshot, engine_config_hash
from integrity.infrastructure.db.models import (
    DocumentVersion,
    EngineVersion,
    Evaluation,
    EvaluationResult,
    EvaluationStage,
)
from integrity.infrastructure.db.repositories import TenantScope
from integrity.security.audit import record_audit_event


@dataclass(frozen=True)
class CreateResult:
    evaluation: Evaluation
    created: bool


def engine_version_for(session: Session, spec: StageSpec) -> EngineVersion:
    """Get or create the registry row for this engine version (race-safe)."""
    cfg = engine_config_hash(spec)

    def find(latest: bool = False):
        stmt = select(EngineVersion).where(EngineVersion.engine_name == spec.engine,
                                           EngineVersion.version == spec.engine_version,
                                           EngineVersion.config_sha256 == cfg)
        return session.scalar(stmt.with_for_update(read=True) if latest else stmt)

    row = find()
    if row is not None:
        return row
    try:
        with session.begin_nested():
            row = EngineVersion(engine_name=spec.engine, version=spec.engine_version, config_sha256=cfg)
            session.add(row)
            session.flush()
        return row
    except IntegrityError:
        row = find(latest=True)
        if row is None:
            raise
        return row


def _replay(scope: TenantScope, key: str, version_id: str, product: Product, latest: bool = False):
    stmt = scope.select(Evaluation).where(Evaluation.idempotency_key == key)
    existing = scope.session.scalar(stmt.with_for_update(read=True) if latest else stmt)
    if existing is None:
        return None
    if existing.document_version_id != version_id or existing.product != product:
        raise IdempotencyConflict("This Idempotency-Key was already used for a different evaluation.")
    return CreateResult(existing, False)


def create_evaluation(session: Session, actor: Actor, *, document_version_id: str, product: str,
                      idempotency_key: str, criteria_profile: str | None = None,
                      criteria_version: str | None = None) -> CreateResult:
    try:
        product_enum = Product(product)
    except ValueError:
        raise InvalidInput(f"product must be one of {[p.value for p in Product]}.") from None
    scope = TenantScope(session, actor.organization_id)
    version = scope.get(DocumentVersion, document_version_id)
    if version is None:
        raise NotFoundError("Document version not found.")
    document = _visible_document(scope, actor, version.document_id)  # 404 if the actor cannot read it
    replay = _replay(scope, idempotency_key, version.id, product_enum)
    if replay:
        return replay
    if document.purged_at is not None:
        raise GoneError("The document was deleted; it cannot be evaluated.")

    snapshot = config_snapshot(product_enum, criteria_profile, criteria_version)
    specs = WORKFLOWS[product_enum]
    engines = [engine_version_for(session, s) for s in specs]
    try:
        with session.begin_nested():
            ev = Evaluation(organization_id=actor.organization_id, document_version_id=version.id,
                            requested_by_user_id=actor.user_id, product=product_enum,
                            status=EvaluationStatus.QUEUED, idempotency_key=idempotency_key,
                            upstream_ref=version.upstream_ref, criteria_profile=criteria_profile,
                            criteria_version=criteria_version, config_snapshot=snapshot,
                            config_sha256=config_hash(snapshot))
            session.add(ev)
            session.flush()
            for seq, (spec, eng) in enumerate(zip(specs, engines), start=1):
                session.add(EvaluationStage(organization_id=actor.organization_id, evaluation_id=ev.id,
                                            stage_name=spec.name, sequence=seq, engine_version_id=eng.id,
                                            max_attempts=spec.max_attempts))
            session.flush()
    except IntegrityError:
        replay = _replay(scope, idempotency_key, version.id, product_enum, latest=True)
        if replay:
            return replay
        raise
    record_audit_event(session, action="evaluation.created", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor.client_id, organization_id=actor.organization_id,
                       target_type="evaluation", target_id=ev.id,
                       details={"product": product_enum.value, "document_version_id": version.id,
                                "stages": len(specs), "user_id": actor.user_id})
    return CreateResult(ev, True)


def _visible_evaluation(scope: TenantScope, actor: Actor, evaluation_id: str) -> Evaluation:
    ev = scope.get(Evaluation, evaluation_id)
    if ev is None:
        raise NotFoundError("Evaluation not found.")
    version = scope.get(DocumentVersion, ev.document_version_id)
    _visible_document(scope, actor, version.document_id)  # same visibility as the document
    return ev


@dataclass(frozen=True)
class EvaluationView:
    evaluation: Evaluation
    stages: list[EvaluationStage]
    results: dict[str, EvaluationResult]  # by stage id


def get_evaluation(session: Session, actor: Actor, evaluation_id: str) -> EvaluationView:
    scope = TenantScope(session, actor.organization_id)
    ev = _visible_evaluation(scope, actor, evaluation_id)
    stages = list(session.scalars(scope.select(EvaluationStage).where(EvaluationStage.evaluation_id == ev.id)
                                  .order_by(EvaluationStage.sequence)))
    results = {r.stage_id: r for r in session.scalars(
        scope.select(EvaluationResult).where(EvaluationResult.evaluation_id == ev.id))}
    return EvaluationView(ev, stages, results)


def cancel_evaluation(session: Session, actor: Actor, evaluation_id: str) -> Evaluation:
    """Idempotent. Pending stages are cancelled now; a running stage finishes
    but its result is discarded and no further stage starts."""
    scope = TenantScope(session, actor.organization_id)
    ev = _visible_evaluation(scope, actor, evaluation_id)
    if ev.status in TERMINAL:
        return ev
    ev.status = EvaluationStatus.CANCELLED
    ev.finished_at = utcnow()
    for st in session.scalars(scope.select(EvaluationStage).where(
            EvaluationStage.evaluation_id == ev.id, EvaluationStage.status == StageStatus.PENDING)):
        st.status = StageStatus.CANCELLED
        st.finished_at = ev.finished_at
    record_audit_event(session, action="evaluation.cancelled", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor.client_id, organization_id=actor.organization_id,
                       target_type="evaluation", target_id=ev.id, details={"user_id": actor.user_id})
    return ev

"""Background stage runner (docs/adr/0005-background-work.md).

``evaluation_stages`` is the queue. One iteration:

1. ``reap_expired``: stages whose lease expired with no attempts left are failed.
2. ``claim_next``: atomically take one runnable stage. Runnable means: pending
   and past its ``not_before`` (or running with an expired lease, i.e. its
   worker died), attempts left, its evaluation still queued/processing, and no
   earlier stage of the same evaluation still pending or running. On MySQL the
   candidate read uses ``FOR UPDATE SKIP LOCKED``; the claim itself is a
   conditional UPDATE, correct on every engine.
3. ``execute``: load inputs, run the engine **outside any transaction**.
4. ``finish``: in a new transaction, only if this worker still holds the lease,
   store the result (or schedule a retry / fail), then roll the evaluation
   status forward. A cancelled evaluation discards the result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import timedelta

from flask import Flask
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from integrity.core.ids import utcnow
from integrity.domain.enums import EvaluationStatus, EvidenceKind, StageStatus
from integrity.engines.base import StageFailure, StageInput, StageOutput
from integrity.engines.base import PreviousVersion
from integrity.engines.registry import ENGINES, NEEDS_PREVIOUS
from integrity.infrastructure import content_store
from integrity.infrastructure.content_store import ContentIntegrityError
from integrity.infrastructure.db.models import (
    DocumentVersion,
    EngineVersion,
    Evaluation,
    EvaluationResult,
    EvaluationStage,
    Evidence,
    Finding,
)
from integrity.infrastructure.db.session import session_scope

log = logging.getLogger("integrity.worker")

DONE = (StageStatus.SUCCEEDED, StageStatus.SKIPPED, StageStatus.FAILED, StageStatus.CANCELLED)
ACTIVE_EVALUATION = (EvaluationStatus.QUEUED, EvaluationStatus.PROCESSING)
RESULT_SCHEMA = "1"
_MAX_DETAIL = 1024


def new_worker_id() -> str:
    return f"{socket.gethostname()[:32]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class Claim:
    stage_id: str
    evaluation_id: str
    organization_id: str
    worker_id: str
    attempt: int
    lease_s: int = 300


def _runnable(now):
    st = EvaluationStage
    earlier = aliased(EvaluationStage)
    blocked = exists().where(earlier.evaluation_id == st.evaluation_id, earlier.sequence < st.sequence,
                             earlier.status.in_((StageStatus.PENDING, StageStatus.RUNNING)))
    claimable = or_(
        and_(st.status == StageStatus.PENDING, or_(st.not_before.is_(None), st.not_before <= now)),
        and_(st.status == StageStatus.RUNNING, st.lease_expires_at < now),
    )
    return and_(claimable, st.attempt < st.max_attempts, ~blocked)


def reap_expired(session: Session, now=None) -> int:
    """Fail stages whose worker died on the last allowed attempt."""
    now = now or utcnow()
    rows = list(session.scalars(select(EvaluationStage).where(
        EvaluationStage.status == StageStatus.RUNNING, EvaluationStage.lease_expires_at < now,
        EvaluationStage.attempt >= EvaluationStage.max_attempts)))
    for st in rows:
        _fail(session, st, "lease_expired", "The worker running this stage stopped responding.", now)
    return len(rows)


def claim_next(session: Session, worker_id: str, lease_s: int, now=None) -> Claim | None:
    now = now or utcnow()
    st = EvaluationStage
    q = (select(st.id).join(Evaluation, and_(Evaluation.id == st.evaluation_id,
                                             Evaluation.organization_id == st.organization_id))
         .where(_runnable(now), Evaluation.status.in_(ACTIVE_EVALUATION))
         .order_by(st.not_before, st.id).limit(5))
    if session.get_bind().dialect.name == "mysql":
        q = q.with_for_update(skip_locked=True, of=st)
    for stage_id in session.scalars(q).all():
        res = session.execute(
            update(st).where(st.id == stage_id, _runnable(now))
            .values(status=StageStatus.RUNNING, lease_owner=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_s), attempt=st.attempt + 1,
                    started_at=func.coalesce(st.started_at, now), not_before=None)
            .execution_options(synchronize_session=False))
        if res.rowcount == 1:
            stage = session.get(EvaluationStage, stage_id, populate_existing=True)
            ev = session.get(Evaluation, stage.evaluation_id)
            if ev.status == EvaluationStatus.QUEUED:
                ev.status = EvaluationStatus.PROCESSING
                ev.started_at = ev.started_at or now
            return Claim(stage.id, stage.evaluation_id, stage.organization_id, worker_id, stage.attempt, lease_s)
    return None


def _owned_stage(session: Session, claim: Claim) -> EvaluationStage | None:
    return session.scalar(select(EvaluationStage).where(
        EvaluationStage.id == claim.stage_id, EvaluationStage.organization_id == claim.organization_id,
        EvaluationStage.status == StageStatus.RUNNING, EvaluationStage.lease_owner == claim.worker_id
    ).with_for_update())


def _optional(ev: Evaluation, stage_name: str) -> bool:
    for s in (ev.config_snapshot or {}).get("stages", []):
        if s.get("name") == stage_name:
            return bool(s.get("optional"))
    return False


def _finalize(session: Session, ev: Evaluation, now) -> None:
    stages = list(session.scalars(select(EvaluationStage).where(
        EvaluationStage.evaluation_id == ev.id, EvaluationStage.organization_id == ev.organization_id)
        .order_by(EvaluationStage.sequence)))
    if any(s.status not in DONE for s in stages) or ev.status not in ACTIVE_EVALUATION:
        return
    if ev.status == EvaluationStatus.QUEUED:
        ev.status = EvaluationStatus.PROCESSING
    required_failed = [s for s in stages if s.status == StageStatus.FAILED and not _optional(ev, s.stage_name)]
    if required_failed:
        ev.status, ev.error_code = EvaluationStatus.FAILED, required_failed[0].error_code
    elif all(s.status == StageStatus.SUCCEEDED for s in stages):
        ev.status = EvaluationStatus.COMPLETED
    else:
        ev.status = EvaluationStatus.PARTIALLY_COMPLETED
    ev.finished_at = now


def _fail(session: Session, st: EvaluationStage, code: str, detail: str, now) -> None:
    st.status, st.error_code, st.error_detail = StageStatus.FAILED, code[:64], detail[:_MAX_DETAIL]
    st.finished_at, st.lease_owner, st.lease_expires_at = now, None, None
    ev = session.get(Evaluation, st.evaluation_id)
    if not _optional(ev, st.stage_name):
        # Later stages cannot run on a failed required stage.
        for later in session.scalars(select(EvaluationStage).where(
                EvaluationStage.evaluation_id == st.evaluation_id, EvaluationStage.sequence > st.sequence,
                EvaluationStage.status == StageStatus.PENDING)):
            later.status, later.error_code, later.finished_at = StageStatus.SKIPPED, "previous_stage_failed", now
    session.flush()
    _finalize(session, ev, now)


def _load_input(session: Session, claim: Claim) -> tuple[StageInput, EngineVersion, str]:
    st = session.get(EvaluationStage, claim.stage_id)
    ev = session.get(Evaluation, claim.evaluation_id)
    version = session.get(DocumentVersion, ev.document_version_id)
    engine = session.get(EngineVersion, st.engine_version_id)
    stored = content_store.get(session, organization_id=claim.organization_id, version_id=version.id)
    if stored is None:
        raise StageFailure("content_unavailable", "The document content was purged or is missing.")
    previous = None
    if (engine.engine_name, engine.version) in NEEDS_PREVIOUS and version.version_number > 1:
        prev = session.scalar(select(DocumentVersion).where(
            DocumentVersion.organization_id == claim.organization_id,
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.version_number < version.version_number)
            .order_by(DocumentVersion.version_number.desc()).limit(1))
        if prev is not None:
            pc = content_store.get(session, organization_id=claim.organization_id, version_id=prev.id)
            previous = PreviousVersion(prev.version_number, prev.content_sha256,
                                       pc.text if pc else None, pc.paragraphs if pc else [])
    return (StageInput(text=stored.text, paragraphs=stored.paragraphs,
                       expected_content_sha256=version.content_sha256, language=version.language,
                       extraction_status=version.extraction_status.value,
                       upstream_limitations=tuple(version.limitations or ()), previous=previous),
            engine, st.stage_name)


_MAX_EXCERPT = 1000


def _store_findings(session: Session, st: EvaluationStage, ev: Evaluation, engine_version_id: str,
                    output: StageOutput, now) -> None:
    from decimal import Decimal

    for fd in output.findings:
        f = Finding(organization_id=st.organization_id, evaluation_id=st.evaluation_id, stage_id=st.id,
                    engine_version_id=engine_version_id, category=fd.category[:64], nature=fd.nature,
                    severity=fd.severity, title=fd.title[:255], description=fd.description, method=fd.method[:128],
                    confidence=Decimal(str(round(fd.confidence, 4))) if fd.confidence is not None else None,
                    confidence_calibrated=fd.confidence_calibrated, location=fd.location,
                    limitations=list(fd.limitations), recommendation=fd.recommendation)
        session.add(f)
        session.flush()
        for ed in fd.evidence:
            excerpt = ed.excerpt[:_MAX_EXCERPT] if ed.excerpt else None
            session.add(Evidence(
                organization_id=st.organization_id, finding_id=f.id, kind=ed.kind,
                document_version_id=ev.document_version_id if ed.kind == EvidenceKind.DOCUMENT_EXCERPT else None,
                locator=ed.locator, excerpt_text=excerpt,
                excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest() if excerpt else None,
                external_identifier=ed.external_identifier, external_url=ed.external_url,
                retrieved_at=now if ed.kind == EvidenceKind.EXTERNAL_RECORD else None))


class LeaseKeeper:
    """Renews the stage lease every ``lease_s / 3`` seconds while an engine runs,
    so a long stage is not mistaken for an abandoned one. If the lease is lost
    (another worker took over after a stall), renewal stops and the final
    write is refused by ``_owned_stage``."""

    def __init__(self, app: Flask, claim: Claim):
        self.app, self.claim = app, claim
        self.interval = max(1.0, claim.lease_s / 3)
        self._stop = threading.Event()
        self.renewals = 0
        self.lost = False
        self._thread = threading.Thread(target=self._run, name=f"lease-{claim.stage_id[:8]}", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=self.interval + 5)

    def _run(self) -> None:
        st = EvaluationStage
        while not self._stop.wait(self.interval):
            try:
                with session_scope(self.app) as s:
                    res = s.execute(update(st).where(
                        st.id == self.claim.stage_id, st.lease_owner == self.claim.worker_id,
                        st.status == StageStatus.RUNNING)
                        .values(lease_expires_at=utcnow() + timedelta(seconds=self.claim.lease_s))
                        .execution_options(synchronize_session=False))
                if res.rowcount != 1:
                    self.lost = True
                    log.warning("stage_lease_lost_during_run", extra={"stage_id": self.claim.stage_id})
                    return
                self.renewals += 1
            except Exception:  # a transient DB error must not kill the stage; retry next tick
                log.exception("stage_lease_renewal_failed", extra={"stage_id": self.claim.stage_id})


def _backoff(attempt: int) -> int:
    return min(30 * 2 ** (attempt - 1), 900)


def execute(app: Flask, claim: Claim) -> StageStatus:
    """Run one claimed stage end to end. Returns the stage's resulting status."""
    output: StageOutput | None = None
    failure: StageFailure | None = None
    engine_version_id = None
    try:
        with session_scope(app) as s:
            inp, engine, _ = _load_input(s, claim)
            engine_version_id = engine.id
            fn = ENGINES.get((engine.engine_name, engine.version))
        if fn is None:
            raise StageFailure("engine_not_available",
                               f"Engine {engine.engine_name} v{engine.version} is not installed in this worker.")
        with LeaseKeeper(app, claim):
            output = fn(inp)  # no transaction open while the engine runs
    except StageFailure as exc:
        failure = exc
    except ContentIntegrityError:
        failure = StageFailure("content_integrity_error", "Stored content failed its integrity check.")
    except Exception as exc:  # engine bug: retry, but never leak details or document text
        log.exception("stage_engine_error", extra={"stage_id": claim.stage_id})
        failure = StageFailure("internal_error", type(exc).__name__, retryable=True)
    finally:
        inp = None  # noqa: F841 - release document text before the next stage

    with session_scope(app) as s:
        now = utcnow()
        st = _owned_stage(s, claim)
        if st is None:
            log.warning("stage_lease_lost", extra={"stage_id": claim.stage_id, "worker": claim.worker_id})
            return StageStatus.RUNNING
        ev = s.get(Evaluation, st.evaluation_id)
        if ev.status == EvaluationStatus.CANCELLED:
            st.status, st.finished_at, st.lease_owner, st.lease_expires_at = StageStatus.CANCELLED, now, None, None
            return StageStatus.CANCELLED
        if failure is None:
            payload_json = json.dumps(output.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            s.add(EvaluationResult(organization_id=st.organization_id, evaluation_id=st.evaluation_id,
                                   stage_id=st.id, engine_version_id=engine_version_id, schema_version=RESULT_SCHEMA,
                                   payload=output.payload, payload_sha256=hashlib.sha256(payload_json.encode()).hexdigest(),
                                   limitations=list(output.limitations)))
            _store_findings(s, st, ev, engine_version_id, output, now)
            st.status, st.finished_at, st.lease_owner, st.lease_expires_at = StageStatus.SUCCEEDED, now, None, None
            st.error_code = st.error_detail = None
            s.flush()
            _finalize(s, ev, now)
            return StageStatus.SUCCEEDED
        if failure.retryable and st.attempt < st.max_attempts:
            st.status, st.lease_owner, st.lease_expires_at = StageStatus.PENDING, None, None
            st.not_before = now + timedelta(seconds=_backoff(st.attempt))
            st.error_code, st.error_detail = failure.code[:64], failure.detail[:_MAX_DETAIL]
            return StageStatus.PENDING
        _fail(s, st, failure.code, failure.detail, now)
        return StageStatus.FAILED


def run_once(app: Flask, worker_id: str, lease_s: int = 300) -> StageStatus | None:
    """One loop iteration. Returns None when there was nothing to do."""
    with session_scope(app) as s:
        reap_expired(s)
    with session_scope(app) as s:
        claim = claim_next(s, worker_id, lease_s)
    if claim is None:
        return None
    log.info("stage_claimed", extra={"stage_id": claim.stage_id, "evaluation_id": claim.evaluation_id,
                                     "attempt": claim.attempt})
    status = execute(app, claim)
    log.info("stage_finished", extra={"stage_id": claim.stage_id, "status": status.value})
    return status

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from integrity.core.request_context import get_correlation_id
from integrity.domain.enums import ActorType
from integrity.infrastructure.db.models import AuditEvent

_MAX_DETAIL_KEYS = 20


def record_audit_event(
    session: Session,
    *,
    action: str,
    actor_type: ActorType,
    actor_id: str | None = None,
    organization_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit row to the caller's transaction (committed with it).

    ``details`` must contain identifiers and counts only — never document
    text, secrets or upstream payloads.
    """
    if details is not None and len(details) > _MAX_DETAIL_KEYS:
        raise ValueError("audit details too large")
    event = AuditEvent(
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        correlation_id=get_correlation_id(),
        details=details,
    )
    session.add(event)
    return event

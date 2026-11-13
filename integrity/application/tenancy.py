"""Tenant provisioning use cases (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from integrity.domain.enums import ActorType, UserRole
from integrity.infrastructure.db.models import Organization, User
from integrity.security.audit import record_audit_event


def _org_by_ref(session: Session, external_ref: str, *, latest: bool = False) -> Organization | None:
    # latest=True: locking read, sees rows committed after this transaction's snapshot
    # (needed after a unique-key violation on InnoDB REPEATABLE READ).
    stmt = select(Organization).where(Organization.external_ref == external_ref)
    return session.scalar(stmt.with_for_update(read=True) if latest else stmt)


def ensure_organization(session: Session, *, external_ref: str, name: str, actor_id: str) -> tuple[Organization, bool]:
    """Return (organization, created). Safe under concurrent callers."""
    org = _org_by_ref(session, external_ref)
    if org is not None:
        return org, False
    try:
        with session.begin_nested():
            org = Organization(external_ref=external_ref, name=name)
            session.add(org)
            session.flush()
    except IntegrityError:  # another request created it first
        org = _org_by_ref(session, external_ref, latest=True)
        if org is None:
            raise
        return org, False
    record_audit_event(session, action="organization.created", actor_type=ActorType.SERVICE_CLIENT,
                       actor_id=actor_id, organization_id=org.id, target_type="organization", target_id=org.id)
    return org, True


def ensure_user(session: Session, *, organization: Organization, external_ref: str, role: UserRole,
                actor_id: str) -> tuple[User, bool]:
    """Return (user, created). An existing user's role is updated if it differs."""
    def find(latest: bool = False) -> User | None:
        stmt = select(User).where(User.organization_id == organization.id, User.external_ref == external_ref)
        return session.scalar(stmt.with_for_update(read=True) if latest else stmt)

    user = find()
    if user is None:
        try:
            with session.begin_nested():
                user = User(organization_id=organization.id, external_ref=external_ref, role=role)
                session.add(user)
                session.flush()
        except IntegrityError:
            user = find(latest=True)
            if user is None:
                raise
        else:
            record_audit_event(session, action="user.created", actor_type=ActorType.SERVICE_CLIENT, actor_id=actor_id,
                               organization_id=organization.id, target_type="user", target_id=user.id,
                               details={"role": role.value})
            return user, True
    if user.role != role:
        previous = user.role
        user.role = role
        record_audit_event(session, action="user.role_changed", actor_type=ActorType.SERVICE_CLIENT, actor_id=actor_id,
                           organization_id=organization.id, target_type="user", target_id=user.id,
                           details={"from": previous.value, "to": role.value})
    return user, False

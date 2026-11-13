"""Request authentication and tenant resolution.

Trust model (Phase 1 — see SECURITY.md §3):
1. Every protected request carries ``Authorization: Bearer <service key>``.
2. A *platform* client (xplagiax_appcli2) asserts the acting organisation and
   user with ``X-Integrity-Org`` / ``X-Integrity-User`` (appcli2 external ids).
   We never accept a tenant id from an end user directly.
3. An *organization* client is pinned to its organisation; asserting any other
   organisation is rejected.
4. The resolved :class:`TenantContext` is the ONLY source of organisation id
   for data access.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import wraps
from typing import Callable, TypeVar

from flask import current_app, g, request
from sqlalchemy import select

from integrity.core.errors import AuthenticationError, PermissionDenied, ValidationFailed
from integrity.core.ids import utcnow
from integrity.domain.enums import ClientScope, RecordStatus, UserRole
from integrity.infrastructure.db.models import Organization, ServiceClient, User
from integrity.infrastructure.db.session import db_session
from integrity.security.api_keys import parse_prefix, verify_key

log = logging.getLogger("integrity.auth")

ORG_HEADER = "X-Integrity-Org"
USER_HEADER = "X-Integrity-User"
_EXTERNAL_REF = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
# Throttle last_used_at writes: one UPDATE per client per this many seconds at most.
_LAST_USED_GRANULARITY_S = 300

F = TypeVar("F", bound=Callable)


@dataclass(frozen=True)
class TenantContext:
    client_id: str
    client_name: str
    client_scope: ClientScope
    organization_id: str | None
    organization_ref: str | None
    user_id: str | None
    user_ref: str | None
    user_role: UserRole | None


def current_tenant() -> TenantContext:
    ctx = getattr(g, "tenant", None)
    if ctx is None:  # programming error: endpoint not decorated
        raise AuthenticationError()
    return ctx


def _bearer() -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError()
    return token.strip()


def _ref(header: str) -> str | None:
    raw = request.headers.get(header)
    if raw is None or raw == "":
        return None
    if not _EXTERNAL_REF.match(raw):
        raise ValidationFailed(f"{header} has an invalid format.")
    return raw


def _authenticate_client() -> ServiceClient:
    token = _bearer()
    prefix = parse_prefix(token)
    if prefix is None:
        raise AuthenticationError()
    session = db_session()
    client = session.scalar(select(ServiceClient).where(ServiceClient.key_prefix == prefix))
    pepper = current_app.config["XI_SETTINGS"].effective_pepper
    # Always run the HMAC compare, even for unknown prefixes, to keep timing flat.
    digest = client.key_hash if client else "0" * 64
    ok = verify_key(token, digest, pepper)
    if not client or not ok or not client.is_active or client.revoked_at is not None:
        log.warning("auth_failed", extra={"key_prefix": prefix, "reason": "invalid_or_inactive"})
        raise AuthenticationError()
    now = utcnow()
    if client.last_used_at is None or (now - client.last_used_at).total_seconds() > _LAST_USED_GRANULARITY_S:
        client.last_used_at = now
        session.commit()
    return client


def _resolve_tenant(client: ServiceClient, require_org: bool) -> TenantContext:
    session = db_session()
    org_ref = _ref(ORG_HEADER)
    user_ref = _ref(USER_HEADER)

    org: Organization | None = None
    if client.scope == ClientScope.ORGANIZATION:
        org = session.get(Organization, client.organization_id)
        if org is None or (org_ref is not None and org_ref != org.external_ref):
            log.warning("tenant_mismatch", extra={"client_id": client.id})
            raise PermissionDenied()
    elif org_ref is not None:
        org = session.scalar(select(Organization).where(Organization.external_ref == org_ref))
        if org is None:
            # Same response as "not allowed": do not reveal which orgs exist.
            raise PermissionDenied()

    if org is not None and org.status != RecordStatus.ACTIVE:
        raise PermissionDenied("Organization is not active.")
    if require_org and org is None:
        raise PermissionDenied("An organization context is required.")

    user: User | None = None
    if user_ref is not None:
        if org is None:
            raise ValidationFailed(f"{USER_HEADER} requires {ORG_HEADER}.")
        user = session.scalar(
            select(User).where(User.organization_id == org.id, User.external_ref == user_ref)
        )
        if user is None or user.status != RecordStatus.ACTIVE:
            raise PermissionDenied()

    return TenantContext(
        client_id=client.id,
        client_name=client.name,
        client_scope=client.scope,
        organization_id=org.id if org else None,
        organization_ref=org.external_ref if org else None,
        user_id=user.id if user else None,
        user_ref=user.external_ref if user else None,
        user_role=user.role if user else None,
    )


def require_auth(*, require_org: bool = True) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            client = _authenticate_client()
            g.auth_client_id = client.id
            g.tenant = _resolve_tenant(client, require_org=require_org)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

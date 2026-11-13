"""Tenant provisioning for platform clients.

The platform owns identities; it tells this service which organisations and
users exist. Both operations are idempotent PUTs.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from integrity.application.tenancy import ensure_organization, ensure_user
from integrity.core.errors import NotFound, PermissionDenied, ValidationFailed
from integrity.domain.enums import ClientScope, UserRole
from integrity.domain.upstream import is_valid_ref
from integrity.infrastructure.db.models import Organization
from integrity.infrastructure.db.session import db_session
from integrity.security.auth import current_tenant, require_auth

_MAX_NAME = 255


def _platform_client_id() -> str:
    tenant = current_tenant()
    if tenant.client_scope != ClientScope.PLATFORM:
        raise PermissionDenied("Only platform clients can provision tenants.")
    return tenant.client_id


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationFailed("A JSON object body is required.")
    return data


def _ref(value: str, what: str) -> str:
    if not is_valid_ref(value):
        raise ValidationFailed(f"{what} has an invalid format.")
    return value


def register(bp: Blueprint) -> None:
    @bp.put("/organizations/<org_ref>")
    @require_auth(require_org=False)
    def put_organization(org_ref: str):
        actor = _platform_client_id()
        name = _body().get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > _MAX_NAME:
            raise ValidationFailed(f"name is required (1-{_MAX_NAME} characters).")
        session = db_session()
        org, created = ensure_organization(session, external_ref=_ref(org_ref, "organization reference"),
                                           name=name.strip(), actor_id=actor)
        session.commit()
        return jsonify(id=org.id, external_ref=org.external_ref, status=org.status.value), (201 if created else 200)

    @bp.put("/organizations/<org_ref>/users/<user_ref>")
    @require_auth(require_org=False)
    def put_user(org_ref: str, user_ref: str):
        actor = _platform_client_id()
        raw_role = _body().get("role", UserRole.MEMBER.value)
        try:
            role = UserRole(raw_role)
        except ValueError:
            raise ValidationFailed(f"role must be one of {[r.value for r in UserRole]}.") from None
        session = db_session()
        org = session.scalar(select(Organization).where(
            Organization.external_ref == _ref(org_ref, "organization reference")))
        if org is None:
            raise NotFound("Organization not found.")
        user, created = ensure_user(session, organization=org, external_ref=_ref(user_ref, "user reference"),
                                    role=role, actor_id=actor)
        session.commit()
        return jsonify(id=user.id, external_ref=user.external_ref, role=user.role.value,
                       organization_id=org.id), (201 if created else 200)

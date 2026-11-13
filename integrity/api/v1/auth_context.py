"""GET /api/v1/auth/context — lets an integrating client verify its credentials
and tenant assertion end-to-end without touching any document."""

from __future__ import annotations

from flask import Blueprint, jsonify

from integrity.security.auth import current_tenant, require_auth


def register(bp: Blueprint) -> None:
    @bp.get("/auth/context")
    @require_auth(require_org=False)
    def auth_context():
        t = current_tenant()
        return jsonify(
            client={"id": t.client_id, "name": t.client_name, "scope": t.client_scope.value},
            organization=({"id": t.organization_id, "external_ref": t.organization_ref} if t.organization_id else None),
            user=({"id": t.user_id, "external_ref": t.user_ref, "role": t.user_role.value} if t.user_id else None),
        )

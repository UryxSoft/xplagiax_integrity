import hashlib

import pytest
from sqlalchemy import select

from integrity.domain.enums import ClientScope
from integrity.domain.upstream import personal_org_ref, text_sha256
from integrity.infrastructure.db.models import AuditEvent, Organization, User
from integrity.infrastructure.db.session import session_scope


def h(key, **extra):
    return {"Authorization": f"Bearer {key}", **extra}


# --- conventions shared with the platform ------------------------------------

def test_text_sha256_ignores_whitespace_layout_only():
    a = text_sha256("Climate  change\nremains\t one of the\r\n greatest challenges. ")
    b = text_sha256("Climate change remains one of the greatest challenges.")
    assert a == b == hashlib.sha256(b"Climate change remains one of the greatest challenges.").hexdigest()
    assert text_sha256("climate change remains one of the greatest challenges.") != a  # case matters
    assert text_sha256(None) == text_sha256("") == hashlib.sha256(b"").hexdigest()


def test_personal_org_ref():
    assert personal_org_ref(42) == "user:42"
    with pytest.raises(ValueError):
        personal_org_ref("4 2")


# --- provisioning ---------------------------------------------------------------

def test_platform_client_provisions_org_and_user_idempotently(app, client, factory):
    _, key = factory.service_client(name="appcli2")
    ref = personal_org_ref(42)

    r1 = client.put(f"/api/v1/organizations/{ref}", json={"name": "User 42"}, headers=h(key))
    r2 = client.put(f"/api/v1/organizations/{ref}", json={"name": "ignored on repeat"}, headers=h(key))
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.get_json()["id"] == r2.get_json()["id"]

    u1 = client.put(f"/api/v1/organizations/{ref}/users/42", json={}, headers=h(key))
    u2 = client.put(f"/api/v1/organizations/{ref}/users/42", json={"role": "org_admin"}, headers=h(key))
    assert (u1.status_code, u2.status_code) == (201, 200)
    assert u1.get_json()["role"] == "member" and u2.get_json()["role"] == "org_admin"

    # The provisioned tenant is immediately usable.
    ctx = client.get("/api/v1/auth/context", headers=h(key, **{"X-Integrity-Org": ref, "X-Integrity-User": "42"}))
    assert ctx.status_code == 200 and ctx.get_json()["user"]["role"] == "org_admin"

    with session_scope(app) as s:
        assert len(s.scalars(select(Organization)).all()) == 1
        assert len(s.scalars(select(User)).all()) == 1
        actions = sorted(a.action for a in s.scalars(select(AuditEvent)))
        assert actions == ["organization.created", "user.created", "user.role_changed"]


def test_organization_client_cannot_provision(client, factory):
    org = factory.org("org-a")
    _, key = factory.service_client(scope=ClientScope.ORGANIZATION, org_id=org)
    assert client.put("/api/v1/organizations/org-b", json={"name": "x"}, headers=h(key)).status_code == 403
    assert client.put("/api/v1/organizations/org-a/users/u1", json={}, headers=h(key)).status_code == 403


def test_provisioning_requires_authentication(client):
    assert client.put("/api/v1/organizations/org-a", json={"name": "x"}).status_code == 401


@pytest.mark.parametrize("body", [None, [], {"name": ""}, {"name": "x" * 256}, {"name": 5}])
def test_organization_body_validation(client, factory, body):
    _, key = factory.service_client()
    assert client.put("/api/v1/organizations/org-a", json=body, headers=h(key)).status_code == 422


def test_invalid_references_and_roles_are_rejected(client, factory):
    _, key = factory.service_client()
    factory.org("org-a")
    assert client.put("/api/v1/organizations/bad ref", json={"name": "x"}, headers=h(key)).status_code == 422
    assert client.put("/api/v1/organizations/org-a/users/u1", json={"role": "root"}, headers=h(key)).status_code == 422
    assert client.put("/api/v1/organizations/missing/users/u1", json={}, headers=h(key)).status_code == 404

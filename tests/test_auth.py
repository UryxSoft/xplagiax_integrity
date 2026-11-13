import pytest

from integrity.core.ids import utcnow
from integrity.domain.enums import ClientScope, RecordStatus
from integrity.infrastructure.db.models import ServiceClient
from integrity.infrastructure.db.session import session_scope
from integrity.security.api_keys import generate_key, hash_key, parse_prefix, verify_key

URL = "/api/v1/auth/context"


def auth(key, org=None, user=None):
    h = {"Authorization": f"Bearer {key}"}
    if org:
        h["X-Integrity-Org"] = org
    if user:
        h["X-Integrity-User"] = user
    return h


# --- key primitives ---------------------------------------------------------

def test_generated_key_roundtrip():
    k = generate_key("pepper")
    assert parse_prefix(k.plaintext) == k.prefix
    assert verify_key(k.plaintext, k.digest, "pepper")
    assert not verify_key(k.plaintext, k.digest, "other-pepper")
    assert k.plaintext not in k.digest


@pytest.mark.parametrize("bad", ["", "xik_", "Bearer x", "xik_zzzzzzzzzzzz_" + "a" * 43, "xik_0123456789ab_short"])
def test_malformed_keys_have_no_prefix(bad):
    assert parse_prefix(bad) is None


def test_hash_is_deterministic_hmac():
    assert hash_key("a", "p") == hash_key("a", "p") != hash_key("a", "q")


# --- authentication -----------------------------------------------------------

@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "},
                                     {"Authorization": "Bearer not-a-key"}])
def test_missing_or_malformed_credentials(client, headers):
    r = client.get(URL, headers=headers)
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthenticated"


def test_unknown_key_rejected(client):
    assert client.get(URL, headers=auth(generate_key("x").plaintext)).status_code == 401


def test_wrong_secret_with_valid_prefix_rejected(client, factory):
    _, key = factory.service_client()
    tampered = key[:-4] + ("AAAA" if not key.endswith("AAAA") else "BBBB")
    assert client.get(URL, headers=auth(tampered)).status_code == 401


def test_platform_client_without_org(client, factory):
    cid, key = factory.service_client(name="appcli2")
    r = client.get(URL, headers=auth(key))
    assert r.status_code == 200
    body = r.get_json()
    assert body["client"] == {"id": cid, "name": "appcli2", "scope": "platform"}
    assert body["organization"] is None and body["user"] is None


def test_platform_client_asserts_org_and_user(client, factory):
    org = factory.org("org-a")
    uid = factory.user(org, "u-1")
    _, key = factory.service_client()
    body = client.get(URL, headers=auth(key, "org-a", "u-1")).get_json()
    assert body["organization"] == {"id": org, "external_ref": "org-a"}
    assert body["user"]["id"] == uid


def test_revoked_or_inactive_client_rejected(app, client, factory):
    cid, key = factory.service_client()
    with session_scope(app) as s:
        s.get(ServiceClient, cid).revoked_at = utcnow()
    assert client.get(URL, headers=auth(key)).status_code == 401
    cid2, key2 = factory.service_client()
    with session_scope(app) as s:
        s.get(ServiceClient, cid2).is_active = False
    assert client.get(URL, headers=auth(key2)).status_code == 401


def test_last_used_is_recorded(app, client, factory):
    cid, key = factory.service_client()
    client.get(URL, headers=auth(key))
    with session_scope(app) as s:
        assert s.get(ServiceClient, cid).last_used_at is not None


# --- tenant resolution --------------------------------------------------------

def test_unknown_org_is_forbidden_not_404(client, factory):
    _, key = factory.service_client()
    r = client.get(URL, headers=auth(key, "does-not-exist"))
    assert r.status_code == 403


def test_suspended_org_forbidden(client, factory):
    factory.org("org-s", status=RecordStatus.SUSPENDED)
    _, key = factory.service_client()
    assert client.get(URL, headers=auth(key, "org-s")).status_code == 403


def test_org_client_cannot_assert_other_org(client, factory):
    a = factory.org("org-a")
    factory.org("org-b")
    _, key = factory.service_client(scope=ClientScope.ORGANIZATION, org_id=a)
    assert client.get(URL, headers=auth(key, "org-b")).status_code == 403
    body = client.get(URL, headers=auth(key)).get_json()  # implicit org
    assert body["organization"]["id"] == a


def test_user_from_other_org_is_forbidden(client, factory):
    a = factory.org("org-a")
    b = factory.org("org-b")
    factory.user(b, "u-b")
    factory.user(a, "u-a")
    _, key = factory.service_client()
    assert client.get(URL, headers=auth(key, "org-a", "u-b")).status_code == 403
    assert client.get(URL, headers=auth(key, "org-a", "u-a")).status_code == 200


def test_user_without_org_is_invalid(client, factory):
    _, key = factory.service_client()
    assert client.get(URL, headers=auth(key, user="u-1")).status_code == 422


@pytest.mark.parametrize("bad", ["org a", "x" * 65, "../etc", "org;drop"])
def test_malformed_tenant_headers_rejected(client, factory, bad):
    _, key = factory.service_client()
    assert client.get(URL, headers=auth(key, bad)).status_code == 422

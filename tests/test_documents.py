"""Stage 2: document ingestion (contract xplagiax.document/v1)."""

import copy
import json
import threading

import pytest
from sqlalchemy import func, select

from integrity.domain.enums import ClientScope, UserRole
from integrity.domain.ingestion_contract import (
    ContractLimits,
    ContractViolation,
    InsufficientContent,
    parse_document,
)
from integrity.domain.upstream import text_sha256
from integrity.infrastructure import content_store
from integrity.infrastructure.db.models import AuditEvent, DocumentContent, DocumentVersion
from integrity.infrastructure.db.session import session_scope

TEXT = ("Climate change remains one of the greatest challenges of our time. "
        "Artificial intelligence and data analytics also play a role in mitigation.")


def payload(**over):
    body = {
        "schema": "xplagiax.document/v1",
        "source": {"producer": "xplagiax_appcli2", "producer_version": "2.4.1", "analysis_ref": "hist-123",
                   "file_sha256": "a" * 64, "filename": "../../etc/passwd", "mime_type": "application/pdf"},
        "text": TEXT,
        "paragraphs": [[1, 1, TEXT[:66]], [1, 2, TEXT[67:]]],
        "word_count": len(TEXT.split()),
        "language": "en",
        "metadata": {"title": "Climate and AI", "author": "someone"},
        "extraction": {"status": "complete", "pages_total": 1, "pages_with_text": 1,
                       "pages_needing_ocr": [], "pages_failed": [], "ocr": None, "format": "pdf"},
    }
    for k, v in over.items():
        body[k] = v
    return body


# ---------------------------------------------------------------- contract (pure)

def test_contract_parses_valid_document():
    d = parse_document(payload())
    assert d.content_sha256 == text_sha256(TEXT)
    assert d.word_count == len(TEXT.split()) and d.language == "en" and d.title == "Climate and AI"
    assert [(p.page, p.number) for p in d.paragraphs] == [(1, 1), (1, 2)]
    assert d.limitations == ()


@pytest.mark.parametrize("mutate,expected", [
    (lambda b: b.update(schema="v0"), "schema"),
    (lambda b: b.pop("text"), "text is required"),
    (lambda b: b.update(text="a\x00b " * 20), "NUL"),
    (lambda b: b["source"].update(producer="bad producer"), "source.producer"),
    (lambda b: b["source"].update(file_sha256="XYZ"), "file_sha256"),
    (lambda b: b["source"].update(mime_type="not a type"), "mime_type"),
    (lambda b: b.update(paragraphs=[[0, 1, "x"]]), "paragraphs[0]"),
    (lambda b: b.update(paragraphs=[[1, 1, "x"], [1, 1, "y"]]), "duplicates"),
    (lambda b: b.update(paragraphs=[[True, 1, "x"]]), "paragraphs[0]"),
    (lambda b: b.update(language="english!!"), "language"),
    (lambda b: b["extraction"].update(status="done"), "extraction.status"),
    (lambda b: b["extraction"].update(pages_failed=[0]), "pages_failed"),
    (lambda b: b.update(word_count=-1), "word_count"),
])
def test_contract_reports_each_violation(mutate, expected):
    body = payload()
    mutate(body)
    with pytest.raises(ContractViolation) as exc:
        parse_document(body)
    assert any(expected in p for p in exc.value.problems), exc.value.problems


def test_contract_collects_all_problems_at_once():
    with pytest.raises(ContractViolation) as exc:
        parse_document({"schema": "x", "source": {}, "extraction": {}})
    assert len(exc.value.problems) >= 4


def test_contract_enforces_size_limits():
    limits = ContractLimits(max_text_chars=50, max_paragraphs=1)
    with pytest.raises(ContractViolation) as exc:
        parse_document(payload(), limits)
    joined = " ".join(exc.value.problems)
    assert "text exceeds" in joined and "paragraphs exceeds" in joined


@pytest.mark.parametrize("body", [
    payload(text="too short"),
    payload(extraction={"status": "failed", "pages_failed": [1]}),
])
def test_contract_rejects_unanalysable_documents(body):
    with pytest.raises(InsufficientContent):
        parse_document(body)


def test_contract_records_limitations_instead_of_hiding_them():
    d = parse_document(payload(language="unknown", word_count=3,
                               extraction={"status": "partial", "pages_total": 3, "pages_failed": [2],
                                           "pages_needing_ocr": [3]}))
    assert d.extraction_status.value == "partial" and d.language is None
    joined = " ".join(d.limitations)
    assert "partial" in joined and "word_count" in joined and "language" in joined


# ---------------------------------------------------------------- HTTP

@pytest.fixture()
def tenant(factory):
    org = factory.org("user:42")
    owner = factory.user(org, "42")
    factory.user(org, "43")
    factory.user(org, "rev", role=UserRole.REVIEWER)
    factory.user(org, "adm", role=UserRole.ORG_ADMIN)
    _, key = factory.service_client(name="appcli2")
    return {"org": org, "owner": owner, "key": key}


def headers(t, user="42", key="idem-key-0001", org="user:42"):
    h = {"Authorization": f"Bearer {t['key']}", "X-Integrity-Org": org, "Idempotency-Key": key}
    if user:
        h["X-Integrity-User"] = user
    return h


def post(client, t, body=None, **kw):
    return client.post("/api/v1/documents", json=payload() if body is None else body, headers=headers(t, **kw))


def test_ingest_creates_document_version_and_compressed_content(app, client, tenant):
    r = post(client, tenant)
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["created"] is True and body["version"]["version_number"] == 1
    assert body["version"]["content_sha256"] == text_sha256(TEXT)
    with session_scope(app) as s:
        v = s.get(DocumentVersion, body["version"]["id"])
        assert v.original_filename == "../../etc/passwd"  # stored as data only, never used as a path
        assert v.storage_ref is None
        stored = content_store.get(s, organization_id=tenant["org"], version_id=v.id)
        assert stored.text == TEXT and stored.paragraphs[0][:2] == (1, 1)
        row = s.get(DocumentContent, v.id)
        assert row.payload_bytes < len(TEXT.encode()) * 2
        assert "document.ingested" in {a.action for a in s.scalars(select(AuditEvent))}


def test_ingest_is_idempotent_and_detects_key_reuse(client, tenant):
    first = post(client, tenant).get_json()
    again = post(client, tenant)
    assert again.status_code == 200 and again.get_json()["created"] is False
    assert again.get_json()["version"]["id"] == first["version"]["id"]
    other = post(client, tenant, body=payload(text=TEXT + " A different ending changes the hash."))
    assert other.status_code == 409 and other.get_json()["error"]["code"] == "idempotency_conflict"


def test_concurrent_identical_requests_create_one_document(app, tenant):
    # Fresh clients per thread; SQLite serialises writes, which still exercises the race path.
    results = []

    def go():
        results.append(app.test_client().post("/api/v1/documents", json=payload(),
                                               headers=headers(tenant, key="race-key-0001")).status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results).count(201) == 1 and set(results) <= {200, 201, 409}
    with session_scope(app) as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 1


@pytest.mark.parametrize("hdrs,status", [
    ({"Idempotency-Key": None}, 422),
    ({"Idempotency-Key": "short"}, 422),
    ({"Idempotency-Key": "has#hash-char"}, 422),  # '#' is reserved for migrated rows
])
def test_idempotency_key_is_required_and_validated(client, tenant, hdrs, status):
    h = headers(tenant)
    for k, v in hdrs.items():
        if v is None:
            h.pop(k)
        else:
            h[k] = v
    assert client.post("/api/v1/documents", json=payload(), headers=h).status_code == status


def test_contract_errors_are_returned_with_details(client, tenant):
    r = post(client, tenant, body=payload(schema="nope", language="??"))
    err = r.get_json()["error"]
    assert r.status_code == 422 and err["code"] == "invalid_document"
    assert any("schema" in d for d in err["details"]) and any("language" in d for d in err["details"])


def test_unanalysable_document_is_rejected_explicitly(client, tenant):
    r = post(client, tenant, body=payload(text="only three words"))
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "insufficient_content"


def test_non_json_body_is_rejected(client, tenant):
    r = client.post("/api/v1/documents", data="text", headers=headers(tenant))
    assert r.status_code == 422


def test_org_context_is_required(client, tenant):
    r = client.post("/api/v1/documents", json=payload(),
                    headers={"Authorization": f"Bearer {tenant['key']}", "Idempotency-Key": "idem-key-0001"})
    assert r.status_code == 403


def test_versions_are_numbered_and_owner_only(client, tenant):
    doc = post(client, tenant).get_json()["document_id"]
    url = f"/api/v1/documents/{doc}/versions"
    v2 = client.post(url, json=payload(text=TEXT + " Revised conclusion."), headers=headers(tenant, key="idem-key-0002"))
    assert v2.status_code == 201 and v2.get_json()["version"]["version_number"] == 2
    # A member who does not own the document cannot even see it.
    other = client.post(url, json=payload(), headers=headers(tenant, user="43", key="idem-key-0003"))
    assert other.status_code == 404
    # Same key, same document -> replay
    replay = client.post(url, json=payload(text=TEXT + " Revised conclusion."), headers=headers(tenant, key="idem-key-0002"))
    assert replay.status_code == 200 and replay.get_json()["version"]["version_number"] == 2
    read = client.get(f"/api/v1/documents/{doc}", headers=headers(tenant)).get_json()
    assert [v["version_number"] for v in read["versions"]] == [1, 2]
    assert TEXT[:30] not in json.dumps(read)  # metadata endpoint never returns document text


def test_read_visibility_by_role(client, tenant):
    doc = post(client, tenant).get_json()["document_id"]
    url = f"/api/v1/documents/{doc}"
    assert client.get(url, headers=headers(tenant, user="42")).status_code == 200
    assert client.get(url, headers=headers(tenant, user="43")).status_code == 404
    assert client.get(url, headers=headers(tenant, user="rev")).status_code == 200
    assert client.get(url, headers=headers(tenant, user="adm")).status_code == 200
    assert client.get(url, headers=headers(tenant, user=None)).status_code == 200


def test_other_organization_cannot_see_document(client, tenant, factory):
    doc = post(client, tenant).get_json()["document_id"]
    factory.org("user:99")
    r = client.get(f"/api/v1/documents/{doc}", headers=headers(tenant, user=None, org="user:99"))
    assert r.status_code == 404


def test_malformed_document_id(client, tenant):
    assert client.get("/api/v1/documents/not-a-uuid", headers=headers(tenant)).status_code == 422


def test_purge_removes_content_keeps_hashes_and_blocks_new_versions(app, client, tenant):
    created = post(client, tenant).get_json()
    doc, vid = created["document_id"], created["version"]["id"]
    assert client.delete(f"/api/v1/documents/{doc}", headers=headers(tenant, user="43")).status_code == 404
    assert client.delete(f"/api/v1/documents/{doc}", headers=headers(tenant, user="rev")).status_code == 403
    r = client.delete(f"/api/v1/documents/{doc}", headers=headers(tenant))
    assert r.status_code == 200 and r.get_json()["contents_removed"] == 1
    again = client.delete(f"/api/v1/documents/{doc}", headers=headers(tenant))
    assert again.status_code == 200 and again.get_json()["contents_removed"] == 0
    with session_scope(app) as s:
        assert s.get(DocumentContent, vid) is None
        assert s.get(DocumentVersion, vid).content_sha256 == text_sha256(TEXT)
    read = client.get(f"/api/v1/documents/{doc}", headers=headers(tenant)).get_json()
    assert read["purged_at"] and read["title"] is None
    v = client.post(f"/api/v1/documents/{doc}/versions", json=payload(), headers=headers(tenant, key="idem-key-0009"))
    assert v.status_code == 410


def test_organization_client_cannot_write_into_another_org(client, factory):
    a = factory.org("org-a")
    factory.org("org-b")
    _, key = factory.service_client(scope=ClientScope.ORGANIZATION, org_id=a)
    r = client.post("/api/v1/documents", json=payload(),
                    headers={"Authorization": f"Bearer {key}", "X-Integrity-Org": "org-b", "Idempotency-Key": "idem-key-0001"})
    assert r.status_code == 403


def test_stored_content_tampering_is_detected(app, client, tenant):
    vid = post(client, tenant).get_json()["version"]["id"]
    with session_scope(app) as s:
        row = s.get(DocumentContent, vid)
        row.payload = content_store.encode("tampered text " * 5, [])
    with session_scope(app) as s:
        with pytest.raises(content_store.ContentIntegrityError):
            content_store.get(s, organization_id=tenant["org"], version_id=vid)


def test_content_store_never_returns_other_tenants_content(app, client, tenant, factory):
    vid = post(client, tenant).get_json()["version"]["id"]
    other = factory.org("org-z")
    with session_scope(app) as s:
        assert content_store.get(s, organization_id=other, version_id=vid) is None


def test_retention_is_applied_from_the_organization(app, client, tenant):
    from integrity.infrastructure.db.models import Organization

    with session_scope(app) as s:
        s.get(Organization, tenant["org"]).retention_days = 30
    read = client.get(f"/api/v1/documents/{post(client, tenant).get_json()['document_id']}",
                      headers=headers(tenant)).get_json()
    assert read["retention_until"] is not None

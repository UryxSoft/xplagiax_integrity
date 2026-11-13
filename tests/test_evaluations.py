"""Stage 3c: evaluations and the background stage worker."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from integrity.core.ids import utcnow
from integrity.domain.enums import EvaluationStatus, StageStatus, UserRole
from integrity.domain.workflows import config_hash
from integrity.engines import registry
from integrity.engines.base import StageFailure
from integrity.infrastructure.db.models import DocumentContent, EvaluationStage
from integrity.infrastructure.db.session import session_scope
from integrity.workers.runner import claim_next, execute, reap_expired, run_once
from tests.test_documents import TEXT, payload

DOI_TEXT = TEXT + " See doi:10.1038/nature12373 and https://doi.org/10.1016/j.cell.2009.01.002."


@pytest.fixture()
def tenant(factory):
    org = factory.org("user:42")
    factory.user(org, "42")
    factory.user(org, "43")
    factory.user(org, "rev", role=UserRole.REVIEWER)
    _, key = factory.service_client(name="appcli2")
    return {"org": org, "key": key}


def h(t, user="42", key="idem-key-0001"):
    return {"Authorization": f"Bearer {t['key']}", "X-Integrity-Org": "user:42", "X-Integrity-User": user,
            "Idempotency-Key": key}


def ingest(client, t, text=DOI_TEXT, paragraphs=None):
    body = payload(text=text, paragraphs=paragraphs if paragraphs is not None else [[1, 1, text]])
    r = client.post("/api/v1/documents", json=body, headers=h(t, key="doc-key-0001"))
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()["version"]["id"]


def evaluate(client, t, version_id, product="research_paper", key="eval-key-0001", user="42"):
    return client.post("/api/v1/evaluations", json={"document_version_id": version_id, "product": product},
                       headers=h(t, user=user, key=key))


def drain(app, limit=20):
    statuses = []
    for _ in range(limit):
        s = run_once(app, "test-worker")
        if s is None:
            break
        statuses.append(s)
    return statuses


def read(client, t, eid, user="42"):
    return client.get(f"/api/v1/evaluations/{eid}", headers=h(t, user=user)).get_json()


# ---------------------------------------------------------------- happy path

def test_evaluation_runs_end_to_end(app, client, tenant):
    vid = ingest(client, tenant)
    r = evaluate(client, tenant, vid)
    assert r.status_code == 202
    ev = r.get_json()
    assert ev["status"] == "queued" and [s["name"] for s in ev["stages"]] == ["content_check", "doi_detection"]
    assert all(s["status"] == "pending" for s in ev["stages"])

    assert drain(app) == [StageStatus.SUCCEEDED, StageStatus.SUCCEEDED]
    ev = read(client, tenant, ev["id"])
    assert ev["status"] == "completed" and ev["finished_at"]
    check, dois = ev["stages"]
    assert check["result"]["payload"]["content_sha256"] == ev_hash(app, vid)
    assert dois["result"]["payload"]["unique_dois"] == ["10.1016/j.cell.2009.01.002", "10.1038/nature12373"]
    loc = dois["result"]["payload"]["mentions"][0]["location"]
    assert (loc["page"], loc["paragraph"]) == (1, 1) and DOI_TEXT[loc["char_start"]:loc["char_end"]] == "10.1038/nature12373"
    assert "not verified" in " ".join(dois["result"]["limitations"])
    assert len(dois["result"]["payload_sha256"]) == 64


def ev_hash(app, vid):
    from integrity.infrastructure.db.models import DocumentVersion

    with session_scope(app) as s:
        return s.get(DocumentVersion, vid).content_sha256


def test_creation_is_idempotent_and_config_is_frozen(client, tenant):
    vid = ingest(client, tenant)
    a = evaluate(client, tenant, vid).get_json()
    b = evaluate(client, tenant, vid)
    assert b.status_code == 200 and b.get_json()["id"] == a["id"]
    other = evaluate(client, tenant, vid, product="dissertation")
    assert other.status_code == 409
    from integrity.domain.enums import Product
    from integrity.domain.workflows import config_snapshot

    assert a["config_sha256"] == config_hash(config_snapshot(Product.RESEARCH_PAPER, None, None))


@pytest.mark.parametrize("body,status", [
    ({"product": "research_paper"}, 422),
    ({"product": "nope", "document_version_id": "01a1d4ff-db27-79b6-9e1b-7db5c3d49620"}, 422),
    ({"product": "research_paper", "document_version_id": "01a1d4ff-db27-79b6-9e1b-7db5c3d49620"}, 404),
    ({"product": "research_paper", "document_version_id": "x"}, 422),
])
def test_creation_validation(client, tenant, body, status):
    assert client.post("/api/v1/evaluations", json=body, headers=h(tenant)).status_code == status


def test_visibility_follows_the_document(client, tenant):
    vid = ingest(client, tenant)
    assert evaluate(client, tenant, vid, user="43", key="eval-key-0043").status_code == 404
    eid = evaluate(client, tenant, vid).get_json()["id"]
    assert client.get(f"/api/v1/evaluations/{eid}", headers=h(tenant, user="43")).status_code == 404
    assert client.get(f"/api/v1/evaluations/{eid}", headers=h(tenant, user="rev")).status_code == 200


def test_patent_workflow_has_only_implemented_stages(app, client, tenant):
    vid = ingest(client, tenant)
    ev = evaluate(client, tenant, vid, product="patent_integrity").get_json()
    assert [s["name"] for s in ev["stages"]] == ["content_check"]
    drain(app)
    assert read(client, tenant, ev["id"])["status"] == "completed"


def test_stages_run_in_order(app, client, tenant):
    vid = ingest(client, tenant)
    evaluate(client, tenant, vid)
    with session_scope(app) as s:
        first = claim_next(s, "w1", 300)
    with session_scope(app) as s:
        assert claim_next(s, "w2", 300) is None  # stage 2 waits for stage 1
    execute(app, first)
    with session_scope(app) as s:
        assert claim_next(s, "w2", 300) is not None


# ---------------------------------------------------------------- failures

def test_tampered_content_fails_required_stage_and_skips_the_rest(app, client, tenant):
    from integrity.infrastructure import content_store

    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    with session_scope(app) as s:  # valid blob, different text: integrity OK, hash of text wrong
        row = s.get(DocumentContent, vid)
        blob = content_store.encode("completely different text " * 5, [])
        import hashlib
        row.payload, row.payload_bytes, row.payload_sha256 = blob, len(blob), hashlib.sha256(blob).hexdigest()
    assert drain(app) == [StageStatus.FAILED]
    ev = read(client, tenant, eid)
    assert ev["status"] == "failed" and ev["error_code"] == "content_hash_mismatch"
    assert [(s["status"], s["error_code"]) for s in ev["stages"]] == [
        ("failed", "content_hash_mismatch"), ("skipped", "previous_stage_failed")]


def test_purged_document_cannot_be_evaluated_and_running_one_fails_cleanly(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    doc = client.get(f"/api/v1/documents/{doc_of(app, vid)}", headers=h(tenant)).get_json()["id"]
    client.delete(f"/api/v1/documents/{doc}", headers=h(tenant))
    assert evaluate(client, tenant, vid, key="eval-key-0002").status_code == 410
    drain(app)
    ev = read(client, tenant, eid)
    assert ev["status"] == "failed" and ev["stages"][0]["error_code"] == "content_unavailable"


def doc_of(app, vid):
    from integrity.infrastructure.db.models import DocumentVersion

    with session_scope(app) as s:
        return s.get(DocumentVersion, vid).document_id


def test_optional_stage_failure_gives_partial_completion(app, client, tenant, monkeypatch):
    def broken(inp):
        raise StageFailure("bad_input", "cannot process", retryable=False)

    monkeypatch.setitem(registry.ENGINES, ("doi_detection", "1"), broken)
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    drain(app)
    ev = read(client, tenant, eid)
    assert ev["status"] == "partially_completed"
    assert [s["status"] for s in ev["stages"]] == ["succeeded", "failed"]


def test_engine_crash_is_retried_with_backoff_then_fails(app, client, tenant, monkeypatch):
    calls = []

    def crash(inp):
        calls.append(1)
        raise RuntimeError("secret document text must not leak")

    monkeypatch.setitem(registry.ENGINES, ("content_check", "1"), crash)
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    assert drain(app) == [StageStatus.PENDING]  # retry scheduled
    with session_scope(app) as s:
        st = s.scalars(select(EvaluationStage).where(EvaluationStage.sequence == 1)).one()
        assert st.not_before > utcnow() and st.error_code == "internal_error"
        assert "secret" not in (st.error_detail or "")
        for _ in range(2):  # fast-forward the backoff twice
            st.not_before = utcnow() - timedelta(seconds=1)
            s.flush()
            s.commit()
            assert run_once(app, "w") in (StageStatus.PENDING, StageStatus.FAILED)
    assert len(calls) == 3
    ev = read(client, tenant, eid)
    assert ev["status"] == "failed" and ev["stages"][0]["attempt"] == 3


def test_expired_lease_is_recovered_by_another_worker(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    with session_scope(app) as s:
        dead = claim_next(s, "dead-worker", 300)
        st = s.get(EvaluationStage, dead.stage_id)
        st.lease_expires_at = utcnow() - timedelta(seconds=1)  # the worker died
    assert run_once(app, "w2") == StageStatus.SUCCEEDED
    # The dead worker coming back must not overwrite anything.
    assert execute(app, dead) == StageStatus.RUNNING
    drain(app)
    ev = read(client, tenant, eid)
    assert ev["status"] == "completed" and ev["stages"][0]["attempt"] == 2


def test_exhausted_expired_lease_is_reaped(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    with session_scope(app) as s:
        c = claim_next(s, "dead", 300)
        st = s.get(EvaluationStage, c.stage_id)
        st.attempt, st.lease_expires_at = st.max_attempts, utcnow() - timedelta(seconds=1)
    with session_scope(app) as s:
        assert reap_expired(s) == 1
    ev = read(client, tenant, eid)
    assert ev["status"] == "failed" and ev["stages"][0]["error_code"] == "lease_expired"


# ---------------------------------------------------------------- cancellation

def test_cancel_before_processing(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    r = client.post(f"/api/v1/evaluations/{eid}/cancel", headers=h(tenant))
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    assert all(s["status"] == "cancelled" for s in r.get_json()["stages"])
    assert drain(app) == []
    assert client.post(f"/api/v1/evaluations/{eid}/cancel", headers=h(tenant)).status_code == 200  # idempotent


def test_cancel_while_running_discards_the_result(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    with session_scope(app) as s:
        c = claim_next(s, "w", 300)
    client.post(f"/api/v1/evaluations/{eid}/cancel", headers=h(tenant))
    assert execute(app, c) == StageStatus.CANCELLED
    ev = read(client, tenant, eid)
    assert ev["status"] == "cancelled" and all(s["result"] is None for s in ev["stages"])


def test_completed_evaluation_cannot_be_cancelled(app, client, tenant):
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    drain(app)
    assert client.post(f"/api/v1/evaluations/{eid}/cancel", headers=h(tenant)).get_json()["status"] == "completed"


def test_worker_cli_once(app, client, tenant):
    vid = ingest(client, tenant)
    evaluate(client, tenant, vid)
    r = app.test_cli_runner().invoke(args=["integrity", "worker", "--once"])
    assert r.exit_code == 0 and "after 1 stage" in r.output

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
    assert ev["status"] == "queued" and [s["name"] for s in ev["stages"]] == [
        "content_check", "doi_detection", "citation_consistency"]
    assert all(s["status"] == "pending" for s in ev["stages"])

    assert drain(app) == [StageStatus.SUCCEEDED] * 3
    ev = read(client, tenant, ev["id"])
    assert ev["status"] == "completed" and ev["finished_at"]
    check, dois, cites = ev["stages"]
    assert cites["result"]["payload"]["references_section_found"] is False  # this text has no bibliography
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
        ("failed", "content_hash_mismatch"), ("skipped", "previous_stage_failed"), ("skipped", "previous_stage_failed")]


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
    assert [s["status"] for s in ev["stages"]] == ["succeeded", "failed", "succeeded"]


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


def test_citation_findings_are_persisted_with_evidence_and_purged_excerpts(app, client, tenant):
    from integrity.infrastructure.db.models import Evidence, Finding
    from tests.test_citations import NUMERIC

    text = "\n".join(NUMERIC)
    vid = ingest(client, tenant, text=text, paragraphs=[[1, i + 1, p] for i, p in enumerate(NUMERIC)])
    eid = evaluate(client, tenant, vid).get_json()["id"]
    drain(app)
    ev = read(client, tenant, eid)
    assert ev["status"] == "completed"
    assert ev["stages"][2]["result"]["payload"]["citations_without_reference"] == 1
    with session_scope(app) as s:
        findings = s.scalars(select(Finding).where(Finding.evaluation_id == eid)).all()
        assert sorted(f.category for f in findings) == ["citation_without_reference", "reference_not_cited"]
        ev_rows = s.scalars(select(Evidence)).all()
        assert len(ev_rows) == 2 and all(e.excerpt_text and len(e.excerpt_sha256) == 64 for e in ev_rows)
        assert all(e.document_version_id == vid for e in ev_rows)
        hashes = {e.id: e.excerpt_sha256 for e in ev_rows}
    client.delete(f"/api/v1/documents/{doc_of(app, vid)}", headers=h(tenant))
    with session_scope(app) as s:
        rows = s.scalars(select(Evidence)).all()
        assert all(e.excerpt_text is None for e in rows)
        assert {e.id: e.excerpt_sha256 for e in rows} == hashes  # still verifiable


# ---------------------------------------------------------------- report

def _paper(client, tenant):
    from tests.test_citations import NUMERIC

    text = "\n".join(NUMERIC) + "\nSee doi:10.1038/nature12373."
    paras = [[1, i + 1, p] for i, p in enumerate(NUMERIC)]
    paras[1][2] += " See doi:10.1038/nature12373."
    return ingest(client, tenant, text="\n".join(p[2] for p in paras), paragraphs=paras)


def test_report_is_built_from_stored_data_and_reproducible(app, client, tenant):
    vid = _paper(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    assert client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).status_code == 409  # not finished
    drain(app)
    r1 = client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).get_json()
    assert r1["product"] == "research_paper" and r1["evaluation"]["status"] == "completed"
    assert r1["document"]["content_sha256"] == ev_hash(app, vid)
    assert [s["engine"]["name"] for s in r1["stages"]] == ["content_check", "doi_detection", "citation_consistency"]
    assert r1["finding_counts"] == {"citation_without_reference": 1, "reference_not_cited": 1}
    f = r1["findings"][0]
    assert f["nature"] == "structural_observation" and "confirm manually" in f["nature_explained"]
    assert f["evidence"][0]["excerpt"] and len(f["evidence"][0]["excerpt_sha256"]) == 64
    assert any("does not mean the document is original" in d for d in r1["disclaimer"])
    assert any("not verified" in l for l in r1["limitations"])
    assert r1["sources_consulted"] == []  # no external source was queried

    r2 = client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).get_json()
    assert r2["report"]["content_sha256"] == r1["report"]["content_sha256"] and r2["report"]["id"] == r1["report"]["id"]

    # Purging the document removes excerpts but the report hash still reproduces.
    client.delete(f"/api/v1/documents/{doc_of(app, vid)}", headers=h(tenant))
    r3 = client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).get_json()
    assert r3["report"]["content_sha256"] == r1["report"]["content_sha256"]
    ev3 = r3["findings"][0]["evidence"][0]
    assert ev3["excerpt"] is None and ev3["excerpt_purged"] is True
    assert ev3["excerpt_sha256"] == f["evidence"][0]["excerpt_sha256"]


def test_tampering_with_stored_findings_is_detected(app, client, tenant):
    from integrity.infrastructure.db.models import Finding

    vid = _paper(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    drain(app)
    assert client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).status_code == 200
    with session_scope(app) as s:
        s.scalars(select(Finding)).first().title = "edited after the fact"
    r = client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant))
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "report_mismatch"


def test_report_follows_document_visibility(app, client, tenant):
    vid = _paper(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    drain(app)
    assert client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant, user="43")).status_code == 404
    assert client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant, user="rev")).status_code == 200


def test_partial_and_patent_reports_state_their_limits(app, client, tenant, monkeypatch):
    def broken(inp):
        raise StageFailure("bad_input", "cannot", retryable=False)

    monkeypatch.setitem(registry.ENGINES, ("citation_consistency", "1"), broken)
    vid = _paper(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    pid = evaluate(client, tenant, vid, product="patent_integrity", key="eval-key-pat1").get_json()["id"]
    drain(app)
    rp = client.get(f"/api/v1/evaluations/{eid}/report", headers=h(tenant)).get_json()
    assert rp["evaluation"]["status"] == "partially_completed"
    assert rp["limitations"][0].startswith("Some optional stages did not complete")
    assert any("[citation_consistency] stage failed (bad_input)" in l for l in rp["limitations"])
    pt = client.get(f"/api/v1/evaluations/{pid}/report", headers=h(tenant)).get_json()
    assert "not a legal opinion" in pt["disclaimer"][0]


# ---------------------------------------------------------------- dissertation versions

def test_dissertation_compares_with_the_previous_version(app, client, tenant):
    from tests.test_version_diff import P1

    v1 = [[p, n, t] for p, n, t in P1]
    v2 = [list(x) for x in v1]
    v2[1][2] = v2[1][2].replace("teachers", "120 secondary school teachers")
    v2.append([3, 1, "An added chapter on ethics, consent procedures and the storage of interview data."])
    body1 = payload(text="\n".join(t for *_, t in v1), paragraphs=v1)
    doc = client.post("/api/v1/documents", json=body1, headers=h(tenant, key="doc-key-diss1")).get_json()
    body2 = payload(text="\n".join(t for *_, t in v2), paragraphs=v2)
    ver2 = client.post(f"/api/v1/documents/{doc['document_id']}/versions", json=body2,
                       headers=h(tenant, key="doc-key-diss2")).get_json()["version"]
    e1 = evaluate(client, tenant, doc["version"]["id"], product="dissertation", key="eval-diss-0001").get_json()["id"]
    e2 = evaluate(client, tenant, ver2["id"], product="dissertation", key="eval-diss-0002").get_json()["id"]
    drain(app, limit=40)
    first = read(client, tenant, e1)["stages"][3]
    assert first["name"] == "version_comparison" and first["result"]["payload"] == {"previous_version": None}
    second = read(client, tenant, e2)
    assert second["status"] == "completed"
    p = second["stages"][3]["result"]["payload"]
    assert p["previous_version"] == 1 and p["counts"] == {"unchanged": 3, "modified": 1, "added": 1, "removed": 0}
    report = client.get(f"/api/v1/evaluations/{e2}/report", headers=h(tenant)).get_json()
    assert report["stages"][3]["engine"]["name"] == "version_diff"


def test_long_stage_keeps_its_lease(app, client, tenant, monkeypatch):
    import threading
    import time

    from integrity.engines import content_check

    started = threading.Event()

    def slow(inp):
        started.set()
        time.sleep(3.5)  # longer than the 2 s lease
        return content_check.run(inp)

    monkeypatch.setitem(registry.ENGINES, ("content_check", "1"), slow)
    vid = ingest(client, tenant)
    eid = evaluate(client, tenant, vid).get_json()["id"]
    with session_scope(app) as s:
        claim = claim_next(s, "slow-worker", 2)
    stolen = []

    def competitor():
        started.wait()
        for _ in range(6):
            time.sleep(0.5)
            with session_scope(app) as s:
                if claim_next(s, "thief", 2) is not None:
                    stolen.append(1)

    t = threading.Thread(target=competitor)
    t.start()
    assert execute(app, claim) == StageStatus.SUCCEEDED
    t.join()
    assert stolen == []  # the renewed lease was never considered expired
    assert read(client, tenant, eid)["stages"][0]["attempt"] == 1

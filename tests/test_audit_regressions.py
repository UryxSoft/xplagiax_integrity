"""Regression tests for docs/AUDIT_PHASE1.md findings. Each test fails on commit cbd7c00.

They run on SQLite always and on MySQL when XI_TEST_MYSQL_URL is set (see the
``any_app`` fixture), because several findings were engine-specific.
"""

import io
import logging
import os

import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError

from integrity.app import create_app
from integrity.config import Settings
from integrity.core.ids import utcnow
from integrity.core.logging import JsonFormatter
from integrity.domain.enums import (
    ApiOutcome,
    CertificateStatus,
    ClientScope,
    EvaluationStatus,
    EvidenceKind,
    FindingNature,
    Product,
    ReportFormat,
    Severity,
    SourceKind,
)
from integrity.domain.evaluation_state import InvalidTransition
from integrity.infrastructure.db.models import (
    ApiRequest,
    Certificate,
    Document,
    DocumentVersion,
    EngineVersion,
    Evaluation,
    EvaluationStage,
    Evidence,
    ExternalSource,
    Finding,
    Organization,
    Report,
    ServiceClient,
)
from integrity.infrastructure.db.session import session_scope
from integrity.security.api_keys import generate_key
from tests.conftest import TEST_PEPPER, alembic_config

MYSQL_URL = os.environ.get("XI_TEST_MYSQL_URL")
SHA, OTHER_SHA = "c" * 64, "d" * 64


@pytest.fixture(params=["sqlite", "mysql"])
def any_app(request, tmp_path):
    if request.param == "mysql":
        if not MYSQL_URL:
            pytest.skip("XI_TEST_MYSQL_URL not set")
        url = MYSQL_URL
        command.downgrade(alembic_config(url), "base")
    else:
        url = f"sqlite:///{tmp_path / 'a.sqlite3'}"
    command.upgrade(alembic_config(url), "head")
    app = create_app(Settings(env="testing", database_url=url, api_key_pepper=TEST_PEPPER, log_level="ERROR"))
    yield app
    if request.param == "mysql":
        from integrity.infrastructure.db.session import get_engine

        get_engine(app).dispose()
        command.downgrade(alembic_config(url), "base")


@pytest.fixture()
def world(any_app):
    """Two organisations, a provider and an engine version."""
    with session_scope(any_app) as s:
        a, b = Organization(external_ref="org-a", name="a"), Organization(external_ref="org-b", name="b")
        src = ExternalSource(code="x", name="x", base_url="https://example.invalid")
        ev = EngineVersion(engine_name="e", version="1", config_sha256=SHA)
        s.add_all([a, b, src, ev])
        s.flush()
        return {"app": any_app, "A": a.id, "B": b.id, "SRC": src.id, "EV": ev.id}


def _evaluation(s, org, sha=SHA):
    d = Document(organization_id=org)
    s.add(d)
    s.flush()
    v = DocumentVersion(idempotency_key=__import__("os").urandom(8).hex(), organization_id=org, document_id=d.id, version_number=1,
                        source_kind=SourceKind.UPSTREAM_EXTRACTION, content_sha256=sha)
    s.add(v)
    s.flush()
    e = Evaluation(organization_id=org, document_version_id=v.id, product=Product.DISSERTATION,
                   idempotency_key=os.urandom(6).hex(), config_sha256=SHA)
    s.add(e)
    s.flush()
    return v, e


def _api_request(w, org, evaluation_id=None):
    return ApiRequest(organization_id=org, evaluation_id=evaluation_id, external_source_id=w["SRC"], operation="o",
                      request_fingerprint=SHA, outcome=ApiOutcome.OK, adapter_version="1")


def _finding(w, org, evaluation_id, stage_id):
    return Finding(organization_id=org, evaluation_id=evaluation_id, stage_id=stage_id, engine_version_id=w["EV"],
                   category="c", nature=FindingNature.TEXTUAL_MATCH, severity=Severity.LOW,
                   title="t", description="d", method="m")


def _rejected(app, fn):
    # DBAPIError, not IntegrityError: MySQL/MariaDB report CHECK violations as
    # OperationalError while FK violations are IntegrityError.
    with pytest.raises(DBAPIError):
        with session_scope(app) as s:
            fn(s)


# --- A1: cross-organisation links ------------------------------------------------

def test_a1_api_request_cannot_point_at_other_tenants_evaluation(world):
    def go(s):
        _, eb = _evaluation(s, world["B"])
        s.add(_api_request(world, world["A"], eb.id))

    _rejected(world["app"], go)


def test_a1_api_request_with_evaluation_requires_organization(world):
    def go(s):
        _, eb = _evaluation(s, world["B"])
        s.add(_api_request(world, None, eb.id))

    _rejected(world["app"], go)


def test_a1_evidence_cannot_cite_other_tenants_api_request(world):
    def go(s):
        _, eb = _evaluation(s, world["B"])
        rb = _api_request(world, world["B"], eb.id)
        s.add(rb)
        _, ea = _evaluation(s, world["A"])
        st = EvaluationStage(organization_id=world["A"], evaluation_id=ea.id, stage_name="s", sequence=1)
        s.add(st)
        s.flush()
        f = _finding(world, world["A"], ea.id, st.id)
        s.add(f)
        s.flush()
        s.add(Evidence(organization_id=world["A"], finding_id=f.id, kind=EvidenceKind.API_OUTCOME, api_request_id=rb.id))

    _rejected(world["app"], go)


def test_a1_same_tenant_chain_is_accepted_and_system_calls_need_no_org(world):
    with session_scope(world["app"]) as s:
        _, ea = _evaluation(s, world["A"])
        ra = _api_request(world, world["A"], ea.id)
        st = EvaluationStage(organization_id=world["A"], evaluation_id=ea.id, stage_name="s", sequence=1)
        s.add_all([ra, st, _api_request(world, None)])  # provider health check: no tenant
        s.flush()
        f = _finding(world, world["A"], ea.id, st.id)
        s.add(f)
        s.flush()
        s.add(Evidence(organization_id=world["A"], finding_id=f.id, kind=EvidenceKind.API_OUTCOME, api_request_id=ra.id))


# --- M1: stage must belong to the same evaluation --------------------------------

def test_m1_finding_cannot_use_stage_of_another_evaluation(world):
    def go(s):
        _, e1 = _evaluation(s, world["A"])
        _, e2 = _evaluation(s, world["A"])
        st = EvaluationStage(organization_id=world["A"], evaluation_id=e2.id, stage_name="s", sequence=1)
        s.add(st)
        s.flush()
        s.add(_finding(world, world["A"], e1.id, st.id))

    _rejected(world["app"], go)


# --- A2: certificate integrity ----------------------------------------------------

def _certificate(org, e, v_id, sha, report_id=None, **kw):
    return Certificate(organization_id=org, evaluation_id=e.id, document_version_id=v_id, report_id=report_id,
                       verification_code=os.urandom(8).hex(), document_content_sha256=sha,
                       criteria_profile="p", criteria_version="1", criteria_sha256=SHA, **kw)


def test_a2_certificate_cannot_use_report_of_another_evaluation(world):
    def go(s):
        v1, e1 = _evaluation(s, world["A"])
        _, e2 = _evaluation(s, world["A"])
        r2 = Report(organization_id=world["A"], evaluation_id=e2.id, engine_version_id=world["EV"],
                    format=ReportFormat.JSON, schema_version="1", content_sha256=SHA)
        s.add(r2)
        s.flush()
        s.add(_certificate(world["A"], e1, v1.id, SHA, r2.id, status=CertificateStatus.CERTIFIED, issued_at=utcnow()))

    _rejected(world["app"], go)


def test_a2_certificate_hash_must_be_the_evaluated_versions_hash(world):
    def go(s):
        v1, e1 = _evaluation(s, world["A"])
        s.add(_certificate(world["A"], e1, v1.id, OTHER_SHA))

    _rejected(world["app"], go)


def test_a2_certificate_version_must_be_the_one_evaluated(world):
    def go(s):
        _, e1 = _evaluation(s, world["A"])
        v2, _ = _evaluation(s, world["A"])
        s.add(_certificate(world["A"], e1, v2.id, SHA))

    _rejected(world["app"], go)


def test_a2_consistent_certificate_is_accepted(world):
    with session_scope(world["app"]) as s:
        v1, e1 = _evaluation(s, world["A"])
        r1 = Report(organization_id=world["A"], evaluation_id=e1.id, engine_version_id=world["EV"],
                    format=ReportFormat.JSON, schema_version="1", content_sha256=SHA)
        s.add(r1)
        s.flush()
        s.add(_certificate(world["A"], e1, v1.id, SHA, r1.id, status=CertificateStatus.CERTIFIED, issued_at=utcnow()))


# --- M2: lifecycle and immutability -----------------------------------------------

def test_m2_stored_evaluation_cannot_skip_or_reverse_states(world):
    with session_scope(world["app"]) as s:
        _, e = _evaluation(s, world["A"])
        eid = e.id
    with session_scope(world["app"]) as s:
        e = s.get(Evaluation, eid)
        with pytest.raises(InvalidTransition):
            e.status = EvaluationStatus.COMPLETED
        e.status = EvaluationStatus.QUEUED
        e.status = EvaluationStatus.PROCESSING
        e.status = EvaluationStatus.COMPLETED
        with pytest.raises(InvalidTransition):
            e.status = EvaluationStatus.PENDING


def test_m2_stored_document_version_is_immutable(world):
    with session_scope(world["app"]) as s:
        v, _ = _evaluation(s, world["A"])
        vid = v.id
    with session_scope(world["app"]) as s:
        v = s.get(DocumentVersion, vid)
        with pytest.raises(ValueError, match="immutable"):
            v.content_sha256 = OTHER_SHA
        v.language = "es"  # descriptive metadata stays editable


# --- M4: identical identifier semantics on every engine ---------------------------

def test_m4_tenant_reference_is_case_sensitive_on_every_engine(world):
    key = generate_key(TEST_PEPPER)
    with session_scope(world["app"]) as s:
        s.add(ServiceClient(name="c", key_prefix=key.prefix, key_hash=key.digest, scope=ClientScope.PLATFORM))
    client = world["app"].test_client()

    def status(ref):
        return client.get("/api/v1/auth/context",
                          headers={"Authorization": f"Bearer {key.plaintext}", "X-Integrity-Org": ref}).status_code

    assert (status("org-a"), status("ORG-A"), status("Org-A")) == (200, 403, 403)


# --- A3: no document data in logs -------------------------------------------------

def test_a3_database_errors_do_not_log_bound_parameters(any_app):
    marker = "CONFIDENTIAL-INVENTION-TITLE"

    def leak():
        from integrity.infrastructure.db.session import db_session

        s = db_session()
        s.add(Document(organization_id="no-such-org", title=marker))
        s.commit()
        return "unreachable"

    any_app.add_url_rule("/_leak", "leak", leak)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    try:
        r = any_app.test_client().get("/_leak")
    finally:
        logging.getLogger().removeHandler(handler)
    assert r.status_code == 500
    assert "unhandled_exception" in buf.getvalue()  # the error IS logged...
    assert marker not in buf.getvalue()             # ...without the data
    assert marker not in r.get_data(as_text=True)

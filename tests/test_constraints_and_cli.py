from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from integrity.domain.enums import (
    CertificateStatus,
    FindingNature,
    Product,
    Severity,
    SourceKind,
)
from integrity.infrastructure.db.models import (
    AuditEvent,
    Certificate,
    Document,
    DocumentVersion,
    EngineVersion,
    Evaluation,
    EvaluationStage,
    Finding,
    ServiceClient,
)
from integrity.infrastructure.db.session import session_scope

SHA = "a" * 64


def _evaluation(s, org):
    d = Document(organization_id=org)
    s.add(d)
    s.flush()
    v = DocumentVersion(organization_id=org, document_id=d.id, version_number=1,
                        source_kind=SourceKind.UPSTREAM_EXTRACTION, content_sha256=SHA)
    s.add(v)
    s.flush()
    e = Evaluation(organization_id=org, document_version_id=v.id, product=Product.DISSERTATION,
                   idempotency_key="k", config_sha256=SHA)
    s.add(e)
    s.flush()
    return e


def test_certificate_cannot_be_certified_without_report(app, factory):
    org = factory.org()
    with pytest.raises(IntegrityError):
        with session_scope(app) as s:
            e = _evaluation(s, org)
            s.add(Certificate(organization_id=org, evaluation_id=e.id, status=CertificateStatus.CERTIFIED,
                              verification_code="ABC", document_content_sha256=SHA,
                              criteria_profile="default", criteria_version="1"))


def test_finding_confidence_must_be_in_unit_range(app, factory):
    org = factory.org()
    with pytest.raises(IntegrityError):
        with session_scope(app) as s:
            e = _evaluation(s, org)
            ev = EngineVersion(engine_name="x", version="0", config_sha256=SHA)
            st = EvaluationStage(organization_id=org, evaluation_id=e.id, stage_name="s", sequence=1)
            s.add_all([ev, st])
            s.flush()
            s.add(Finding(organization_id=org, evaluation_id=e.id, stage_id=st.id, engine_version_id=ev.id,
                          category="c", nature=FindingNature.SEMANTIC_SIMILARITY, severity=Severity.LOW,
                          title="t", description="d", method="m", confidence=Decimal("1.5"),
                          confidence_calibrated=False))


def test_invalid_enum_value_rejected_in_python(app, factory):
    org = factory.org()
    with pytest.raises(Exception):
        with session_scope(app) as s:
            d = Document(organization_id=org, product_hint="not-a-product")
            s.add(d)
            s.flush()


def test_cli_create_org_and_platform_client_then_authenticate(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["integrity", "create-org", "--external-ref", "org-x", "--name", "Org X"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(args=["integrity", "create-client", "--name", "appcli2", "--scope", "platform"])
    assert r.exit_code == 0, r.output
    key = [l.split("=", 1)[1] for l in r.output.splitlines() if l.startswith("api_key=")][0]
    resp = app.test_client().get("/api/v1/auth/context",
                                 headers={"Authorization": f"Bearer {key}", "X-Integrity-Org": "org-x"})
    assert resp.status_code == 200
    with session_scope(app) as s:
        stored = s.scalars(select(ServiceClient)).one()
        assert key not in (stored.key_hash, stored.key_prefix)
        actions = {a.action for a in s.scalars(select(AuditEvent))}
        assert {"organization.created", "service_client.created"} <= actions


def test_cli_scope_validation(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["integrity", "create-client", "--name", "x", "--scope", "organization"])
    assert r.exit_code != 0
    r = runner.invoke(args=["integrity", "create-client", "--name", "x", "--scope", "platform", "--org-ref", "a"])
    assert r.exit_code != 0


def test_cli_revoke_client(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["integrity", "create-client", "--name", "c", "--scope", "platform"])
    cid = [l.split("=", 1)[1] for l in r.output.splitlines() if l.startswith("client_id=")][0]
    key = [l.split("=", 1)[1] for l in r.output.splitlines() if l.startswith("api_key=")][0]
    assert runner.invoke(args=["integrity", "revoke-client", cid]).exit_code == 0
    assert app.test_client().get("/api/v1/auth/context", headers={"Authorization": f"Bearer {key}"}).status_code == 401

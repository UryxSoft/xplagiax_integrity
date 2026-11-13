"""Database-level guarantees: a row can never point at another tenant's parent."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from integrity.domain.enums import Product, SourceKind
from integrity.infrastructure.db.models import Document, DocumentVersion, Evaluation
from integrity.infrastructure.db.session import session_scope
from integrity.infrastructure.db.tenant import scoped_select

SHA = "0" * 64


def _doc_version(s, org_id):
    d = Document(organization_id=org_id, title="t")
    s.add(d)
    s.flush()
    v = DocumentVersion(organization_id=org_id, document_id=d.id, version_number=1,
                        source_kind=SourceKind.UPSTREAM_EXTRACTION, content_sha256=SHA)
    s.add(v)
    s.flush()
    return d, v


def test_evaluation_cannot_reference_other_tenants_document(app, factory):
    a, b = factory.org("org-a"), factory.org("org-b")
    with session_scope(app) as s:
        _, v_b = _doc_version(s, b)
        vb_id = v_b.id
    with pytest.raises(IntegrityError):
        with session_scope(app) as s:
            s.add(Evaluation(organization_id=a, document_version_id=vb_id, product=Product.RESEARCH_PAPER,
                             idempotency_key="k1", config_sha256=SHA))


def test_version_cannot_attach_to_other_tenants_document(app, factory):
    a, b = factory.org("org-a"), factory.org("org-b")
    with session_scope(app) as s:
        d_b, _ = _doc_version(s, b)
        db_id = d_b.id
    with pytest.raises(IntegrityError):
        with session_scope(app) as s:
            s.add(DocumentVersion(organization_id=a, document_id=db_id, version_number=2,
                                  source_kind=SourceKind.UPSTREAM_EXTRACTION, content_sha256=SHA))


def test_same_tenant_link_is_accepted_and_idempotency_enforced(app, factory):
    a = factory.org("org-a")
    with session_scope(app) as s:
        _, v = _doc_version(s, a)
        s.add(Evaluation(organization_id=a, document_version_id=v.id, product=Product.DISSERTATION,
                         idempotency_key="same", config_sha256=SHA))
        vid = v.id
    with pytest.raises(IntegrityError):
        with session_scope(app) as s:
            s.add(Evaluation(organization_id=a, document_version_id=vid, product=Product.DISSERTATION,
                             idempotency_key="same", config_sha256=SHA))


def test_scoped_select_only_returns_own_rows(app, factory):
    a, b = factory.org("org-a"), factory.org("org-b")
    with session_scope(app) as s:
        _doc_version(s, a)
        _doc_version(s, b)
    with session_scope(app) as s:
        rows = s.scalars(scoped_select(Document, a)).all()
        assert len(rows) == 1 and rows[0].organization_id == a
        assert len(s.scalars(select(Document)).all()) == 2


def test_scoped_select_rejects_missing_org_and_global_models():
    from integrity.infrastructure.db.models import ExternalSource

    with pytest.raises(ValueError):
        scoped_select(Document, "")
    with pytest.raises(TypeError):
        scoped_select(ExternalSource, "org")

"""Opt-in: runs only when XI_TEST_MYSQL_URL points at a disposable MySQL/MariaDB database.

    XI_TEST_MYSQL_URL=mysql+pymysql://user:pass@127.0.0.1:3306/xi_test pytest tests/test_mysql_integration.py

The database is wiped (downgrade base) before and after.
"""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from integrity.app import create_app
from integrity.config import Settings
from integrity.domain.enums import Product, SourceKind
from integrity.infrastructure.db.models import Base, Document, DocumentVersion, Evaluation, Organization
from integrity.infrastructure.db.session import session_scope
from tests.conftest import TEST_PEPPER, alembic_config

URL = os.environ.get("XI_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="XI_TEST_MYSQL_URL not set")
SHA = "b" * 64


@pytest.fixture()
def mysql_app():
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    app = create_app(Settings(env="testing", database_url=URL, api_key_pepper=TEST_PEPPER, log_level="WARNING"))
    yield app
    command.downgrade(cfg, "base")


def test_schema_matches_models_on_mysql(mysql_app):
    with create_engine(URL).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], diff


def test_ready_and_tenant_fk_on_mysql(mysql_app):
    assert mysql_app.test_client().get("/api/v1/health/ready").status_code == 200
    with session_scope(mysql_app) as s:
        a, b = Organization(external_ref="a", name="a"), Organization(external_ref="b", name="b")
        s.add_all([a, b])
        s.flush()
        d = Document(organization_id=b.id)
        s.add(d)
        s.flush()
        v = DocumentVersion(organization_id=b.id, document_id=d.id, version_number=1,
                            source_kind=SourceKind.UPSTREAM_EXTRACTION, content_sha256=SHA)
        s.add(v)
        s.flush()
        a_id, v_id = a.id, v.id
    with pytest.raises(IntegrityError):
        with session_scope(mysql_app) as s:
            s.add(Evaluation(organization_id=a_id, document_version_id=v_id, product=Product.PATENT_INTEGRITY,
                             idempotency_key="k", config_sha256=SHA))


def test_datetime_microseconds_and_tz_roundtrip(mysql_app):
    from integrity.core.ids import utcnow

    now = utcnow()
    with session_scope(mysql_app) as s:
        o = Organization(external_ref="t", name="t", created_at=now)
        s.add(o)
        s.flush()
        oid = o.id
    with session_scope(mysql_app) as s:
        got = s.get(Organization, oid).created_at
    assert got == now and got.tzinfo is not None

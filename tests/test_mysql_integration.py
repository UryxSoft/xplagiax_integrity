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
        v = DocumentVersion(idempotency_key=__import__("os").urandom(8).hex(), organization_id=b.id, document_id=d.id, version_number=1,
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


def test_concurrent_ingestion_with_same_key_creates_one_version(mysql_app):
    """Real InnoDB row locking: N parallel identical requests -> exactly one version."""
    import threading

    from sqlalchemy import func, select

    from integrity.domain.enums import ClientScope
    from integrity.infrastructure.db.models import DocumentVersion, ServiceClient
    from integrity.security.api_keys import generate_key
    from tests.test_documents import payload

    key = generate_key(TEST_PEPPER)
    with session_scope(mysql_app) as s:
        s.add(Organization(external_ref="user:1", name="u1"))
        s.add(ServiceClient(name="c", key_prefix=key.prefix, key_hash=key.digest, scope=ClientScope.PLATFORM))
    headers = {"Authorization": f"Bearer {key.plaintext}", "X-Integrity-Org": "user:1",
               "Idempotency-Key": "race-key-mysql-1"}
    statuses: list[int] = []
    lock = threading.Lock()

    def go():
        r = mysql_app.test_client().post("/api/v1/documents", json=payload(), headers=headers)
        with lock:
            statuses.append(r.status_code)

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert statuses.count(201) == 1, statuses
    assert set(statuses) <= {200, 201}, statuses
    with session_scope(mysql_app) as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 1


def test_concurrent_tenant_provisioning_is_idempotent(mysql_app):
    import threading

    from sqlalchemy import func, select

    from integrity.domain.enums import ClientScope
    from integrity.infrastructure.db.models import ServiceClient, User
    from integrity.security.api_keys import generate_key

    key = generate_key(TEST_PEPPER)
    with session_scope(mysql_app) as s:
        s.add(ServiceClient(name="c", key_prefix=key.prefix, key_hash=key.digest, scope=ClientScope.PLATFORM))
    h = {"Authorization": f"Bearer {key.plaintext}"}
    statuses: list[int] = []
    lock = threading.Lock()

    def go(url, body):
        r = mysql_app.test_client().put(url, json=body, headers=h)
        with lock:
            statuses.append(r.status_code)

    for url, body in (("/api/v1/organizations/user:7", {"name": "u7"}),
                      ("/api/v1/organizations/user:7/users/7", {})):
        statuses.clear()
        threads = [threading.Thread(target=go, args=(url, body)) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert statuses.count(201) == 1 and set(statuses) <= {200, 201}, (url, statuses)
    with session_scope(mysql_app) as s:
        assert s.scalar(select(func.count()).select_from(Organization)) == 1
        assert s.scalar(select(func.count()).select_from(User)) == 1


def test_parallel_workers_run_each_stage_exactly_once(mysql_app):
    """4 workers in parallel over 12 evaluations (24 stages) on InnoDB with SKIP LOCKED."""
    import threading

    from sqlalchemy import func, select

    from integrity.domain.enums import ClientScope, EvaluationStatus, StageStatus
    from integrity.infrastructure.db.models import EvaluationResult, EvaluationStage, ServiceClient
    from integrity.security.api_keys import generate_key
    from integrity.workers.runner import run_once
    from tests.test_documents import payload

    key = generate_key(TEST_PEPPER)
    with session_scope(mysql_app) as s:
        s.add(Organization(external_ref="user:1", name="u1"))
        s.add(ServiceClient(name="c", key_prefix=key.prefix, key_hash=key.digest, scope=ClientScope.PLATFORM))
    c = mysql_app.test_client()
    base = {"Authorization": f"Bearer {key.plaintext}", "X-Integrity-Org": "user:1"}
    for i in range(12):
        body = payload(text=f"Document number {i}. " + "Enough words to be analysed here. " * 3 + "doi:10.1000/x" + str(i))
        v = c.post("/api/v1/documents", json=body, headers={**base, "Idempotency-Key": f"doc-key-{i:04d}"}).get_json()
        r = c.post("/api/v1/evaluations", json={"document_version_id": v["version"]["id"], "product": "research_paper"},
                   headers={**base, "Idempotency-Key": f"eval-key-{i:04d}"})
        assert r.status_code == 202

    errors = []

    def worker(n):
        try:
            idle = 0
            while idle < 3:
                idle = idle + 1 if run_once(mysql_app, f"w{n}") is None else 0
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    with session_scope(mysql_app) as s:
        stages = s.scalars(select(EvaluationStage)).all()
        assert len(stages) == 24
        assert all(st.status == StageStatus.SUCCEEDED and st.attempt == 1 for st in stages), \
            [(st.stage_name, st.status, st.attempt, st.error_code) for st in stages if st.attempt != 1 or st.status != StageStatus.SUCCEEDED]
        assert s.scalar(select(func.count()).select_from(EvaluationResult)) == 24
        from integrity.infrastructure.db.models import Evaluation
        assert {e.status for e in s.scalars(select(Evaluation))} == {EvaluationStatus.COMPLETED}

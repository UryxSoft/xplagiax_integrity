from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from integrity.infrastructure.db.models import Base
from tests.conftest import alembic_config


def test_upgrade_head_matches_models(migrated_db_url):
    engine = create_engine(migrated_db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models and migrations diverge: {diff}"


def test_downgrade_to_base_and_back(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert set(inspect(create_engine(db_url)).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert "evaluations" in inspect(create_engine(db_url)).get_table_names()


def test_constraint_and_index_names_fit_mysql_limit():
    too_long = []
    for table in Base.metadata.sorted_tables:
        for item in list(table.constraints) + list(table.indexes):
            if item.name is not None and len(str(item.name)) > 64:
                too_long.append(str(item.name))
    assert not too_long


def test_every_tenant_owned_table_has_an_index_led_by_organization():
    """organization_id must be the first column of an explicit index or unique
    key on every tenant-owned table, so tenant filters never scan the table."""
    from sqlalchemy import UniqueConstraint

    missing = []
    for table in Base.metadata.sorted_tables:
        if "organization_id" not in table.c:
            continue
        leading = {list(ix.columns.keys())[0] for ix in table.indexes}
        leading |= {list(c.columns.keys())[0] for c in table.constraints if isinstance(c, UniqueConstraint)}
        if "organization_id" not in leading:
            missing.append(table.name)
    assert not missing, missing


def test_offline_mysql_ddl_renders(tmp_path, capsys):
    """Generate MySQL DDL without a server, to catch dialect-specific errors."""
    cfg = alembic_config("mysql+pymysql://u:p@localhost/x")
    command.upgrade(cfg, "head", sql=True)
    ddl = capsys.readouterr().out
    assert "DATETIME(6)" in ddl
    assert "ENGINE=InnoDB" in ddl and "CHARSET=utf8mb4" in ddl
    assert ddl.count("COLLATE utf8mb4_bin") == len(Base.metadata.tables)
    assert "FOREIGN KEY(document_version_id, organization_id) REFERENCES document_versions (id, organization_id)" in ddl


def test_expected_schema_heads_constant_matches_alembic():
    from alembic.script import ScriptDirectory

    from integrity.infrastructure.db.schema_version import EXPECTED_SCHEMA_HEADS
    from tests.conftest import alembic_config

    heads = frozenset(ScriptDirectory.from_config(alembic_config("sqlite://")).get_heads())
    assert heads == EXPECTED_SCHEMA_HEADS, "bump integrity/infrastructure/db/schema_version.py"


def test_web_process_does_not_import_alembic():
    import subprocess
    import sys

    code = ("import sys; from integrity.app import create_app; from integrity.config import Settings;"
            "a=create_app(Settings(env='testing', database_url='sqlite://', log_level='ERROR'));"
            "a.test_client().get('/api/v1/health/ready'); print('alembic' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out.splitlines()[-1] == "False"


def test_0002_upgrades_a_database_that_already_has_versions(db_url):
    """New NOT NULL columns must be backfilled, not just added."""
    from sqlalchemy import text

    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0001")
    engine = create_engine(db_url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO organizations (id, external_ref, name, status, created_at, updated_at) "
                       "VALUES ('o1', 'org', 'Org', 'active', '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO documents (id, organization_id, created_at) VALUES ('d1', 'o1', '2026-01-01')"))
        c.execute(text("INSERT INTO document_versions (id, organization_id, document_id, version_number, source_kind, "
                       "content_sha256, extraction_status, created_at) VALUES "
                       "('v1', 'o1', 'd1', 1, 'upstream_extraction', :h, 'complete', '2026-01-01')"), {"h": "0" * 64})
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        row = c.execute(text("SELECT idempotency_key, limitations FROM document_versions WHERE id='v1'")).one()
    assert row[0] == "legacy#v1" and row[1] == "[]"
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")

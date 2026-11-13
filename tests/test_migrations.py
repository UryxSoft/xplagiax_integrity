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


def test_every_tenant_owned_table_indexes_or_keys_organization():
    """organization_id must lead at least one index/unique key (fast tenant filtering)."""
    missing = []
    for table in Base.metadata.sorted_tables:
        if "organization_id" not in table.c:
            continue
        leading = {tuple(ix.columns.keys())[0] for ix in table.indexes}
        leading |= {tuple(c.columns.keys())[0] for c in table.constraints if hasattr(c, "columns") and len(c.columns)}
        if "organization_id" not in leading and "id" not in leading:
            missing.append(table.name)
    assert not missing


def test_offline_mysql_ddl_renders(tmp_path, capsys):
    """Generate MySQL DDL without a server, to catch dialect-specific errors."""
    cfg = alembic_config("mysql+pymysql://u:p@localhost/x")
    command.upgrade(cfg, "head", sql=True)
    ddl = capsys.readouterr().out
    assert "DATETIME(6)" in ddl
    assert "ENGINE=InnoDB" in ddl and "CHARSET=utf8mb4" in ddl
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

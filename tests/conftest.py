from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from integrity.app import create_app
from integrity.config import Settings
from integrity.domain.enums import ClientScope, UserRole
from integrity.infrastructure.db.models import Organization, ServiceClient, User
from integrity.infrastructure.db.session import session_scope
from integrity.security.api_keys import generate_key

ROOT = Path(__file__).resolve().parents[1]
TEST_PEPPER = "test-pepper-0123456789abcdef0123456789"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture()
def db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'test.sqlite3'}"


@pytest.fixture()
def migrated_db_url(db_url) -> str:
    command.upgrade(alembic_config(db_url), "head")
    return db_url


@pytest.fixture()
def settings(migrated_db_url) -> Settings:
    return Settings(env="testing", database_url=migrated_db_url, api_key_pepper=TEST_PEPPER, log_level="WARNING")


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def factory(app):
    """Helpers to create tenants, users and service clients directly in the DB."""

    class Factory:
        def org(self, ref: str = "org-a", **kw) -> str:
            with session_scope(app) as s:
                o = Organization(external_ref=ref, name=kw.pop("name", ref), **kw)
                s.add(o)
                s.flush()
                return o.id

        def user(self, org_id: str, ref: str = "user-1", role: UserRole = UserRole.MEMBER, **kw) -> str:
            with session_scope(app) as s:
                u = User(organization_id=org_id, external_ref=ref, role=role, **kw)
                s.add(u)
                s.flush()
                return u.id

        def service_client(self, scope: ClientScope = ClientScope.PLATFORM, org_id: str | None = None, **kw) -> tuple[str, str]:
            key = generate_key(TEST_PEPPER)
            with session_scope(app) as s:
                c = ServiceClient(name=kw.pop("name", "test-client"), key_prefix=key.prefix, key_hash=key.digest,
                                  scope=scope, organization_id=org_id, **kw)
                s.add(c)
                s.flush()
                return c.id, key.plaintext

    return Factory()

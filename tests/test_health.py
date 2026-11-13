from integrity.app import create_app
from integrity.config import Settings


def test_live(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_ready_with_migrated_schema(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.get_json()["checks"]["database"] == "ok"


def test_ready_reports_missing_schema(db_url):
    app = create_app(Settings(env="testing", database_url=db_url, log_level="WARNING"))
    r = app.test_client().get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.get_json() == {"status": "unavailable", "checks": {"database": "schema_missing"}}


def test_ready_reports_outdated_schema(app, client):
    from sqlalchemy import text

    from integrity.infrastructure.db.session import get_engine

    with get_engine(app).begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.get_json()["checks"]["database"] == "schema_outdated"


def test_ready_reports_unreachable_database(tmp_path):
    bad = f"sqlite:///{tmp_path / 'missing-dir' / 'x.sqlite3'}"
    app = create_app(Settings(env="testing", database_url=bad, log_level="ERROR"))
    r = app.test_client().get("/api/v1/health/ready")
    assert r.status_code == 503 and r.get_json()["checks"]["database"] == "unreachable"


def test_version_exposes_engine_maturity_honestly(client):
    body = client.get("/api/v1/version").get_json()
    assert body["api_version"] == "v1"
    names = {e["name"]: e["maturity"] for e in body["engines"]}
    assert len(names) == 13
    # Nothing scientific is claimed as implemented in the foundation phase.
    assert "implemented" not in names.values()


def test_security_headers(client):
    r = client.get("/api/v1/health/live")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"

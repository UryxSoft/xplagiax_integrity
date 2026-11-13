from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from flask import Flask, current_app, g
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from integrity.config import Settings


def build_engine(settings: Settings) -> Engine:
    url = settings.database_url
    if url.startswith("sqlite"):
        engine = create_engine(url, future=True)

        @event.listens_for(engine, "connect")
        def _sqlite_fk_on(dbapi_conn, _record):  # composite tenant FKs must be enforced in tests too
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(
        url,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_s, "charset": "utf8mb4"},
    )


def init_db(app: Flask, settings: Settings) -> None:
    engine = build_engine(settings)
    app.extensions["integrity.engine"] = engine
    app.extensions["integrity.sessionmaker"] = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @app.teardown_appcontext
    def _close_session(exc: BaseException | None) -> None:
        session: Session | None = g.pop("db_session", None)
        if session is not None:
            if exc is not None:
                session.rollback()
            session.close()


def get_engine(app: Flask | None = None) -> Engine:
    return (app or current_app).extensions["integrity.engine"]


def db_session() -> Session:
    """Request-scoped session (closed on app-context teardown)."""
    if "db_session" not in g:
        g.db_session = current_app.extensions["integrity.sessionmaker"]()
    return g.db_session


@contextmanager
def session_scope(app: Flask) -> Iterator[Session]:
    """Transactional scope for CLI / workers (no request context)."""
    session: Session = app.extensions["integrity.sessionmaker"]()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()

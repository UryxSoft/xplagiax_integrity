"""Health endpoints (unauthenticated, no tenant data, no internals leaked)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from sqlalchemy import text

from integrity import API_VERSION, __version__
from integrity.domain.capabilities import as_public_list
from integrity.infrastructure.db.schema_version import EXPECTED_SCHEMA_HEADS
from integrity.infrastructure.db.session import get_engine

log = logging.getLogger("integrity.health")


def _check_database() -> tuple[bool, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            try:
                rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            except Exception:
                return False, "schema_missing"
        if frozenset(rows) != EXPECTED_SCHEMA_HEADS:
            return False, "schema_outdated"
        return True, "ok"
    except Exception:
        log.exception("readiness_db_check_failed")
        return False, "unreachable"


def register(bp: Blueprint) -> None:
    @bp.get("/health/live")
    def live():
        return jsonify(status="ok")

    @bp.get("/health/ready")
    def ready():
        db_ok, db_state = _check_database()
        body = {"status": "ok" if db_ok else "unavailable", "checks": {"database": db_state}}
        return jsonify(body), (200 if db_ok else 503)

    @bp.get("/version")
    def version():
        return jsonify(
            service="xplagiax-integrity",
            version=__version__,
            api_version=API_VERSION,
            engines=as_public_list(),
        )

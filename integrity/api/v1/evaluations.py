"""Evaluation endpoints. Work happens in background workers; these only
create, read and cancel."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from integrity.api.v1.documents import _actor, _document_id, _idempotency_key
from integrity.application.evaluations import cancel_evaluation, create_evaluation, get_evaluation
from integrity.application.reports import build_report
from integrity.core.errors import ValidationFailed
from integrity.infrastructure.db.session import db_session
from integrity.security.auth import require_auth

_MAX_PROFILE = 64


def _iso(dt):
    return dt.isoformat() if dt else None


def _view_json(view) -> dict:
    ev = view.evaluation
    return {
        "id": ev.id,
        "product": ev.product.value,
        "status": ev.status.value,
        "document_version_id": ev.document_version_id,
        "upstream_ref": ev.upstream_ref,
        "config_sha256": ev.config_sha256,
        "criteria": {"profile": ev.criteria_profile, "version": ev.criteria_version},
        "error_code": ev.error_code,
        "created_at": _iso(ev.created_at), "started_at": _iso(ev.started_at), "finished_at": _iso(ev.finished_at),
        "stages": [
            {
                "name": st.stage_name,
                "sequence": st.sequence,
                "status": st.status.value,
                "attempt": st.attempt,
                "error_code": st.error_code,
                "started_at": _iso(st.started_at),
                "finished_at": _iso(st.finished_at),
                "result": ({"schema_version": r.schema_version, "payload": r.payload, "payload_sha256": r.payload_sha256,
                            "limitations": r.limitations}
                           if (r := view.results.get(st.id)) else None),
            }
            for st in view.stages
        ],
    }


def register(bp: Blueprint) -> None:
    @bp.post("/evaluations")
    @require_auth()
    def post_evaluation():
        key = _idempotency_key()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationFailed("A JSON object body is required.")
        version_id = body.get("document_version_id")
        if not isinstance(version_id, str):
            raise ValidationFailed("document_version_id is required.")
        profile, pversion = body.get("criteria_profile"), body.get("criteria_version")
        for name, v in (("criteria_profile", profile), ("criteria_version", pversion)):
            if v is not None and (not isinstance(v, str) or not 1 <= len(v) <= _MAX_PROFILE):
                raise ValidationFailed(f"{name} must be a string of 1-{_MAX_PROFILE} characters.")
        session = db_session()
        result = create_evaluation(session, _actor(), document_version_id=_document_id(version_id),
                                   product=str(body.get("product", "")), idempotency_key=key,
                                   criteria_profile=profile, criteria_version=pversion)
        session.commit()
        view = get_evaluation(session, _actor(), result.evaluation.id)
        return jsonify(_view_json(view)), (202 if result.created else 200)

    @bp.get("/evaluations/<evaluation_id>")
    @require_auth()
    def read_evaluation(evaluation_id: str):
        return jsonify(_view_json(get_evaluation(db_session(), _actor(), _document_id(evaluation_id))))

    @bp.get("/evaluations/<evaluation_id>/report")
    @require_auth()
    def read_report(evaluation_id: str):
        session = db_session()
        report = build_report(session, _actor(), _document_id(evaluation_id))
        session.commit()  # first generation records the report hash
        return jsonify(report)

    @bp.post("/evaluations/<evaluation_id>/cancel")
    @require_auth()
    def post_cancel(evaluation_id: str):
        session = db_session()
        ev = cancel_evaluation(session, _actor(), _document_id(evaluation_id))
        session.commit()
        return jsonify(_view_json(get_evaluation(session, _actor(), ev.id)))

from __future__ import annotations

from flask import Blueprint, Flask

from integrity.api.v1 import auth_context, health


def register_v1(app: Flask) -> None:
    bp = Blueprint("v1", __name__, url_prefix="/api/v1")
    health.register(bp)
    auth_context.register(bp)
    app.register_blueprint(bp)

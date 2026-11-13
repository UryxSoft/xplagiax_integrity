"""Flask application factory."""

from __future__ import annotations

import logging

from flask import Flask

from integrity.config import Settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = (settings or Settings.from_env()).validate()

    from integrity.core.logging import configure_logging, register_access_log

    configure_logging(settings.log_level)

    app = Flask("integrity")
    app.config.update(
        XI_SETTINGS=settings,
        MAX_CONTENT_LENGTH=settings.max_request_bytes,
        JSON_SORT_KEYS=False,
        TESTING=settings.env == "testing",
    )

    from integrity.api.v1 import register_v1
    from integrity.cli import register_cli
    from integrity.core.errors import register_error_handlers
    from integrity.core.request_context import register_request_context
    from integrity.infrastructure.db.session import init_db

    register_request_context(app)  # must run first: other hooks read the correlation id
    register_access_log(app)
    register_error_handlers(app)
    init_db(app, settings)
    register_v1(app)
    register_cli(app)

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    logging.getLogger("integrity").info("app_created", extra={"settings": settings.public_dict()})
    return app

"""Environment-driven configuration.

All configuration comes from environment variables (12-factor). No secrets have
defaults that are usable in production: ``validate()`` refuses to boot a
production app with missing or weak settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Mapping

_VALID_ENVS = ("development", "testing", "production")
_MIN_PEPPER_LEN = 32


class ConfigError(RuntimeError):
    """Raised when configuration is invalid. The app must not start."""


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    database_url: str = "sqlite:///./instance/integrity-dev.sqlite3"
    # HMAC pepper for API key hashing. Never logged, never returned.
    api_key_pepper: str = field(default="", repr=False)
    log_level: str = "INFO"
    # Hard cap on any request body (bytes). Sized to the document contract's
    # 5M-character text limit: the text travels twice (``text`` and
    # ``paragraphs``), ~10.5 MB at the limit. Flask parses the whole body before
    # validation, so a larger cap only wastes memory (measured: docs/PERFORMANCE.md §1.2).
    max_request_bytes: int = 12 * 1024 * 1024
    db_pool_size: int = 5
    db_max_overflow: int = 2
    db_pool_recycle_s: int = 1800
    db_connect_timeout_s: int = 5
    # Upper bound for a single DB read/write; a hung database must not hang a worker.
    db_io_timeout_s: int = 30

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        # Fail closed: a deployment that forgets XI_ENV must not silently run
        # with development defaults (audit finding M3).
        name = env.get("XI_ENV")
        if not name:
            raise ConfigError(f"XI_ENV must be set explicitly to one of {_VALID_ENVS}")
        defaults = cls()
        return cls(
            env=name,
            database_url=env.get("XI_DATABASE_URL", defaults.database_url),
            api_key_pepper=env.get("XI_API_KEY_PEPPER", ""),
            log_level=env.get("XI_LOG_LEVEL", defaults.log_level).upper(),
            max_request_bytes=_int(env, "XI_MAX_REQUEST_BYTES", defaults.max_request_bytes),
            db_pool_size=_int(env, "XI_DB_POOL_SIZE", defaults.db_pool_size),
            db_max_overflow=_int(env, "XI_DB_MAX_OVERFLOW", defaults.db_max_overflow),
            db_pool_recycle_s=_int(env, "XI_DB_POOL_RECYCLE_S", defaults.db_pool_recycle_s),
            db_connect_timeout_s=_int(env, "XI_DB_CONNECT_TIMEOUT_S", defaults.db_connect_timeout_s),
            db_io_timeout_s=_int(env, "XI_DB_IO_TIMEOUT_S", defaults.db_io_timeout_s),
        )

    def validate(self) -> "Settings":
        errors: list[str] = []
        if self.env not in _VALID_ENVS:
            errors.append(f"XI_ENV must be one of {_VALID_ENVS}")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            errors.append("XI_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        if self.max_request_bytes <= 0:
            errors.append("XI_MAX_REQUEST_BYTES must be positive")
        if self.db_connect_timeout_s < 1 or self.db_io_timeout_s < 1:
            errors.append("database timeouts must be >= 1 second")
        if self.db_pool_size < 1 or self.db_max_overflow < 0:
            errors.append("XI_DB_POOL_SIZE must be >=1 and XI_DB_MAX_OVERFLOW >=0")
        if self.env == "production":
            if len(self.api_key_pepper) < _MIN_PEPPER_LEN:
                errors.append(f"XI_API_KEY_PEPPER must be set (>= {_MIN_PEPPER_LEN} chars) in production")
            if not self.database_url.startswith("mysql+pymysql://"):
                errors.append("XI_DATABASE_URL must be a mysql+pymysql:// URL in production")
            if self.log_level == "DEBUG":
                errors.append("XI_LOG_LEVEL=DEBUG is not allowed in production")
        if errors:
            raise ConfigError("; ".join(errors))
        return self

    @property
    def effective_pepper(self) -> str:
        """Pepper used for key hashing.

        Outside production a fixed, clearly-non-secret pepper is used so local
        development works without setup. ``validate()`` guarantees production
        never reaches this fallback.
        """
        return self.api_key_pepper or "insecure-development-pepper-do-not-use"

    def public_dict(self) -> dict[str, object]:
        """Non-secret view, safe for logs."""
        hidden = {"api_key_pepper", "database_url"}
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in hidden}

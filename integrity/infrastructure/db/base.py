from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, MetaData, String, TypeDecorator
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from integrity.core.ids import new_id

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

ID = String(36)
SHA256 = String(64)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC (MySQL DATETIME(6)); always returns tz-aware UTC."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not accepted; use integrity.core.ids.utcnow()")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=timezone.utc)


def enum_col(enum_cls: type[StrEnum], length: int = 32) -> Enum:
    """VARCHAR-backed enum validated in Python (no DB CHECK, to avoid
    migration drift when vocabularies grow). See docs/DATA_MODEL.md §2."""
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


JSONType = JSON().with_variant(mysql.JSON(), "mysql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: dict[Any, Any] = {datetime: UTCDateTime()}


class IdMixin:
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)


def tenant_fk(local_column: str, parent_table: str, **kw: Any):
    """Composite FK (child.x_id, child.organization_id) -> (parent.id, parent.organization_id).

    Makes it impossible *at the database level* to link a row to a parent
    owned by another organisation, even if application code has a bug.
    Requires ``UniqueConstraint("id", "organization_id")`` on the parent.
    """
    from sqlalchemy import ForeignKeyConstraint

    return ForeignKeyConstraint(
        [local_column, "organization_id"],
        [f"{parent_table}.id", f"{parent_table}.organization_id"],
        **kw,
    )


def tenant_key():
    from sqlalchemy import UniqueConstraint

    return UniqueConstraint("id", "organization_id")

"""Tenant-scoped query helpers.

Prefer :class:`integrity.infrastructure.db.repositories.TenantScope`, which
binds the organisation once. ``scoped_select`` remains for one-off queries.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select, select

from integrity.infrastructure.db.base import Base

M = TypeVar("M", bound=Base)


def scoped_select(model: type[M], organization_id: str) -> Select[tuple[M]]:
    if not organization_id:
        raise ValueError("organization_id is required for tenant-scoped queries")
    col = getattr(model, "organization_id", None)
    if col is None:
        raise TypeError(f"{model.__name__} is not tenant-owned")
    return select(model).where(col == organization_id)

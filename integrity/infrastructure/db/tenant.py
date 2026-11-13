"""Tenant-scoped query helpers.

Data-access code for tenant-owned tables must go through ``scoped_select``
(or add the same predicate) so that forgetting the organisation filter is a
visible deviation in review, not a silent default.
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

"""Conventions shared with the XplagiaX platform (xplagiax_appcli2 / marktrack).

These mirror what the platform already does, so identifiers and hashes can be
cross-referenced between systems. See docs/INTEGRATION_XPLAGIAX.md.
"""

from __future__ import annotations

import hashlib
import re

_REF = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
PERSONAL_ORG_PREFIX = "user:"


def text_sha256(text: str | None) -> str:
    """SHA-256 of the analysed text with all whitespace runs collapsed.

    Same definition the platform uses for the document hash on its existing
    certificates, so a hash computed here equals the one computed there for
    the same text regardless of line-wrapping differences.
    """
    return hashlib.sha256(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()


def is_valid_ref(value: object) -> bool:
    return isinstance(value, str) and bool(_REF.match(value))


def personal_org_ref(platform_user_id: int | str) -> str:
    """The platform has users but no organisation entity. Every platform user
    therefore gets a personal organisation, so tenant isolation in this
    service is at least per user. Institutions can be added later with their
    own prefix without changing existing rows."""
    ref = f"{PERSONAL_ORG_PREFIX}{platform_user_id}"
    if not is_valid_ref(ref):
        raise ValueError("invalid platform user id")
    return ref

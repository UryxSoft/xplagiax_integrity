"""Service API keys.

Format: ``xik_<prefix>_<secret>``
* prefix: 12 hex chars, stored in clear, used only for lookup;
* secret: 32 random bytes (urlsafe base64).

Stored value: HMAC-SHA256(pepper, full_key). Keys are high-entropy random
values, so a slow password hash adds no security, only CPU cost per request.
The pepper lives outside the database: a DB dump alone cannot verify keys.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

_KEY_RE = re.compile(r"^xik_([0-9a-f]{12})_([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class GeneratedKey:
    plaintext: str  # shown once, never stored
    prefix: str
    digest: str


def hash_key(key: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), key.encode(), hashlib.sha256).hexdigest()


def generate_key(pepper: str) -> GeneratedKey:
    prefix = secrets.token_hex(6)
    key = f"xik_{prefix}_{secrets.token_urlsafe(32)}"
    return GeneratedKey(plaintext=key, prefix=prefix, digest=hash_key(key, pepper))


def parse_prefix(key: str) -> str | None:
    m = _KEY_RE.match(key)
    return m.group(1) if m else None


def verify_key(key: str, stored_digest: str, pepper: str) -> bool:
    return hmac.compare_digest(hash_key(key, pepper), stored_digest)

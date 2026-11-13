"""Identifier and time helpers.

Primary keys are UUIDv7 (RFC 9562) rendered as 36-char strings:
* time-ordered -> good InnoDB clustered-index locality (vs. random UUIDv4),
* 74 random bits -> not enumerable by API consumers.
Trade-off: the creation timestamp is recoverable from the id. Acceptable here;
see docs/adr/0004-identifiers.md.
"""

from __future__ import annotations

import os
import secrets
import time
import uuid
from datetime import datetime, timezone

_B32_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no I, L, O, U, 0, 1


def uuid7() -> uuid.UUID:
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand >> 62) & 0xFFF
    rand_b = rand & ((1 << 62) - 1)
    value = ((ts_ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def new_id() -> str:
    return str(uuid7())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def human_code(length: int = 16) -> str:
    """Random, unambiguous, uppercase code (e.g. certificate verification codes).

    16 chars over a 30-symbol alphabet ~= 78.5 bits of entropy.
    """
    return "".join(secrets.choice(_B32_ALPHABET) for _ in range(length))

"""Content storage for document versions.

Current backend: compressed rows in ``document_contents`` (MySQL). The
interface is deliberately small so a SeaweedFS backend can replace it.

Format ``zlib+json/v1``: zlib-compressed UTF-8 JSON
``{"text": str, "paragraphs": [[page, number, text], ...]}``.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from integrity.infrastructure.db.models import DocumentContent

CODEC = "zlib+json/v1"
_LEVEL = 6  # measured trade-off; see docs/PERFORMANCE.md


class ContentIntegrityError(RuntimeError):
    """Stored blob does not match its recorded hash (corruption or tampering)."""


@dataclass(frozen=True)
class StoredContent:
    text: str
    paragraphs: list[tuple[int, int, str]]


def encode(text: str, paragraphs) -> bytes:
    raw = json.dumps({"text": text, "paragraphs": [[p.page, p.number, p.text] for p in paragraphs]},
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw, _LEVEL)


def put(session: Session, *, organization_id: str, version_id: str, text: str, paragraphs) -> DocumentContent:
    blob = encode(text, paragraphs)
    row = DocumentContent(version_id=version_id, organization_id=organization_id, codec=CODEC, payload=blob,
                          payload_bytes=len(blob), payload_sha256=hashlib.sha256(blob).hexdigest())
    session.add(row)
    return row


def get(session: Session, *, organization_id: str, version_id: str) -> StoredContent | None:
    row = session.get(DocumentContent, version_id)
    if row is None or row.organization_id != organization_id:
        return None
    if row.codec != CODEC:
        raise ContentIntegrityError(f"unsupported codec {row.codec}")
    if hashlib.sha256(row.payload).hexdigest() != row.payload_sha256:
        raise ContentIntegrityError("stored content hash mismatch")
    data = json.loads(zlib.decompress(row.payload))
    return StoredContent(text=data["text"], paragraphs=[tuple(p) for p in data["paragraphs"]])


def delete_for_versions(session: Session, *, organization_id: str, version_ids: list[str]) -> int:
    if not version_ids:
        return 0
    result = session.execute(delete(DocumentContent).where(
        DocumentContent.organization_id == organization_id, DocumentContent.version_id.in_(version_ids)))
    return result.rowcount or 0

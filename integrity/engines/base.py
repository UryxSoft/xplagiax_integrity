from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageInput:
    text: str
    paragraphs: list[tuple[int, int, str]]
    expected_content_sha256: str
    language: str | None
    extraction_status: str
    upstream_limitations: tuple[str, ...]


@dataclass(frozen=True)
class StageOutput:
    payload: dict[str, Any]
    limitations: tuple[str, ...] = field(default_factory=tuple)


class StageFailure(Exception):
    """Raised by an engine. ``retryable=False`` fails the stage immediately."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable

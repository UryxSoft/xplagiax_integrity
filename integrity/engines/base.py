from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from integrity.domain.enums import EvidenceKind, FindingNature, Severity


@dataclass(frozen=True)
class PreviousVersion:
    version_number: int
    content_sha256: str
    text: str | None                     # None when its content was purged
    paragraphs: list[tuple[int, int, str]]


@dataclass(frozen=True)
class StageInput:
    text: str
    paragraphs: list[tuple[int, int, str]]
    expected_content_sha256: str
    language: str | None
    extraction_status: str
    upstream_limitations: tuple[str, ...]
    # Loaded only for engines that declare NEEDS_PREVIOUS.
    previous: PreviousVersion | None = None


@dataclass(frozen=True)
class EvidenceDraft:
    kind: EvidenceKind
    locator: dict[str, Any] | None = None
    excerpt: str | None = None          # from the user's own document only
    external_identifier: str | None = None
    external_url: str | None = None


@dataclass(frozen=True)
class FindingDraft:
    """A finding as produced by an engine. Every finding must carry evidence
    and its epistemic nature (docs/SCIENTIFIC_VALIDATION.md)."""

    category: str
    nature: FindingNature
    severity: Severity
    title: str
    description: str
    method: str
    location: dict[str, Any] | None
    evidence: tuple[EvidenceDraft, ...]
    limitations: tuple[str, ...] = ()
    recommendation: str | None = None
    confidence: float | None = None
    confidence_calibrated: bool | None = None

    def __post_init__(self):
        if not self.evidence:
            raise ValueError("a finding without evidence is not allowed")
        if self.confidence is not None and self.confidence_calibrated is None:
            raise ValueError("a confidence value must state whether it is calibrated")


@dataclass(frozen=True)
class StageOutput:
    payload: dict[str, Any]
    limitations: tuple[str, ...] = field(default_factory=tuple)
    findings: tuple[FindingDraft, ...] = field(default_factory=tuple)


class StageFailure(Exception):
    """Raised by an engine. ``retryable=False`` fails the stage immediately."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable

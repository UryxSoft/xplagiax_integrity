"""Verifies that the content about to be analysed is exactly the content that
was ingested (hash match) and summarises its quality. Every pipeline starts
here: no engine may run on content whose identity is not established."""

from __future__ import annotations

from integrity.domain.upstream import text_sha256
from integrity.engines.base import StageFailure, StageInput, StageOutput

NAME, VERSION = "content_check", "1"


def run(inp: StageInput) -> StageOutput:
    actual = text_sha256(inp.text)
    if actual != inp.expected_content_sha256:
        raise StageFailure("content_hash_mismatch",
                           "Stored content does not match the hash recorded at ingestion.", retryable=False)
    pages = sorted({p for p, _, _ in inp.paragraphs})
    limitations = list(inp.upstream_limitations)
    if not inp.paragraphs:
        limitations.append("No paragraph structure received: locations are character offsets in the full text.")
    return StageOutput(
        payload={
            "content_sha256": actual,
            "words": len(inp.text.split()),
            "characters": len(inp.text),
            "paragraphs": len(inp.paragraphs),
            "pages_with_paragraphs": len(pages),
            "language": inp.language,
            "extraction_status": inp.extraction_status,
        },
        limitations=tuple(limitations),
    )

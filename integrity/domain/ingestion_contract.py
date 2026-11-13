"""Input document contract ``xplagiax.document/v1`` (docs/API_CONTRACTS.md §3).

Pure validation: no Flask, no database. Returns an immutable
:class:`IncomingDocument` or raises :class:`ContractViolation` listing every
problem found (so the caller can fix them all in one round trip).

Limits are deliberately conservative and configurable through
:class:`ContractLimits`; they bound memory and CPU per request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from integrity.domain.enums import ExtractionStatus
from integrity.domain.upstream import is_valid_ref, text_sha256

SCHEMA_ID = "xplagiax.document/v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# BCP-47-like: "en", "es", "pt-BR", "zh-Hant". "unknown" is what appcli2 sends when detection fails.
_LANG = re.compile(r"^(?:[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}|unknown)$")
_MIME = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$")
_UPSTREAM_STATUS = {"complete": ExtractionStatus.COMPLETE, "partial": ExtractionStatus.PARTIAL}


class ContractViolation(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class InsufficientContent(ValueError):
    """The document is well-formed but cannot be analysed (empty, failed extraction, too short)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ContractLimits:
    max_text_chars: int = 5_000_000          # ~1,500 pages of dense text
    max_paragraphs: int = 50_000
    max_paragraph_chars: int = 50_000
    max_pages: int = 10_000
    min_words: int = 10                      # same floor appcli2 applies before analysis
    max_title_chars: int = 512


@dataclass(frozen=True)
class Paragraph:
    page: int
    number: int
    text: str


@dataclass(frozen=True)
class IncomingDocument:
    text: str
    content_sha256: str
    word_count: int
    char_count: int
    paragraphs: tuple[Paragraph, ...]
    language: str | None
    title: str | None
    extraction_status: ExtractionStatus
    page_count: int | None
    pages_failed: tuple[int, ...]
    pages_needing_ocr: tuple[int, ...]
    producer: str
    producer_version: str | None
    analysis_ref: str | None
    file_sha256: str | None
    filename: str | None
    mime_type: str | None
    limitations: tuple[str, ...] = field(default_factory=tuple)


def _opt_str(obj: dict, key: str, problems: list[str], max_len: int, where: str) -> str | None:
    v = obj.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > max_len:
        problems.append(f"{where}.{key} must be a string of at most {max_len} characters")
        return None
    return v


def _int_list(obj: dict, key: str, problems: list[str], where: str, max_page: int) -> tuple[int, ...]:
    v = obj.get(key, [])
    if v is None:
        return ()
    if not isinstance(v, list) or not all(isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= max_page for i in v):
        problems.append(f"{where}.{key} must be a list of page numbers between 1 and {max_page}")
        return ()
    return tuple(sorted(set(v)))


def parse_document(payload: Any, limits: ContractLimits = ContractLimits()) -> IncomingDocument:
    if not isinstance(payload, dict):
        raise ContractViolation(["body must be a JSON object"])
    problems: list[str] = []

    if payload.get("schema") != SCHEMA_ID:
        problems.append(f"schema must be '{SCHEMA_ID}'")

    # --- source -------------------------------------------------------------
    source = payload.get("source")
    if not isinstance(source, dict):
        problems.append("source must be an object")
        source = {}
    producer = source.get("producer")
    if not isinstance(producer, str) or not is_valid_ref(producer):
        problems.append("source.producer is required ([A-Za-z0-9._:-]{1,64})")
    producer_version = _opt_str(source, "producer_version", problems, 64, "source")
    analysis_ref = source.get("analysis_ref")
    if analysis_ref is not None and not is_valid_ref(analysis_ref):
        problems.append("source.analysis_ref has an invalid format")
        analysis_ref = None
    file_sha256 = source.get("file_sha256")
    if file_sha256 is not None and not (isinstance(file_sha256, str) and _HEX64.match(file_sha256)):
        problems.append("source.file_sha256 must be 64 lowercase hex characters")
        file_sha256 = None
    filename = _opt_str(source, "filename", problems, 255, "source")
    mime_type = source.get("mime_type")
    if mime_type is not None and not (isinstance(mime_type, str) and _MIME.match(mime_type)):
        problems.append("source.mime_type is not a valid media type")
        mime_type = None

    # --- text ---------------------------------------------------------------
    text = payload.get("text")
    if not isinstance(text, str):
        problems.append("text is required and must be a string")
        text = ""
    elif len(text) > limits.max_text_chars:
        problems.append(f"text exceeds {limits.max_text_chars} characters")
    if "\x00" in text:
        problems.append("text must not contain NUL characters")

    # --- paragraphs (optional) ----------------------------------------------
    paragraphs: list[Paragraph] = []
    raw_pars = payload.get("paragraphs")
    if raw_pars is not None:
        if not isinstance(raw_pars, list):
            problems.append("paragraphs must be a list of [page, number, text]")
        elif len(raw_pars) > limits.max_paragraphs:
            problems.append(f"paragraphs exceeds {limits.max_paragraphs} items")
        else:
            seen: set[tuple[int, int]] = set()
            for i, p in enumerate(raw_pars):
                ok = (isinstance(p, list) and len(p) == 3
                      and isinstance(p[0], int) and not isinstance(p[0], bool) and 1 <= p[0] <= limits.max_pages
                      and isinstance(p[1], int) and not isinstance(p[1], bool) and p[1] >= 1
                      and isinstance(p[2], str) and len(p[2]) <= limits.max_paragraph_chars and "\x00" not in p[2])
                if not ok:
                    problems.append(f"paragraphs[{i}] must be [page>=1, number>=1, text<= {limits.max_paragraph_chars} chars]")
                    if len(problems) > 50:
                        break
                    continue
                key = (p[0], p[1])
                if key in seen:
                    problems.append(f"paragraphs[{i}] duplicates page {p[0]} paragraph {p[1]}")
                    continue
                seen.add(key)
                paragraphs.append(Paragraph(p[0], p[1], p[2]))

    # --- descriptive fields --------------------------------------------------
    language = payload.get("language")
    if language is not None and not (isinstance(language, str) and _LANG.match(language)):
        problems.append("language must be a BCP-47 tag or 'unknown'")
        language = None
    if language == "unknown":
        language = None
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        problems.append("metadata must be an object")
        metadata = {}
    title = metadata.get("title")
    if title is not None and not isinstance(title, str):
        problems.append("metadata.title must be a string")
        title = None
    if isinstance(title, str):
        title = title.strip()[: limits.max_title_chars] or None

    declared_words = payload.get("word_count")
    if declared_words is not None and (not isinstance(declared_words, int) or isinstance(declared_words, bool) or declared_words < 0):
        problems.append("word_count must be a non-negative integer")

    # --- extraction quality ---------------------------------------------------
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict):
        problems.append("extraction must be an object")
        extraction = {}
    raw_status = extraction.get("status")
    if raw_status not in ("complete", "partial", "failed"):
        problems.append("extraction.status must be 'complete', 'partial' or 'failed'")
    pages_total = extraction.get("pages_total")
    if pages_total is not None and (not isinstance(pages_total, int) or isinstance(pages_total, bool)
                                    or not 0 <= pages_total <= limits.max_pages):
        problems.append(f"extraction.pages_total must be an integer between 0 and {limits.max_pages}")
        pages_total = None
    pages_failed = _int_list(extraction, "pages_failed", problems, "extraction", limits.max_pages)
    pages_ocr = _int_list(extraction, "pages_needing_ocr", problems, "extraction", limits.max_pages)

    if problems:
        raise ContractViolation(problems)

    # --- sufficiency (well-formed but not analysable) -------------------------
    if raw_status == "failed":
        raise InsufficientContent("Upstream extraction failed; the document cannot be analysed.")
    word_count = len(text.split())
    if word_count < limits.min_words:
        raise InsufficientContent(f"Not enough text to analyse (minimum {limits.min_words} words).")

    limitations: list[str] = []
    status = _UPSTREAM_STATUS[raw_status]
    if status == ExtractionStatus.PARTIAL:
        limitations.append("Upstream extraction was partial: "
                           f"{len(pages_failed)} failed page(s), {len(pages_ocr)} page(s) needed OCR.")
    if isinstance(declared_words, int) and declared_words != word_count:
        limitations.append(f"Declared word_count ({declared_words}) differs from the received text ({word_count}).")
    if language is None:
        limitations.append("Document language was not detected upstream.")

    return IncomingDocument(
        text=text,
        content_sha256=text_sha256(text),
        word_count=word_count,
        char_count=len(text),
        paragraphs=tuple(paragraphs),
        language=language,
        title=title,
        extraction_status=status,
        page_count=pages_total,
        pages_failed=pages_failed,
        pages_needing_ocr=pages_ocr,
        producer=producer,
        producer_version=producer_version,
        analysis_ref=analysis_ref,
        file_sha256=file_sha256,
        filename=filename,
        mime_type=mime_type,
        limitations=tuple(limitations),
    )

"""DOI detection and normalisation (pure, deterministic).

DOIs are case-insensitive (ISO 26324 / DOI Handbook), so comparisons use the
lower-cased form. Detection is deliberately conservative: a finding built on a
mis-detected DOI would be a false accusation of a broken reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

# "10." + registrant (4-9 digits, optional sub-parts) + "/" + suffix (no whitespace or quotes/brackets).
_DOI = re.compile(r"10\.\d{4,9}(?:\.\d+)*/[^\s\"'<>{}|\\^`\[\]]+", re.IGNORECASE)
_PREFIXES = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*|urn:doi:)", re.IGNORECASE)
_TRAILING = ".,;:!?"
_MAX_LEN = 300


@dataclass(frozen=True)
class DoiMention:
    doi: str      # normalised (lower-case, no prefix, no trailing punctuation)
    raw: str      # as written in the text
    start: int    # span of ``raw`` in the searched text
    end: int


def _trim(candidate: str) -> str:
    """Remove trailing sentence punctuation and unbalanced closing brackets."""
    while candidate:
        last = candidate[-1]
        if last in _TRAILING:
            candidate = candidate[:-1]
        elif last == ")" and candidate.count("(") < candidate.count(")"):
            candidate = candidate[:-1]
        else:
            break
    return candidate


def normalize_doi(value: str) -> str | None:
    """Return the normalised DOI contained in ``value`` (a bare DOI, ``doi:``
    form or doi.org URL), or None if it is not a syntactically valid DOI."""
    if not isinstance(value, str):
        return None
    v = unquote(value.strip())
    v = _PREFIXES.sub("", v)
    m = _DOI.fullmatch(_trim(v))
    if not m or len(m.group()) > _MAX_LEN:
        return None
    return m.group().lower()


def find_dois(text: str) -> list[DoiMention]:
    """All DOI mentions in ``text``, in order, with their spans."""
    mentions: list[DoiMention] = []
    for m in _DOI.finditer(text):
        raw = _trim(m.group())
        if not raw or len(raw) > _MAX_LEN or "/" not in raw:
            continue
        mentions.append(DoiMention(doi=raw.lower(), raw=raw, start=m.start(), end=m.start() + len(raw)))
    return mentions

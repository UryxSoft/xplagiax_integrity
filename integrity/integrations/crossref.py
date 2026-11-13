"""Crossref REST API adapter: DOI lookup and bibliographic search.

Endpoints used (Crossref public REST API): ``GET /works/{doi}`` and
``GET /works?query.bibliographic=...``. They were taken from Crossref's public
documentation but could not be re-checked from this environment (no network
access to crossref.org); the live test in tests/ is opt-in.

The adapter is blocked by policy until an operator records the reviewed terms
(``flask integrity source-review``). Nothing is cached: responses are reduced
to the fields below and only their hash is persisted.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from integrity.domain.doi import normalize_doi
from integrity.domain.enums import ApiOutcome
from integrity.integrations.base import CallResult, SourceClient

_MAX_SEARCH_ROWS = 5
_MAX_QUERY_CHARS = 300
_SELECT = "DOI,title,author,issued,container-title,type,publisher"


@dataclass(frozen=True)
class BibRecord:
    """Minimal, normalised bibliographic metadata (facts only; no abstracts)."""

    doi: str
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    container: str | None
    type: str | None
    publisher: str | None


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip() or None
    return None


def _year(issued: Any) -> int | None:
    try:
        y = issued["date-parts"][0][0]
        return int(y) if y is not None else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _authors(raw: Any) -> tuple[str, ...]:
    names = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict):
            continue
        name = " ".join(p for p in (a.get("given"), a.get("family")) if isinstance(p, str) and p) or a.get("name")
        if isinstance(name, str) and name:
            names.append(name[:200])
    return tuple(names[:50])


def to_record(message: Any) -> BibRecord | None:
    if not isinstance(message, dict):
        return None
    doi = normalize_doi(message.get("DOI") or "")
    if doi is None:
        return None
    return BibRecord(doi=doi, title=_first(message.get("title")), authors=_authors(message.get("author")),
                     year=_year(message.get("issued")), container=_first(message.get("container-title")),
                     type=message.get("type") if isinstance(message.get("type"), str) else None,
                     publisher=message.get("publisher") if isinstance(message.get("publisher"), str) else None)


@dataclass
class DoiLookup:
    result: CallResult
    record: BibRecord | None


@dataclass
class SearchResult:
    result: CallResult
    records: list[BibRecord]


class CrossrefClient(SourceClient):
    code = "crossref"
    allowed_host = "api.crossref.org"
    adapter_version = "1"
    required_permissions = ("allows_commercial_use",)

    def lookup_doi(self, session: Session, doi: str, *, organization_id: str | None = None,
                   evaluation_id: str | None = None) -> DoiLookup:
        normalized = normalize_doi(doi)
        if normalized is None:
            raise ValueError("not a syntactically valid DOI")
        res = self.call(session, operation="doi_lookup",
                        path="/works/" + urllib.parse.quote(normalized, safe=""), query=None,
                        fingerprint_params={"doi": normalized}, organization_id=organization_id,
                        evaluation_id=evaluation_id, count_results=lambda d: 1)
        record = to_record(res.data.get("message")) if res.outcome == ApiOutcome.OK and isinstance(res.data, dict) else None
        if res.outcome == ApiOutcome.OK and record is None:
            res.reason = "malformed provider response"
        return DoiLookup(res, record)

    def search(self, session: Session, bibliographic: str, *, rows: int = 3, organization_id: str | None = None,
               evaluation_id: str | None = None) -> SearchResult:
        """Search by a reference string. The caller must pass only reference text
        (title/authors/year), never document content (DATA_SOURCES §4)."""
        q = " ".join(bibliographic.split())[:_MAX_QUERY_CHARS]
        if not q:
            raise ValueError("empty query")
        rows = max(1, min(rows, _MAX_SEARCH_ROWS))
        res = self.call(session, operation="bibliographic_search", path="/works",
                        query={"query.bibliographic": q, "rows": rows, "select": _SELECT},
                        fingerprint_params={"q": q, "rows": rows}, organization_id=organization_id,
                        evaluation_id=evaluation_id,
                        count_results=lambda d: len(((d or {}).get("message") or {}).get("items") or []))
        items = []
        if res.outcome == ApiOutcome.OK and isinstance(res.data, dict):
            for it in ((res.data.get("message") or {}).get("items") or [])[:rows]:
                rec = to_record(it)
                if rec:
                    items.append(rec)
        return SearchResult(res, items)

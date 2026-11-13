"""Citation <-> bibliography consistency (engine ``citation_consistency`` v1).

Finds, in the document's own text:
* in-text citations that have no matching entry in the reference list;
* reference-list entries that are never cited.

Method (deterministic, heuristic, documented in every finding):
1. Locate the reference section by its heading (multilingual list below). If it
   is not found, the engine reports that and produces **no** findings: the
   absence of a detected section is not evidence of missing references.
2. Detect the citation style: numeric (``[1]``, ``[2-4]``) or author-year
   (``(Smith, 2020)``, ``Smith et al. (2020)``).
3. Numeric: compare cited numbers with entry numbers. Author-year: compare
   (first-author surname, year) keys, accent- and case-insensitive.

It does NOT verify that references exist (that needs an authorised registry
lookup) or that a source supports a claim. Findings are
``structural_observation``: a parsing heuristic, to be confirmed by a person.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from integrity.domain.enums import EvidenceKind, FindingNature, Severity
from integrity.engines.base import EvidenceDraft, FindingDraft, StageInput, StageOutput

NAME, VERSION = "citation_consistency", "1"
METHOD_NUMERIC = "citation-consistency-v1/numeric"
METHOD_AUTHOR_YEAR = "citation-consistency-v1/author-year"
MAX_FINDINGS = 300
MAX_RANGE = 50
EXCERPT_CHARS = 240

_HEADINGS = {
    "references", "reference list", "bibliography", "works cited", "literature cited", "cited literature",
    "referencias", "referencias bibliograficas", "bibliografia", "bibliografia citada",
    "references bibliographiques", "bibliographie", "literatur", "literaturverzeichnis",
    "riferimenti bibliografici", "referencias bibliográficas", "bibliografía", "références",
}
_END_HEADINGS = {"appendix", "appendices", "annex", "annexes", "anexo", "anexos", "apendice", "apéndice",
                 "annexe", "anhang", "supplementary material", "acknowledgments", "acknowledgements",
                 "agradecimientos"}

_NUMERIC_CITE = re.compile(r"\[(\d{1,4}(?:\s*[-–,]\s*\d{1,4})*)\]")
_NAME = r"[A-ZÁÉÍÓÚÑÄÖÜÇ][\w'’\-]+"
_PAREN = re.compile(r"\(([^()]{4,300})\)")
_IN_PAREN_ITEM = re.compile(rf"({_NAME})(?:\s+et al\.?|\s+(?:and|&|y|e|et|und)\s+{_NAME})?,?\s+((?:19|20)\d{{2}})[a-z]?")
_NARRATIVE = re.compile(rf"({_NAME})(?:\s+et al\.?|\s+(?:and|&|y|e|et|und)\s+{_NAME})?\s+\(((?:19|20)\d{{2}})[a-z]?\)")
_ENTRY_NUMBER = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+")
_YEAR = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")
_SURNAME = re.compile(rf"^\s*({_NAME})")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()


def _heading_key(text: str) -> str:
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[ivxlc]+\.)\s+", "", text.strip(), flags=re.IGNORECASE)
    return _fold(t.strip().rstrip(":").strip())


_END_FOLDED = {_fold(h) for h in _END_HEADINGS}
_LABEL = re.compile(r"^(?:[a-z]|\d{1,3}|[ivxlc]{1,6})$")


def _is_end_heading(text: str) -> bool:
    """'Appendix', 'Appendix A', 'Anexo 1', 'Annexe II', 'Supplementary material'..."""
    words = _heading_key(text).rstrip(".:").split()
    for n in (2, 1):  # heading may be one or two words, optionally followed by one label
        head, rest = " ".join(words[:n]), words[n:]
        if head in _END_FOLDED and (not rest or (len(rest) == 1 and _LABEL.match(rest[0]))):
            return True
    return False


@dataclass(frozen=True)
class _Para:
    page: int | None
    number: int | None
    text: str
    offset: int  # start offset in the full text when no paragraph structure exists


def _paragraphs(inp: StageInput) -> list[_Para]:
    if inp.paragraphs:
        return [_Para(p, n, t, 0) for p, n, t in inp.paragraphs]
    paras, pos = [], 0
    for line in inp.text.split("\n"):
        paras.append(_Para(None, None, line, pos))
        pos += len(line) + 1
    return paras


def _loc(p: _Para, start: int, end: int) -> dict:
    if p.page is not None:
        return {"page": p.page, "paragraph": p.number, "char_start": start, "char_end": end}
    return {"char_start": p.offset + start, "char_end": p.offset + end}


def _excerpt(text: str, start: int, end: int) -> tuple[str, int]:
    a = max(0, start - (EXCERPT_CHARS - (end - start)) // 2)
    return text[a:a + EXCERPT_CHARS], a


def _expand(spec: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", spec):
        if re.search(r"[-–]", part):
            a, b = (int(x) for x in re.split(r"\s*[-–]\s*", part)[:2])
            if 0 < b - a <= MAX_RANGE:
                out.extend(range(a, b + 1))
            else:
                out.extend([a, b])
        elif part:
            out.append(int(part))
    return out


@dataclass
class _Cite:
    key: object
    label: str
    para: _Para
    start: int
    end: int


def _numeric_cites(body: list[_Para]) -> list[_Cite]:
    cites = []
    for p in body:
        for m in _NUMERIC_CITE.finditer(p.text):
            for n in _expand(m.group(1)):
                cites.append(_Cite(n, f"[{n}]", p, m.start(), m.end()))
    return cites


def _author_year_cites(body: list[_Para]) -> list[_Cite]:
    cites = []
    for p in body:
        seen_spans = []
        for m in _NARRATIVE.finditer(p.text):
            cites.append(_Cite((_fold(m.group(1)), m.group(2)), f"{m.group(1)} ({m.group(2)})", p, m.start(), m.end()))
            seen_spans.append((m.start(), m.end()))
        for m in _PAREN.finditer(p.text):
            if any(a <= m.start() < b for a, b in seen_spans):
                continue
            for item in m.group(1).split(";"):
                im = _IN_PAREN_ITEM.search(item)
                if im:
                    cites.append(_Cite((_fold(im.group(1)), im.group(2)), f"{im.group(1)}, {im.group(2)}",
                                       p, m.start(), m.end()))
    return cites


@dataclass
class _Entry:
    key: object
    para: _Para


def _entries(refs: list[_Para], numeric: bool) -> list[_Entry]:
    out = []
    for p in refs:
        t = p.text.strip()
        if len(t) < 8:
            continue
        if numeric:
            m = _ENTRY_NUMBER.match(t)
            if m:
                out.append(_Entry(int(m.group(1) or m.group(2)), p))
        else:
            sm, ym = _SURNAME.match(t), _YEAR.search(t)
            if sm and ym:
                out.append(_Entry((_fold(sm.group(1)), ym.group(1)), p))
    return out


def _finding(category: str, title: str, description: str, method: str, p: _Para, start: int, end: int,
             recommendation: str, limitations: list[str]) -> FindingDraft:
    excerpt, a = _excerpt(p.text, start, end)
    return FindingDraft(
        category=category, nature=FindingNature.STRUCTURAL_OBSERVATION, severity=Severity.LOW, title=title,
        description=description, method=method, location=_loc(p, start, end), limitations=tuple(limitations),
        recommendation=recommendation,
        evidence=(EvidenceDraft(kind=EvidenceKind.DOCUMENT_EXCERPT, locator=_loc(p, a, a + len(excerpt)),
                                excerpt=excerpt),))


def run(inp: StageInput) -> StageOutput:
    paras = _paragraphs(inp)
    idx = next((i for i, p in enumerate(paras) if _heading_key(p.text) in {_fold(h) for h in _HEADINGS}), None)
    if idx is None:
        return StageOutput(payload={"references_section_found": False, "style": None, "citations": 0,
                                    "references": 0},
                           limitations=("No reference section heading was found; consistency was not assessed.",))
    end = next((j for j in range(idx + 1, len(paras)) if _is_end_heading(paras[j].text)), len(paras))
    body, refs = paras[:idx], paras[idx + 1:end]

    numeric_entries = _entries(refs, numeric=True)
    numeric = len(numeric_entries) >= max(1, len([r for r in refs if len(r.text.strip()) >= 8]) // 2)
    if numeric:
        entries, cites, method = numeric_entries, _numeric_cites(body), METHOD_NUMERIC
    else:
        entries, cites, method = _entries(refs, numeric=False), _author_year_cites(body), METHOD_AUTHOR_YEAR

    limitations = ["Heuristic parsing of the document's own text; confirm each observation manually.",
                   "References were not checked against any registry."]
    if not numeric:
        limitations.append("Author-year matching uses the first author's surname and the year only.")
    if not entries:
        return StageOutput(payload={"references_section_found": True, "style": "numeric" if numeric else "author_year",
                                    "citations": len(cites), "references": 0},
                           limitations=tuple(limitations + ["No reference entries could be parsed."]))

    ref_keys = {e.key for e in entries}
    cited_keys = {c.key for c in cites}
    findings: list[FindingDraft] = []
    reported = set()
    for c in cites:
        if c.key not in ref_keys and c.key not in reported:
            reported.add(c.key)
            findings.append(_finding(
                "citation_without_reference", f"Citation {c.label} has no matching reference",
                f"The in-text citation {c.label} does not match any entry of the reference list.",
                method, c.para, c.start, c.end,
                "Add the missing reference or correct the citation.", limitations))
    for e in entries:
        if e.key not in cited_keys:
            label = f"[{e.key}]" if numeric else f"{e.para.text.strip()[:60]}…"
            findings.append(_finding(
                "reference_not_cited", f"Reference {label} is never cited",
                "This reference-list entry is not cited anywhere in the text before the reference section.",
                method, e.para, 0, min(len(e.para.text), EXCERPT_CHARS),
                "Cite the reference where it is used, or remove it.", limitations))
    truncated = len(findings) > MAX_FINDINGS
    if truncated:
        limitations.append(f"Only the first {MAX_FINDINGS} of {len(findings)} observations are reported.")
    return StageOutput(
        payload={"references_section_found": True, "style": "numeric" if numeric else "author_year",
                 "citations": len(cites), "distinct_citations": len(cited_keys), "references": len(entries),
                 "citations_without_reference": sum(f.category == "citation_without_reference" for f in findings),
                 "references_not_cited": sum(f.category == "reference_not_cited" for f in findings)},
        limitations=tuple(limitations),
        findings=tuple(findings[:MAX_FINDINGS]),
    )

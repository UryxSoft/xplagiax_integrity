"""Lists the DOIs written in the document, with their location.

Detection only: it does not say whether a DOI exists or matches its citation.
That needs an authorised lookup (Crossref) and is a separate stage."""

from __future__ import annotations

from integrity.domain.doi import find_dois
from integrity.engines.base import StageInput, StageOutput

NAME, VERSION = "doi_detection", "1"
_MAX_REPORTED = 2000




def run(inp: StageInput) -> StageOutput:
    mentions = []
    if inp.paragraphs:
        for page, number, ptext in inp.paragraphs:
            for m in find_dois(ptext):
                mentions.append({"doi": m.doi, "raw": m.raw,
                                 "location": {"page": page, "paragraph": number, "char_start": m.start, "char_end": m.end}})
    else:
        for m in find_dois(inp.text):
            mentions.append({"doi": m.doi, "raw": m.raw, "location": {"char_start": m.start, "char_end": m.end}})
    unique = sorted({m["doi"] for m in mentions})
    limitations = ["Detection only: DOIs were not verified against any registry."]
    if len(mentions) > _MAX_REPORTED:
        limitations.append(f"Only the first {_MAX_REPORTED} of {len(mentions)} mentions are listed.")
    return StageOutput(
        payload={"mentions": mentions[:_MAX_REPORTED], "mention_count": len(mentions),
                 "unique_dois": unique[:_MAX_REPORTED], "unique_count": len(unique)},
        limitations=tuple(limitations),
    )

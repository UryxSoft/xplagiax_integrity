"""Comparison of a document version with its previous version (engine
``version_diff`` v1, Dissertation Certification).

Paragraph-level alignment (difflib) on normalised text, then, for paragraphs
that were rewritten, the share of 5-word shingles kept. Reports what changed
and where; it does not judge whether the changes are good, and it does not
detect plagiarism (no external source is involved).

Inputs without paragraph structure are compared line by line.
"""

from __future__ import annotations

import difflib

from integrity.domain.normalization import normalize
from integrity.engines.base import StageInput, StageOutput
from integrity.engines.textsim import jaccard, shingle_hashes, tokens

NAME, VERSION = "version_diff", "1"
NEEDS_PREVIOUS = True
MAX_CHANGES = 500
# A replaced paragraph keeping at least this share of shingles is "modified";
# below it, it is reported as removed + added. Provisional, not calibrated.
MODIFIED_THRESHOLD = 0.2


def _units(text: str, paragraphs) -> list[tuple[dict, str]]:
    if paragraphs:
        return [({"page": p, "paragraph": n}, t) for p, n, t in paragraphs if t.strip()]
    out, line_no = [], 0
    for line in text.split("\n"):
        line_no += 1
        if line.strip():
            out.append(({"line": line_no}, line))
    return out


def _sim(a: str, b: str) -> float:
    return round(jaccard(set(shingle_hashes(tokens(a))), set(shingle_hashes(tokens(b)))), 4)


MAX_BLOCK_PAIRS = 400  # above this, a replaced block is paired in order (bounded cost)


def _best_pairs(prev_units, cur_units, i1, i2, j1, j2) -> list[tuple[int, int, float]]:
    """Greedy highest-similarity pairing of a replaced block, keeping document
    order (no crossing pairs). Pairs below MODIFIED_THRESHOLD are not made."""
    if (i2 - i1) * (j2 - j1) > MAX_BLOCK_PAIRS:
        cands = [(i1 + k, j1 + k) for k in range(min(i2 - i1, j2 - j1))]
    else:
        cands = [(i, j) for i in range(i1, i2) for j in range(j1, j2)]
    scored = sorted(((_sim(prev_units[i][1], cur_units[j][1]), i, j) for i, j in cands), key=lambda x: (-x[0], x[1], x[2]))
    chosen: list[tuple[int, int, float]] = []
    for sim, i, j in scored:
        if sim < MODIFIED_THRESHOLD:
            break
        if any(i == a or j == b or (a < i) != (b < j) for a, b, _ in chosen):
            continue
        chosen.append((i, j, sim))
    return sorted(chosen)


def run(inp: StageInput) -> StageOutput:
    prev = inp.previous
    if prev is None:
        return StageOutput(payload={"previous_version": None},
                           limitations=("First version of the document: there is nothing to compare.",))
    if prev.text is None:
        return StageOutput(payload={"previous_version": prev.version_number, "compared": False},
                           limitations=("The previous version's content was purged; versions were not compared.",))

    cur_units, prev_units = _units(inp.text, inp.paragraphs), _units(prev.text, prev.paragraphs)
    cur_keys = [normalize(t, casefold=True).text for _, t in cur_units]
    prev_keys = [normalize(t, casefold=True).text for _, t in prev_units]
    matcher = difflib.SequenceMatcher(a=prev_keys, b=cur_keys, autojunk=False)

    changes: list[dict] = []
    counts = {"unchanged": 0, "modified": 0, "added": 0, "removed": 0}

    def add(kind: str, prev_i: int | None, cur_i: int | None, similarity: float | None = None):
        counts[kind] += 1
        if len(changes) < MAX_CHANGES:
            entry = {"type": kind}
            if prev_i is not None:
                entry["previous_location"] = prev_units[prev_i][0]
            if cur_i is not None:
                entry["location"] = cur_units[cur_i][0]
            if similarity is not None:
                entry["similarity"] = similarity
            changes.append(entry)

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            counts["unchanged"] += i2 - i1
        elif op == "delete":
            for i in range(i1, i2):
                add("removed", i, None)
        elif op == "insert":
            for j in range(j1, j2):
                add("added", None, j)
        else:  # replace: pair paragraphs by best similarity, without crossings
            pairs = _best_pairs(prev_units, cur_units, i1, i2, j1, j2)
            paired_prev = {i for i, _, _ in pairs}
            paired_cur = {j for _, j, _ in pairs}
            for i, j, sim in pairs:
                add("modified", i, j, sim)
            for i in range(i1, i2):
                if i not in paired_prev:
                    add("removed", i, None)
            for j in range(j1, j2):
                if j not in paired_cur:
                    add("added", None, j)

    cur_sh, prev_sh = set(shingle_hashes(tokens(inp.text))), set(shingle_hashes(tokens(prev.text)))
    limitations = ["Lexical comparison of wording only; it does not assess meaning or quality of the changes.",
                   f"'modified' uses a provisional threshold ({MODIFIED_THRESHOLD}) of shared 5-word sequences."]
    if not inp.paragraphs or not prev.paragraphs:
        limitations.append("At least one version had no paragraph structure; lines were compared instead.")
    if sum(counts[k] for k in ("modified", "added", "removed")) > MAX_CHANGES:
        limitations.append(f"Only the first {MAX_CHANGES} changes are listed.")
    return StageOutput(
        payload={
            "previous_version": prev.version_number,
            "previous_content_sha256": prev.content_sha256,
            "compared": True,
            "identical": inp.expected_content_sha256 == prev.content_sha256,
            "document_similarity": round(jaccard(cur_sh, prev_sh), 4),
            "units": {"previous": len(prev_units), "current": len(cur_units)},
            "counts": counts,
            "words": {"previous": len(prev.text.split()), "current": len(inp.text.split())},
            "changes": changes,
        },
        limitations=tuple(limitations),
    )

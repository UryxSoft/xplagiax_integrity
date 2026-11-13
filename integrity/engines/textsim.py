"""Lexical similarity primitives (deterministic, dependency-free).

* ``tokens``: words of the normalised, case-folded text (Unicode letters/digits).
* ``shingles``: hashes of every run of ``k`` consecutive tokens.
* ``jaccard`` / ``containment``: set overlap measures on shingles.
* ``winnow``: Schleimer, Wilkerson & Aiken (SIGMOD 2003) fingerprint selection,
  which guarantees that any shared run of at least ``w + k - 1`` tokens is
  detected while keeping only a fraction of the hashes. Used later to compare
  against authorised external sources without storing their full text.

These measures say how much *wording* is shared. They say nothing about
meaning, authorship or plagiarism; findings built on them must be
``textual_match`` and cite the matched passages.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from integrity.domain.normalization import normalize

_WORD = re.compile(r"\w+", re.UNICODE)
DEFAULT_K = 5


def tokens(text: str) -> list[str]:
    return _WORD.findall(normalize(text, casefold=True).text)


def _h(chunk: str) -> int:
    # Stable across processes and Python versions (unlike hash()).
    return int.from_bytes(hashlib.blake2b(chunk.encode(), digest_size=8).digest(), "big")


def shingle_hashes(toks: list[str], k: int = DEFAULT_K) -> list[int]:
    if len(toks) < k:
        return [_h(" ".join(toks))] if toks else []
    return [_h(" ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)]


def jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def containment(a: set[int], b: set[int]) -> float:
    """Share of ``a`` found in ``b``."""
    return len(a & b) / len(a) if a else 0.0


@dataclass(frozen=True)
class Fingerprint:
    hash: int
    position: int  # index of the first token of the shingle


def winnow(hashes: list[int], w: int = 4) -> list[Fingerprint]:
    """Select the minimum hash of every window of ``w`` consecutive shingles
    (rightmost on ties), recording each selection once."""
    if not hashes:
        return []
    if len(hashes) <= w:
        i = min(range(len(hashes)), key=lambda j: (hashes[j], -j))
        return [Fingerprint(hashes[i], i)]
    out: list[Fingerprint] = []
    last = -1
    for start in range(len(hashes) - w + 1):
        window = range(start, start + w)
        i = min(window, key=lambda j: (hashes[j], -j))
        if i != last:
            out.append(Fingerprint(hashes[i], i))
            last = i
    return out

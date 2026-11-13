"""Deterministic text normalisation with an offset map back to the original.

Every engine compares *normalised* text, but every finding must point at the
*original* text the user submitted. ``normalize`` returns both the normalised
string and, for each normalised character, the index of the original
character it came from, so any span found on the normalised text maps back
exactly (``to_original_span``).

What it does (in order, all language-neutral):
1. Unicode NFKC per character (ligatures "ﬁ" -> "fi", full-width forms, etc.).
2. Removes soft hyphens and zero-width characters.
3. Joins words hyphenated across a line break ("integ-\\nrity" -> "integrity").
4. Unifies typographic quotes and dashes.
5. Collapses every whitespace run to a single space; trims the ends.
6. Optional ``casefold`` (off by default: some engines need case).

What it deliberately does NOT do: stemming, stop-word removal, accent
stripping or any language-specific rule. Those belong to engines that know the
language, and they would break the offset guarantee.

Pure Python, O(n), no dependencies. Plain ASCII words (the vast majority)
are copied as whole slices; only words with non-ASCII or special characters
are processed character by character. Offsets are stored as a 4-byte
``array`` (measured: docs/PERFORMANCE.md §1.3).
"""

from __future__ import annotations

import re
import unicodedata
from array import array
from dataclasses import dataclass

VERSION = "1"

_DROP = {"­", "​", "‌", "‍", "⁠", "﻿"}
_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
}
_HYPHENS = {"-", "‐", "‑"}


@dataclass(frozen=True)
class NormalizedText:
    text: str
    # offsets[i] = index in the original string of the character that produced text[i]
    offsets: array
    original_length: int
    version: str = VERSION

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open span [start, end) of the normalised text to the
        smallest original span that contains all its source characters."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError("span out of range")
        return self.offsets[start], self.offsets[end - 1] + 1


# Python's \s matches exactly str.isspace(), which includes every Unicode Zs space.
_TOKEN = re.compile(r"\S+")
_SPECIAL = frozenset(_DROP) | frozenset(_MAP) | _HYPHENS
_LINEBREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")


def _last_kept(token: str, upto: int) -> str | None:
    """Last character before index ``upto`` that is not a dropped character."""
    for k in range(upto - 1, -1, -1):
        if token[k] not in _DROP:
            return token[k]
    return None


def normalize(original: str, *, casefold: bool = False) -> NormalizedText:
    """Rule for hyphenation: a hyphen is removed (and the words joined) only if
    it is the last character of a word, directly preceded by a letter of that
    same word, followed by whitespace that contains a line break, and the next
    word starts with a lowercase letter. A separator space maps to the original
    index of the first character emitted after it."""
    out: list[str] = []
    offs = array("I")
    # One-token lookahead instead of materialising every Match object
    # (a list of 300k matches alone costs ~30 MB).
    tokens = _TOKEN.finditer(original)
    nxt = next(tokens, None)
    pending = False      # a separator is owed before the next emitted character
    join_next = False    # previous token ended with a line-break hyphenation

    def emit(chars: str, src: int) -> None:
        nonlocal pending
        if pending and out:
            out.append(" ")
            offs.append(src)
        pending = False
        out.append(chars)
        offs.extend([src] * len(chars))

    while nxt is not None:
        m, nxt = nxt, next(tokens, None)
        start, end = m.span()
        token = m.group()
        if not join_next:
            pending = True
        join_next = False
        if (token[-1] in _HYPHENS and nxt is not None
                and (prev := _last_kept(token, len(token) - 1)) is not None and prev.isalpha()):
            if original[nxt.start()].islower() and any(c in _LINEBREAKS for c in original[end:nxt.start()]):
                token = token[:-1]
                end -= 1
                join_next = True

        if token.isascii() and not (_SPECIAL & set(token)):
            if pending and out:
                out.append(" ")
                offs.append(start)
            pending = False
            out.append(token.casefold() if casefold else token)
            offs.extend(range(start, end))
            continue

        for k, ch in enumerate(token):
            if ch in _DROP:
                continue
            mapped = _MAP.get(ch)
            if mapped is None:
                mapped = unicodedata.normalize("NFKC", ch)
                if mapped.strip() == "":   # NFKC produced whitespace inside a word
                    pending = True
                    continue
            emit(mapped.casefold() if casefold else mapped, start + k)

    return NormalizedText(text="".join(out), offsets=offs, original_length=len(original))

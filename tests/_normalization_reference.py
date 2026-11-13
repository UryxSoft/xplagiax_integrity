"""Reference (slow, per-character) implementation used only to check the optimised one."""


from __future__ import annotations

import unicodedata
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
    offsets: tuple[int, ...]
    original_length: int
    version: str = VERSION

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open span [start, end) of the normalised text to the
        smallest original span that contains all its source characters."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError("span out of range")
        return self.offsets[start], self.offsets[end - 1] + 1


def _is_space(ch: str) -> bool:
    return ch.isspace() or unicodedata.category(ch) == "Zs"


def normalize_reference(original: str, *, casefold: bool = False) -> NormalizedText:
    out: list[str] = []
    offs: list[int] = []
    n = len(original)
    i = 0
    pending_space = False

    def emit(chars: str, src: int) -> None:
        nonlocal pending_space
        if pending_space and out:
            out.append(" ")
            offs.append(src)
        pending_space = False
        for c in chars:
            out.append(c)
            offs.append(src)

    while i < n:
        ch = original[i]
        if ch in _DROP:
            i += 1
            continue
        # Line-break hyphenation: letter + hyphen + optional spaces + newline + spaces + lowercase letter.
        # Same rule as the optimised implementation: hyphen directly after a letter of the
        # same word (no separator pending), then whitespace with a line break, then lowercase.
        if ch in _HYPHENS and out and not pending_space and out[-1].isalpha():
            j = i + 1
            saw_newline = False
            while j < n and _is_space(original[j]):
                saw_newline = saw_newline or original[j] in "\n\r  "
                j += 1
            if saw_newline and j < n and original[j].islower():
                i = j
                continue
        if _is_space(ch):
            pending_space = True
            i += 1
            continue
        mapped = _MAP.get(ch)
        if mapped is None:
            mapped = unicodedata.normalize("NFKC", ch)
            # NFKC can itself produce spaces (e.g. U+00A0 handled above, but "⁄" variants etc.)
            if mapped.strip() == "":
                pending_space = True
                i += 1
                continue
        if casefold:
            mapped = mapped.casefold()
        emit(mapped, i)
        i += 1

    return NormalizedText(text="".join(out), offsets=tuple(offs), original_length=n)

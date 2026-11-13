import random

import pytest

from integrity.domain.normalization import normalize


@pytest.mark.parametrize("raw,expected", [
    ("  Hello \t\n  world  ", "Hello world"),
    ("integ-\nrity", "integrity"),
    ("integ- \r\n   rity", "integrity"),
    ("state-of-the-art", "state-of-the-art"),          # real hyphens kept
    ("COVID-\n19", "COVID- 19"),                         # not joined: next char is not lowercase
    ("ﬁnancial eﬃcient", "financial efficient"),  # ligatures
    ("“quoted” ‘single’ «guill»", "\"quoted\" 'single' \"guill\""),
    ("a – b — c", "a - b - c"),
    ("soft­hyphen zero​width", "softhyphen zerowidth"),
    ("non breaking space", "non breaking space"),
    ("ＦＵＬＬ　ｗｉｄｔｈ", "FULL width"),
    ("", ""),
    ("   ", ""),
])
def test_normalize(raw, expected):
    assert normalize(raw).text == expected


def test_casefold_is_optional():
    assert normalize("Straße ABC").text == "Straße ABC"
    assert normalize("Straße ABC", casefold=True).text == "strasse abc"


def test_accents_are_preserved():
    # Accent stripping is language-specific and would change meaning ("año" / "ano").
    assert normalize("año está acción").text == "año está acción"


def test_offsets_map_back_to_the_original_text():
    raw = "  The ﬁrst  “integ-\nrity”  check.\n"
    norm = normalize(raw)
    assert norm.text == 'The first "integrity" check.'
    start = norm.text.index("integrity")
    s, e = norm.to_original_span(start, start + len("integrity"))
    assert raw[s:e] == "integ-\nrity"
    s, e = norm.to_original_span(norm.text.index("first"), norm.text.index("first") + 5)
    assert raw[s:e] == "ﬁrst"  # one original char produced two normalised chars


def test_span_validation():
    norm = normalize("abc")
    with pytest.raises(ValueError):
        norm.to_original_span(2, 2)
    with pytest.raises(ValueError):
        norm.to_original_span(0, 4)


def test_offsets_are_monotonic_and_in_range_on_random_input():
    rng = random.Random(7)
    alphabet = "abcXYZ áé-–—“”‘’ \t\n\r ­​ﬁﬃＡ1."
    for _ in range(300):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        norm = normalize(raw)
        assert len(norm.offsets) == len(norm.text)
        assert all(0 <= o < len(raw) for o in norm.offsets)
        assert list(norm.offsets) == sorted(norm.offsets)
        assert not norm.text.startswith(" ") and not norm.text.endswith(" ") and "  " not in norm.text


def test_deterministic():
    raw = "Mismo   texto,\nmismo resultado — siempre."
    a, b = normalize(raw), normalize(raw)
    assert a.text == b.text and a.offsets == b.offsets


def test_optimised_implementation_matches_reference_exactly():
    from tests._normalization_reference import normalize_reference

    rng = random.Random(11)
    alphabet = ["abc", "XYZ", "año", "-", "–", "—", "“", "”", "‘", "’", " ", "  ", "\t", "\n", "\r\n",
                " ", "­", "​", "ﬁ", "ﬃ", "Ａ", "1", ".", "Straße", "-\n", "x-\nb"]
    for _ in range(3000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        for cf in (False, True):
            fast, ref = normalize(raw, casefold=cf), normalize_reference(raw, casefold=cf)
            assert fast.text == ref.text, (raw, fast.text, ref.text)
            assert list(fast.offsets) == list(ref.offsets), raw

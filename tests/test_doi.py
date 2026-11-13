import pytest

from integrity.domain.doi import find_dois, normalize_doi


@pytest.mark.parametrize("value,expected", [
    ("10.1038/nature12373", "10.1038/nature12373"),
    ("doi:10.1038/NATURE12373", "10.1038/nature12373"),
    ("DOI: 10.1000/xyz123", "10.1000/xyz123"),
    ("https://doi.org/10.1016/j.cell.2009.01.002", "10.1016/j.cell.2009.01.002"),
    ("http://dx.doi.org/10.1093/nar/gkab1112.", "10.1093/nar/gkab1112"),
    ("https://doi.org/10.1002/%28SICI%291097-4571", "10.1002/(sici)1097-4571"),
    ("10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0", None),  # '<' and '>' not accepted
    ("10.12/abc", None),          # registrant too short
    ("11.1038/nature12373", None),
    ("10.1038", None),
    ("", None),
    (None, None),
])
def test_normalize_doi(value, expected):
    assert normalize_doi(value) == expected


def test_find_dois_with_spans_and_punctuation():
    text = ("As shown (doi:10.1038/nature12373), and see https://doi.org/10.1016/j.cell.2009.01.002. "
            "Also 10.1093/nar/gkab1112; and 10.5555/12345678.")
    found = find_dois(text)
    assert [d.doi for d in found] == ["10.1038/nature12373", "10.1016/j.cell.2009.01.002",
                                      "10.1093/nar/gkab1112", "10.5555/12345678"]
    for d in found:
        assert text[d.start:d.end] == d.raw


def test_balanced_parentheses_are_kept():
    [d] = find_dois("see 10.1002/(SICI)1097-4571 now")
    assert d.doi == "10.1002/(sici)1097-4571"
    [d] = find_dois("(10.1000/abc(1)) end")
    assert d.raw == "10.1000/abc(1)"


def test_no_false_positives_on_numbers_and_versions():
    assert find_dois("Version 10.2 released on 10.10.2026, ratio 10.5/3, p < 10.0001") == []

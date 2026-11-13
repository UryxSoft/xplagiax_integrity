"""Engine citation_consistency v1 on realistic snippets."""

import pytest

from integrity.domain.enums import EvidenceKind, FindingNature
from integrity.engines import citations
from integrity.engines.base import EvidenceDraft, FindingDraft, StageInput


def inp(paragraphs=None, text=None):
    if paragraphs is not None:
        paras = [(1 + i // 10, i % 10 + 1, t) for i, t in enumerate(paragraphs)]
        text = "\n".join(paragraphs)
    else:
        paras = []
    return StageInput(text=text, paragraphs=paras, expected_content_sha256="", language="en",
                      extraction_status="complete", upstream_limitations=())


NUMERIC = [
    "1. Introduction",
    "Deep learning improved detection [1], and later work extended it [2-4].",
    "A recent survey [7] contradicts this; see also [2, 3].",
    "References",
    "[1] A. Krizhevsky, I. Sutskever, G. Hinton. ImageNet classification. NIPS, 2012.",
    "[2] K. He et al. Deep residual learning. CVPR, 2016.",
    "[3] A. Vaswani et al. Attention is all you need. NeurIPS, 2017.",
    "[4] J. Devlin et al. BERT. NAACL, 2019.",
    "[5] T. Brown et al. Language models are few-shot learners. NeurIPS, 2020.",
    "Appendix A",
    "[9] This bracket in the appendix must be ignored.",
]


def test_numeric_style():
    out = citations.run(inp(NUMERIC))
    p = out.payload
    assert (p["style"], p["references"], p["distinct_citations"]) == ("numeric", 5, 5)
    by_cat = {f.category: f for f in out.findings}
    assert [f.title for f in out.findings if f.category == "citation_without_reference"] == [
        "Citation [7] has no matching reference"]
    assert [f.title for f in out.findings if f.category == "reference_not_cited"] == ["Reference [5] is never cited"]
    f = by_cat["citation_without_reference"]
    assert f.nature == FindingNature.STRUCTURAL_OBSERVATION and f.method == citations.METHOD_NUMERIC
    loc = f.location
    assert NUMERIC[2][loc["char_start"]:loc["char_end"]] == "[7]" and loc["paragraph"] == 3
    [ev] = f.evidence
    assert ev.kind == EvidenceKind.DOCUMENT_EXCERPT and "[7]" in ev.excerpt
    assert any("confirm" in l for l in f.limitations)


AUTHOR_YEAR_ES = [
    "Introducción",
    "Según García (2019), el método es robusto. Otros autores coinciden (López y Pérez, 2020; Smith et al., 2018).",
    "Sin embargo, Müller (2021) presenta resultados distintos (Brown, 2015).",
    "Referencias bibliográficas",
    "García, M. (2019). Métodos robustos. Revista de Ciencia, 12(3), 45-60.",
    "Lopez, A., & Pérez, J. (2020). Un estudio comparativo. Editorial Universitaria.",
    "Smith, J., Doe, R., & Roe, P. (2018). Comparative analysis. Journal of Methods, 4, 1-10.",
    "Muller, K. (2021). Andere Ergebnisse. Zeitschrift, 9, 100-120.",
    "Zhang, L. (2017). Never cited work. Science, 1, 1-2.",
]


def test_author_year_style_is_accent_and_case_insensitive():
    out = citations.run(inp(AUTHOR_YEAR_ES))
    p = out.payload
    assert p["style"] == "author_year" and p["references"] == 5
    missing = [f.title for f in out.findings if f.category == "citation_without_reference"]
    uncited = [f for f in out.findings if f.category == "reference_not_cited"]
    assert missing == ["Citation Brown, 2015 has no matching reference"]
    assert len(uncited) == 1 and uncited[0].title.startswith("Reference Zhang")
    # "López" in the text matches "Lopez" in the list; "Müller" matches "Muller".
    assert any("first author's surname" in l for l in out.limitations)


def test_without_reference_section_no_findings_are_produced():
    out = citations.run(inp(["Introduction", "A claim [1] with no bibliography at all."]))
    assert out.findings == () and out.payload["references_section_found"] is False
    assert "not assessed" in out.limitations[0]


def test_heading_variants():
    for heading in ("REFERENCES", "7. References", "Bibliografía", "Works Cited:", "Literaturverzeichnis"):
        out = citations.run(inp(["Body text cites [1].", heading, "[1] Some author. Some title. 2020."]))
        assert out.payload["references_section_found"], heading
        assert out.findings == (), heading


def test_plain_text_without_paragraph_structure():
    text = "Body cites [1] and [2].\nReferences\n[1] Author A. Title one. 2020."
    out = citations.run(inp(text=text))
    [f] = out.findings
    assert f.title == "Citation [2] has no matching reference"
    assert text[f.location["char_start"]:f.location["char_end"]] == "[2]"


def test_huge_ranges_are_not_expanded():
    out = citations.run(inp(["See [1-5000].", "References", "[1] A. B. Title. 2020."]))
    assert out.payload["distinct_citations"] == 2  # 1 and 5000, not 5000 numbers


def test_findings_require_evidence_and_calibration_flag():
    with pytest.raises(ValueError):
        FindingDraft(category="c", nature=FindingNature.STRUCTURAL_OBSERVATION, severity="low", title="t",
                     description="d", method="m", location=None, evidence=())
    with pytest.raises(ValueError):
        FindingDraft(category="c", nature=FindingNature.STATISTICAL_INDICATOR, severity="low", title="t",
                     description="d", method="m", location=None, confidence=0.9,
                     evidence=(EvidenceDraft(kind=EvidenceKind.COMPUTED_METRIC),))


@pytest.mark.parametrize("heading", ["Appendix A", "Apéndice B", "Anexo 1", "Annexe II", "Acknowledgements"])
def test_reference_section_ends_at_appendix_like_headings(heading):
    out = citations.run(inp(["Body [1].", "References", "[1] A. Author. Title. 2020.", heading, "[2] Not a reference."]))
    assert out.payload["references"] == 1 and out.findings == ()


def test_a_reference_mentioning_the_word_appendix_does_not_end_the_section():
    out = citations.run(inp(["Body [1] [2].", "References", "[1] A. Author. Appendix tables. 2020.",
                             "[2] B. Author. Title. 2021."]))
    assert out.payload["references"] == 2 and out.findings == ()

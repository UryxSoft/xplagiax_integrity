import random

import pytest

from integrity.engines import textsim, version_diff
from integrity.engines.base import PreviousVersion, StageInput


def si(pars, prev_pars=None, prev_text_override="unset", same_hash=False):
    text = "\n".join(t for _, _, t in pars)
    prev = None
    if prev_pars is not None:
        ptext = "\n".join(t for _, _, t in prev_pars) if prev_text_override == "unset" else prev_text_override
        prev = PreviousVersion(1, "h" * 64 if not same_hash else "c" * 64, ptext, prev_pars)
    return StageInput(text=text, paragraphs=pars, expected_content_sha256="c" * 64, language="en",
                      extraction_status="complete", upstream_limitations=(), previous=prev)


P1 = [(1, 1, "Chapter one introduces the research problem and the main objectives of this thesis."),
      (1, 2, "The methodology follows a mixed design with interviews and a structured survey of teachers."),
      (2, 1, "Results show a moderate association between training hours and classroom practice."),
      (2, 2, "These limitations will be addressed in future work by extending the sample size.")]


# ---------------------------------------------------------------- primitives

def test_tokens_are_normalised_and_casefolded():
    assert textsim.tokens("The  ﬁrst—Ünïcode TEST, here.") == ["the", "first", "ünïcode", "test", "here"]


def test_shingle_hashes_are_stable_and_ordered():
    t = "a b c d e f".split()
    assert textsim.shingle_hashes(t, 5) == textsim.shingle_hashes(list(t), 5) and len(textsim.shingle_hashes(t, 5)) == 2
    assert textsim.shingle_hashes([], 5) == [] and len(textsim.shingle_hashes(["a", "b"], 5)) == 1


def test_jaccard_and_containment():
    assert textsim.jaccard(set(), set()) == 1.0
    assert textsim.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert textsim.containment({1, 2}, {2, 3, 4}) == 0.5 and textsim.containment(set(), {1}) == 0.0


def test_winnowing_guarantee_detects_any_long_shared_run():
    """Any shared run of >= w + k - 1 tokens must share at least one fingerprint."""
    rng = random.Random(3)
    vocab = [f"w{i}" for i in range(500)]
    k, w = 5, 4
    for _ in range(200):
        shared = [rng.choice(vocab) for _ in range(w + k - 1)]
        a = [rng.choice(vocab) for _ in range(rng.randint(0, 40))] + shared + [rng.choice(vocab) for _ in range(20)]
        b = [rng.choice(vocab) for _ in range(rng.randint(0, 40))] + shared + [rng.choice(vocab) for _ in range(20)]
        fa = {f.hash for f in textsim.winnow(textsim.shingle_hashes(a, k), w)}
        fb = {f.hash for f in textsim.winnow(textsim.shingle_hashes(b, k), w)}
        assert fa & fb


def test_winnowing_keeps_a_fraction_of_hashes():
    toks = [f"w{i}" for i in range(2000)]
    hashes = textsim.shingle_hashes(toks)
    fp = textsim.winnow(hashes, 4)
    assert len(fp) < len(hashes) * 0.6 and all(hashes[f.position] == f.hash for f in fp)


# ---------------------------------------------------------------- engine

def test_first_version_has_nothing_to_compare():
    out = version_diff.run(si(P1))
    assert out.payload == {"previous_version": None} and "First version" in out.limitations[0]


def test_purged_previous_version_is_reported_not_compared():
    out = version_diff.run(si(P1, P1, prev_text_override=None))
    assert out.payload["compared"] is False and "purged" in out.limitations[0]


def test_identical_versions():
    out = version_diff.run(si(P1, P1, same_hash=True))
    p = out.payload
    assert p["identical"] and p["document_similarity"] == 1.0
    assert p["counts"] == {"unchanged": 4, "modified": 0, "added": 0, "removed": 0} and p["changes"] == []


def test_layout_only_changes_count_as_unchanged():
    reflowed = [(1, 1, P1[0][2].upper()), (1, 2, P1[1][2].replace(" ", "   ")), P1[2], P1[3]]
    assert version_diff.run(si(reflowed, P1)).payload["counts"]["unchanged"] == 4


def test_modified_added_and_removed_paragraphs_with_locations():
    v2 = [P1[0],
          (1, 2, "The methodology follows a mixed design with interviews and a structured survey of 120 teachers."),
          (2, 1, "Results show a moderate association between training hours and classroom practice."),
          (2, 2, "A new section discusses ethical approval and informed consent of all participants."),
          (3, 1, "Completely new conclusions about the policy implications for regional education boards.")]
    out = version_diff.run(si(v2, P1))
    p = out.payload
    assert p["counts"] == {"unchanged": 2, "modified": 1, "added": 2, "removed": 1}
    mod = [c for c in p["changes"] if c["type"] == "modified"][0]
    assert mod["location"] == {"page": 1, "paragraph": 2} and mod["previous_location"] == {"page": 1, "paragraph": 2}
    assert 0.2 <= mod["similarity"] < 1
    assert {"type": "removed", "previous_location": {"page": 2, "paragraph": 2}} in p["changes"]
    assert 0 < p["document_similarity"] < 1
    assert any("provisional threshold" in l for l in out.limitations)


def test_without_paragraph_structure_lines_are_compared():
    inp = StageInput(text="line one is here\nline two changed", paragraphs=[], expected_content_sha256="c" * 64,
                     language=None, extraction_status="complete", upstream_limitations=(),
                     previous=PreviousVersion(1, "h" * 64, "line one is here\nline two original", []))
    out = version_diff.run(inp)
    assert out.payload["counts"]["unchanged"] == 1 and any("lines were compared" in l for l in out.limitations)


def test_deleted_paragraph_next_to_an_edited_one_is_not_mispaired():
    v2 = [P1[0], (1, 2, P1[2][2] + " Additionally, effects were larger in rural schools."), P1[3]]  # P1[1] deleted, P1[2] edited
    p = version_diff.run(si(v2, P1)).payload
    assert p["counts"] == {"unchanged": 2, "modified": 1, "added": 0, "removed": 1}
    mod = [c for c in p["changes"] if c["type"] == "modified"][0]
    assert mod["previous_location"] == {"page": 2, "paragraph": 1}


def test_pairs_never_cross():
    a = (1, 1, "alpha beta gamma delta epsilon zeta eta theta iota kappa")
    b = (1, 2, "lambda mu nu xi omicron pi rho sigma tau upsilon")
    swapped = [(1, 1, b[2] + " phi"), (1, 2, a[2] + " chi")]
    p = version_diff.run(si(swapped, [a, b])).payload
    mods = [c for c in p["changes"] if c["type"] == "modified"]
    assert len(mods) == 1 and p["counts"]["added"] == 1 and p["counts"]["removed"] == 1


def test_synthetic_ground_truth_is_recovered_exactly():
    """Regression on known edits: 10% of paragraphs edited, some deleted, some inserted."""
    rng = random.Random(5)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 10))) for _ in range(5000)]
    v1 = [(1 + i // 8, i % 8 + 1, " ".join(rng.choice(vocab) for _ in range(80))) for i in range(200)]
    edited, deleted = set(rng.sample(range(200), 20)), set(rng.sample(range(200), 6))
    v2 = []
    for k, (p, n, t) in enumerate(v1):
        if k in deleted:
            continue
        if k in edited:
            w = t.split()
            w[rng.randrange(len(w))] = "edited"
            t = " ".join(w)
        v2.append((p, n, t))
        if k in (50, 120):
            v2.append((p, 99, " ".join(rng.choice(vocab) for _ in range(80))))
    c = version_diff.run(si(v2, v1)).payload["counts"]
    assert c == {"unchanged": 200 - len(edited | deleted), "modified": len(edited - deleted), "added": 2,
                 "removed": len(deleted)}

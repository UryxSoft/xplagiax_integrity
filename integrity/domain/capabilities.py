"""Honest, machine-readable inventory of engine status.

Exposed at GET /api/v1/version so consumers (xplagiax_appcli2) never assume a
capability exists. Update this file in the same commit that changes an engine's
real status. "implemented" requires passing tests that exercise the behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Maturity(StrEnum):
    IMPLEMENTED = "implemented"
    BASELINE = "baseline"                      # initial working base, limited scope
    PENDING = "pending"                        # designed, not built
    REQUIRES_RESEARCH = "requires_research"    # method not yet validated
    REQUIRES_EXTERNAL_API = "requires_external_api"  # blocked on provider terms/credentials or sibling service


@dataclass(frozen=True)
class Engine:
    name: str
    maturity: Maturity
    note: str
    version: str | None = None


ENGINES: tuple[Engine, ...] = (
    Engine("document_ingestion", Maturity.BASELINE, "POST /documents (xplagiax.document/v1): validation, idempotency, versions, compressed storage, purge. Contract v1 awaits confirmation by xplagiax_appcli2.", version="1"),
    Engine("document_extraction", Maturity.REQUIRES_RESEARCH, "Primary extraction lives in xplagiax_appcli2. Local fallback and anydoc / LightOnOCR comparison pending benchmark."),
    Engine("ocr", Maturity.REQUIRES_RESEARCH, "Upstream responsibility by default; on-demand local OCR only if benchmark justifies it."),
    Engine("text_normalization", Maturity.BASELINE, "Deterministic, language-neutral normalisation with an exact offset map back to the original text (integrity/domain/normalization.py). Not yet wired into an engine.", version="1"),
    Engine("similarity", Maturity.BASELINE, "Lexical primitives (5-word shingles, Jaccard, winnowing) and version_diff v1 between versions of a document. Comparison against external sources pending authorised sources; semantic similarity not started.", version="1"),
    Engine("ai_content_analysis", Maturity.REQUIRES_EXTERNAL_API, "Delegated to sibling services (beyond_xota / finderx / scitrace); contracts not yet inspected."),
    Engine("citation_verification", Maturity.BASELINE, "citation_consistency v1: in-text citations vs reference list (numeric and author-year), heuristic, no precision metrics yet. DOI detection exists; DOI verification needs an authorised source.", version="1"),
    Engine("academic_source_discovery", Maturity.REQUIRES_EXTERNAL_API, "Crossref adapter built (DOI lookup, bibliographic search) and blocked by policy until its terms are reviewed. PubMed / Europe PMC / arXiv pending. Terms UNVERIFIED."),
    Engine("patent_search", Maturity.REQUIRES_EXTERNAL_API, "EPO OPS / LOD, USPTO ODP, IP Australia...; terms UNVERIFIED."),
    Engine("semantic_comparison", Maturity.REQUIRES_RESEARCH, "Claim-element mapping; method and metrics to be validated before exposure."),
    Engine("evidence_management", Maturity.BASELINE, "Findings require evidence and an epistemic nature; excerpts are hashed and purged with the document."),
    Engine("report_generation", Maturity.BASELINE, "JSON report from stored rows only, with a reproducible hash that survives purges. PDF pending.", version="1"),
    Engine("certification", Maturity.PENDING, "Data model exists; criteria profiles and signing scheme pending audit."),
)


def as_public_list() -> list[dict[str, str | None]]:
    return [{"name": e.name, "maturity": e.maturity.value, "version": e.version, "note": e.note} for e in ENGINES]

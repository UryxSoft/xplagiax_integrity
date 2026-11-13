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
    Engine("text_normalization", Maturity.PENDING, "Deterministic Unicode/whitespace normalisation with offset mapping to original text."),
    Engine("similarity", Maturity.REQUIRES_RESEARCH, "Lexical (n-gram/winnowing) first; semantic via shared Qdrant only where licences allow."),
    Engine("ai_content_analysis", Maturity.REQUIRES_EXTERNAL_API, "Delegated to sibling services (beyond_xota / finderx / scitrace); contracts not yet inspected."),
    Engine("citation_verification", Maturity.PENDING, "In-text citation <-> bibliography linking; DOI lookups depend on source terms."),
    Engine("academic_source_discovery", Maturity.REQUIRES_EXTERNAL_API, "Crossref / PubMed / Europe PMC / arXiv adapters; terms UNVERIFIED."),
    Engine("patent_search", Maturity.REQUIRES_EXTERNAL_API, "EPO OPS / LOD, USPTO ODP, IP Australia...; terms UNVERIFIED."),
    Engine("semantic_comparison", Maturity.REQUIRES_RESEARCH, "Claim-element mapping; method and metrics to be validated before exposure."),
    Engine("evidence_management", Maturity.BASELINE, "Persistence model (findings, evidence, api_requests) exists; no producers yet."),
    Engine("report_generation", Maturity.PENDING, "JSON report schema first; PDF later."),
    Engine("certification", Maturity.PENDING, "Data model exists; criteria profiles and signing scheme pending audit."),
)


def as_public_list() -> list[dict[str, str | None]]:
    return [{"name": e.name, "maturity": e.maturity.value, "version": e.version, "note": e.note} for e in ENGINES]

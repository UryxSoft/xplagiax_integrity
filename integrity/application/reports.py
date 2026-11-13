"""JSON report of a finished evaluation (engine ``report_json`` v1).

The report is assembled **only from stored rows**; nothing is recomputed.
Its ``content_sha256`` is computed over a canonical form in which evidence
excerpts are replaced by their SHA-256, so:
* regenerating the report later yields the same hash (reproducible);
* purging the document (which deletes excerpts) does not change the hash;
* anyone holding the report can verify each excerpt against its hash.

The first generation is recorded in ``reports``; later generations must
reproduce the stored hash, otherwise the stored data changed and the report
is refused (``report_mismatch``) instead of silently differing.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrity import __version__
from integrity.application.documents import Actor
from integrity.application.errors import DataInconsistency, NotReady
from integrity.application.evaluations import _visible_evaluation, engine_version_for
from integrity.domain.enums import EvaluationStatus, Product, ReportFormat
from integrity.domain.evaluation_state import TERMINAL
from integrity.domain.workflows import StageSpec
from integrity.infrastructure.db.models import (
    ApiRequest,
    DocumentVersion,
    EngineVersion,
    Evidence,
    ExternalSource,
    Finding,
    Report,
)
from integrity.infrastructure.db.repositories import TenantScope

SCHEMA_VERSION = "1"
REPORT_ENGINE = StageSpec("report", "report_json", "1")

NATURE_TEXT = {
    "verified_evidence": "Verified fact that a person can check directly.",
    "textual_match": "Textual overlap with an identified source. Not, by itself, proof of plagiarism.",
    "semantic_similarity": "Model-based similarity. Not proof of copying or of lack of novelty.",
    "statistical_indicator": "Probabilistic indicator. Not proof of authorship or misconduct.",
    "structural_observation": "Observation from parsing the document's structure; confirm manually.",
    "not_determinable": "The system could not reach a conclusion.",
}

DISCLAIMERS = {
    Product.RESEARCH_PAPER: "Documentary assessment support. It is not a peer review and does not predict editorial acceptance.",
    Product.DISSERTATION: "Documentary assessment under the stated criteria. It does not certify originality, scientific validity or institutional acceptance.",
    Product.PATENT_INTEGRITY: "Technical and documentary analysis only. It is not a legal opinion on patentability, novelty, infringement or freedom to operate.",
}
COMMON = ("An absence of findings means that nothing was detected by the listed methods in the listed sources; "
          "it does not mean the document is original or free of problems.")


def _iso(dt):
    return dt.isoformat() if dt else None


def _canonical(report: dict) -> bytes:
    hashable = json.loads(json.dumps(report))  # deep copy
    for f in hashable["findings"]:
        for e in f["evidence"]:
            e.pop("excerpt", None)          # excerpt_sha256 stays and identifies it
            e.pop("excerpt_purged", None)   # retention state, not content
    hashable.pop("report", None)   # id/hash/generation time are about the report, not its content
    return json.dumps(hashable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def build_report(session: Session, actor: Actor, evaluation_id: str) -> dict:
    scope = TenantScope(session, actor.organization_id)
    ev = _visible_evaluation(scope, actor, evaluation_id)
    if ev.status not in TERMINAL:
        raise NotReady("The evaluation has not finished yet.", details=[f"status: {ev.status.value}"])
    version = scope.get(DocumentVersion, ev.document_version_id)
    from integrity.application.evaluations import get_evaluation

    view = get_evaluation(session, actor, ev.id)
    engines = {e.id: e for e in session.scalars(select(EngineVersion))}

    findings = list(session.scalars(scope.select(Finding).where(Finding.evaluation_id == ev.id)
                                    .order_by(Finding.created_at, Finding.id)))
    evidence_by_finding: dict[str, list[Evidence]] = {}
    if findings:
        for e in session.scalars(scope.select(Evidence).where(Evidence.finding_id.in_([f.id for f in findings]))
                                 .order_by(Evidence.created_at, Evidence.id)):
            evidence_by_finding.setdefault(e.finding_id, []).append(e)

    calls = session.execute(
        select(ExternalSource.code, ApiRequest.operation, ApiRequest.outcome)
        .join(ExternalSource, ExternalSource.id == ApiRequest.external_source_id)
        .where(ApiRequest.organization_id == actor.organization_id, ApiRequest.evaluation_id == ev.id)).all()
    sources = Counter((c, op, o.value) for c, op, o in calls)

    limitations = list(version.limitations or [])
    for st in view.stages:
        r = view.results.get(st.id)
        if r:
            limitations += [f"[{st.stage_name}] {lim}" for lim in r.limitations]
        elif st.status.value != "succeeded":
            limitations.append(f"[{st.stage_name}] stage {st.status.value}" + (f" ({st.error_code})" if st.error_code else ""))

    report = {
        "schema_version": SCHEMA_VERSION,
        "product": ev.product.value,
        "evaluation": {"id": ev.id, "status": ev.status.value, "created_at": _iso(ev.created_at),
                       "finished_at": _iso(ev.finished_at), "config_sha256": ev.config_sha256,
                       "criteria": {"profile": ev.criteria_profile, "version": ev.criteria_version},
                       "upstream_ref": ev.upstream_ref},
        "document": {"version_id": version.id, "version_number": version.version_number,
                     "content_sha256": version.content_sha256, "file_sha256": version.file_sha256,
                     "words": version.word_count, "pages": version.page_count, "language": version.language,
                     "extraction_status": version.extraction_status.value},
        "stages": [
            {"name": st.stage_name, "status": st.status.value, "error_code": st.error_code,
             "engine": ({"name": engines[st.engine_version_id].engine_name,
                         "version": engines[st.engine_version_id].version,
                         "config_sha256": engines[st.engine_version_id].config_sha256}
                        if st.engine_version_id in engines else None),
             "result_sha256": view.results[st.id].payload_sha256 if st.id in view.results else None,
             "summary": view.results[st.id].payload if st.id in view.results else None}
            for st in view.stages],
        "sources_consulted": [{"source": c, "operation": op, "outcome": o, "calls": n}
                              for (c, op, o), n in sorted(sources.items())],
        "findings": [
            {"id": f.id, "category": f.category, "nature": f.nature.value, "nature_explained": NATURE_TEXT[f.nature.value],
             "severity": f.severity.value, "title": f.title, "description": f.description, "method": f.method,
             "confidence": float(f.confidence) if f.confidence is not None else None,
             "confidence_calibrated": f.confidence_calibrated, "location": f.location,
             "limitations": f.limitations, "recommendation": f.recommendation,
             "evidence": [{"kind": e.kind.value, "locator": e.locator, "excerpt": e.excerpt_text,
                           "excerpt_sha256": e.excerpt_sha256, "excerpt_purged": e.excerpt_sha256 is not None and e.excerpt_text is None,
                           "external_identifier": e.external_identifier, "external_url": e.external_url}
                          for e in evidence_by_finding.get(f.id, [])]}
            for f in findings],
        "finding_counts": dict(sorted(Counter(f.category for f in findings).items())),
        "limitations": limitations,
        "disclaimer": [DISCLAIMERS[ev.product], COMMON],
        "generator": {"service": "xplagiax-integrity", "version": __version__,
                      "engine": REPORT_ENGINE.engine, "engine_version": REPORT_ENGINE.engine_version},
    }
    if ev.status == EvaluationStatus.PARTIALLY_COMPLETED:
        report["limitations"].insert(0, "Some optional stages did not complete; their checks are missing from this report.")

    digest = hashlib.sha256(_canonical(report)).hexdigest()
    stored = session.scalar(scope.select(Report).where(Report.evaluation_id == ev.id, Report.format == ReportFormat.JSON)
                            .order_by(Report.generated_at))
    if stored is None:
        eng = engine_version_for(session, REPORT_ENGINE)
        stored = Report(organization_id=actor.organization_id, evaluation_id=ev.id, engine_version_id=eng.id,
                        format=ReportFormat.JSON, schema_version=SCHEMA_VERSION, content_sha256=digest)
        session.add(stored)
        session.flush()
    elif stored.content_sha256 != digest:
        raise DataInconsistency("The stored evaluation data no longer reproduces the recorded report.")
    report["report"] = {"id": stored.id, "content_sha256": digest, "first_generated_at": _iso(stored.generated_at)}
    return report

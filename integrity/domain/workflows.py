"""Stage pipelines per product (pure).

Only stages backed by a real, tested engine are listed. Products gain stages
as engines are implemented; nothing here pretends a capability exists. Each
stage pins an engine name and version, frozen into the evaluation's
``config_snapshot`` at creation so a result is always attributable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from integrity.domain.enums import Product


@dataclass(frozen=True)
class StageSpec:
    name: str
    engine: str
    engine_version: str
    # A failed optional stage makes the evaluation PARTIALLY_COMPLETED instead of FAILED.
    optional: bool = False
    max_attempts: int = 3


CONTENT_CHECK = StageSpec("content_check", "content_check", "1")
DOI_DETECTION = StageSpec("doi_detection", "doi_detection", "1", optional=True)
CITATION_CONSISTENCY = StageSpec("citation_consistency", "citation_consistency", "1", optional=True)
VERSION_DIFF = StageSpec("version_comparison", "version_diff", "1", optional=True)

WORKFLOWS: dict[Product, tuple[StageSpec, ...]] = {
    Product.RESEARCH_PAPER: (CONTENT_CHECK, DOI_DETECTION, CITATION_CONSISTENCY),
    Product.DISSERTATION: (CONTENT_CHECK, DOI_DETECTION, CITATION_CONSISTENCY, VERSION_DIFF),
    Product.PATENT_INTEGRITY: (CONTENT_CHECK,),
}

WORKFLOW_SCHEMA = "1"


def config_snapshot(product: Product, criteria_profile: str | None, criteria_version: str | None) -> dict:
    return {
        "schema": WORKFLOW_SCHEMA,
        "product": product.value,
        "criteria": {"profile": criteria_profile, "version": criteria_version},
        "stages": [{"name": s.name, "engine": s.engine, "version": s.engine_version, "optional": s.optional}
                   for s in WORKFLOWS[product]],
    }


def config_hash(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def engine_config_hash(spec: StageSpec) -> str:
    return hashlib.sha256(f"{spec.engine}:{spec.engine_version}:defaults".encode()).hexdigest()

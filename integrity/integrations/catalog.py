"""Providers known to the service. Seeding creates rows that are disabled and
UNVERIFIED; only an operator review (CLI ``source-review``) can enable one.
Base URLs are informational; adapters pin their own host."""

from __future__ import annotations

CATALOG: tuple[dict[str, str], ...] = (
    {"code": "crossref", "name": "Crossref REST API", "base_url": "https://api.crossref.org"},
    {"code": "pubmed", "name": "NCBI E-utilities (PubMed)", "base_url": "https://eutils.ncbi.nlm.nih.gov"},
    {"code": "europe_pmc", "name": "Europe PMC REST API", "base_url": "https://www.ebi.ac.uk/europepmc/webservices/rest"},
    {"code": "arxiv", "name": "arXiv API", "base_url": "https://export.arxiv.org/api"},
    {"code": "epo_ops", "name": "EPO Open Patent Services", "base_url": "https://ops.epo.org"},
    {"code": "epo_lod", "name": "EPO Linked Open EP Data", "base_url": "https://data.epo.org/linked-data"},
    {"code": "uspto_odp", "name": "USPTO Open Data Portal", "base_url": "https://api.uspto.gov"},
    {"code": "ip_australia", "name": "IP Australia Patent Search API", "base_url": "https://production.api.ipaustralia.gov.au"},
)

"""Domain vocabularies shared by all three products.

These values are persisted. Renaming a member is a data migration.
"""

from __future__ import annotations

from enum import StrEnum


class Product(StrEnum):
    PATENT_INTEGRITY = "patent_integrity"
    RESEARCH_PAPER = "research_paper"
    DISSERTATION = "dissertation"


class UserRole(StrEnum):
    MEMBER = "member"
    REVIEWER = "reviewer"
    ORG_ADMIN = "org_admin"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class ClientScope(StrEnum):
    # A platform client (e.g. xplagiax_appcli2) may act on behalf of any
    # organisation, asserting org/user per request.
    PLATFORM = "platform"
    # An organisation client is pinned to exactly one organisation.
    ORGANIZATION = "organization"


class SourceKind(StrEnum):
    # Extraction already performed upstream by xplagiax_appcli2 (primary path).
    UPSTREAM_EXTRACTION = "upstream_extraction"
    # Raw file handled by this service (pending; see ROADMAP stage 2).
    LOCAL_UPLOAD = "local_upload"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    PARTIAL = "partial"          # some pages failed / low text yield
    INSUFFICIENT = "insufficient"  # not enough text to analyse; must not proceed silently
    FAILED = "failed"


class EvaluationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"     # e.g. source not authorised; must be reported as a limitation
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingNature(StrEnum):
    """Epistemic nature of a finding. Reports must render each differently.

    This is the key guard against over-claiming: a semantic similarity score is
    never presented as a verified fact, and an AI-content indicator is never
    presented as proof of authorship.
    """

    VERIFIED_EVIDENCE = "verified_evidence"          # deterministic, checkable by a human (e.g. DOI resolves to different title)
    TEXTUAL_MATCH = "textual_match"                  # exact / near-exact overlap with an identified source
    SEMANTIC_SIMILARITY = "semantic_similarity"      # model-based closeness; not proof of copying
    STATISTICAL_INDICATOR = "statistical_indicator"  # e.g. AI-content indicators; probabilistic
    STRUCTURAL_OBSERVATION = "structural_observation"  # e.g. missing section, uncited reference
    NOT_DETERMINABLE = "not_determinable"            # the system could not reach a conclusion


class EvidenceKind(StrEnum):
    DOCUMENT_EXCERPT = "document_excerpt"
    EXTERNAL_RECORD = "external_record"
    COMPUTED_METRIC = "computed_metric"
    API_OUTCOME = "api_outcome"  # e.g. "queried Crossref, 404": supports NO_MATCH_IN_QUERIED_SOURCES


class SourceAuthorization(StrEnum):
    UNVERIFIED = "unverified"   # default: PROVIDER CONFIRMATION REQUIRED
    AUTHORIZED = "authorized"   # terms reviewed and recorded for our exact use
    RESTRICTED = "restricted"   # allowed only for a subset of uses (see per-use flags)
    DENIED = "denied"


class ApiOutcome(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"
    BLOCKED_BY_POLICY = "blocked_by_policy"  # adapter refused: source not authorised for this use


class ReportFormat(StrEnum):
    JSON = "json"
    PDF = "pdf"


class CertificateStatus(StrEnum):
    INCOMPLETE = "incomplete"
    PROCESSING = "processing"
    REQUIRES_REVIEW = "requires_review"
    REQUIRES_CORRECTIONS = "requires_corrections"
    ELIGIBLE_FOR_CERTIFICATION = "eligible_for_certification"
    CERTIFIED = "certified"
    REVOKED = "revoked"
    FAILED = "failed"


class ActorType(StrEnum):
    SERVICE_CLIENT = "service_client"
    USER = "user"
    SYSTEM = "system"

"""Provider-neutral domain vocabulary.

Enums are persisted by value. Renaming a value therefore requires a migration and
an explicit product decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

OBSERVATION_FIELDS = frozenset(
    {
        "actor",
        "actor_role",
        "industry",
        "job_to_be_done",
        "context",
        "root_cause",
        "current_workaround",
        "tools_used",
        "frequency",
        "time_impact",
        "financial_impact",
        "revenue_impact",
        "error_impact",
        "delay_impact",
        "risk_impact",
        "active_solution_search",
        "switching_intent",
        "existing_solution",
        "existing_spend",
        "paid_workaround",
        "country_code",
        "language_code",
        "pipeline_run_id",
    }
)

BOOLEAN_OBSERVATION_FIELDS = frozenset({"active_solution_search", "switching_intent"})


def validate_observation_fields(fields: dict[str, Any]) -> None:
    unknown = set(fields) - OBSERVATION_FIELDS
    if unknown:
        raise ValueError(f"unknown observation fields: {', '.join(sorted(unknown))}")
    for name, value in fields.items():
        if name in BOOLEAN_OBSERVATION_FIELDS:
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"observation field {name} must be boolean or null")
        elif value is not None and not isinstance(value, str):
            raise ValueError(f"observation field {name} must be a string or null")


class SourceLifecycle(StrEnum):
    CANDIDATE = "CANDIDATE"
    EXPLORATION = "EXPLORATION"
    CORE = "CORE"
    LOW_VALUE = "LOW_VALUE"
    EXCLUDED = "EXCLUDED"


class AudienceType(StrEnum):
    PRACTITIONER = "PRACTITIONER"
    OWNER = "OWNER"
    BUYER = "BUYER"
    CONSUMER = "CONSUMER"
    FOUNDER = "FOUNDER"
    VENDOR = "VENDOR"
    JOBSEEKER = "JOBSEEKER"
    GENERAL = "GENERAL"
    MIXED = "MIXED"


class DiscoveryState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONTENT_PARTIAL = "CONTENT_PARTIAL"
    CONTENT_COMPLETE = "CONTENT_COMPLETE"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class ContentCompleteness(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    METADATA_ONLY = "METADATA_ONLY"


class SourceAvailability(StrEnum):
    RESULTS = "RESULTS"
    NO_RESULTS = "NO_RESULTS"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class EvidenceScope(StrEnum):
    GLOBAL = "GLOBAL"
    DACH = "DACH"


class ClaimKind(StrEnum):
    FACT = "FACT"
    ANALYSIS = "ANALYSIS"
    HYPOTHESIS = "HYPOTHESIS"


class EvidenceState(StrEnum):
    SINGLE_SIGNAL = "SINGLE_SIGNAL"
    EMERGING = "EMERGING"
    RECURRING = "RECURRING"
    MULTI_SOURCE = "MULTI_SOURCE"
    CROSS_MARKET = "CROSS_MARKET"


class ProblemType(StrEnum):
    STRUCTURAL_PROBLEM = "STRUCTURAL_PROBLEM"
    WORKFLOW_GAP = "WORKFLOW_GAP"
    INTEGRATION_GAP = "INTEGRATION_GAP"
    REPEATED_LIMITATION = "REPEATED_LIMITATION"
    MIGRATION_PROBLEM = "MIGRATION_PROBLEM"
    REGULATION_PROBLEM = "REGULATION_PROBLEM"
    FEATURE_GAP = "FEATURE_GAP"
    TEMPORARY_INCIDENT = "TEMPORARY_INCIDENT"
    SUPPORT_QUESTION = "SUPPORT_QUESTION"
    USER_ERROR = "USER_ERROR"
    GENERAL_COMPLAINT = "GENERAL_COMPLAINT"


class ProblemFamily(StrEnum):
    MANUAL_DATA_ENTRY = "MANUAL_DATA_ENTRY"
    RECONCILIATION = "RECONCILIATION"
    INTEGRATION = "INTEGRATION"
    DOCUMENT_COLLECTION = "DOCUMENT_COLLECTION"
    REPORTING = "REPORTING"
    SCHEDULING = "SCHEDULING"
    APPROVAL = "APPROVAL"
    COMMUNICATION = "COMMUNICATION"
    MIGRATION = "MIGRATION"
    COMPLIANCE = "COMPLIANCE"
    HANDOVER = "HANDOVER"
    ERROR_CORRECTION = "ERROR_CORRECTION"
    SEARCH_RETRIEVAL = "SEARCH_RETRIEVAL"
    MONITORING = "MONITORING"
    PROCUREMENT = "PROCUREMENT"
    PAYMENTS = "PAYMENTS"
    INVENTORY = "INVENTORY"
    CUSTOMER_MANAGEMENT = "CUSTOMER_MANAGEMENT"
    WORKFORCE = "WORKFORCE"
    OTHER = "OTHER"


class WorkaroundType(StrEnum):
    SPREADSHEET = "SPREADSHEET"
    CSV = "CSV"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    PAPER = "PAPER"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    EMPLOYEE = "EMPLOYEE"
    FREELANCER = "FREELANCER"
    AGENCY = "AGENCY"
    VIRTUAL_ASSISTANT = "VIRTUAL_ASSISTANT"
    INTERNAL_SCRIPT = "INTERNAL_SCRIPT"
    CUSTOM_SOFTWARE = "CUSTOM_SOFTWARE"
    MULTIPLE_TOOLS = "MULTIPLE_TOOLS"
    EXISTING_SAAS = "EXISTING_SAAS"
    OTHER = "OTHER"


class ImpactType(StrEnum):
    TIME = "TIME"
    MONEY = "MONEY"
    REVENUE = "REVENUE"
    ERRORS = "ERRORS"
    CUSTOMER_LOSS = "CUSTOMER_LOSS"
    COMPLIANCE = "COMPLIANCE"
    RISK = "RISK"
    STRESS = "STRESS"
    DELAY = "DELAY"
    OTHER = "OTHER"


class PaymentEvidenceType(StrEnum):
    EXISTING_SOFTWARE_SPEND = "EXISTING_SOFTWARE_SPEND"
    EMPLOYEE_LABOR = "EMPLOYEE_LABOR"
    FREELANCER_SPEND = "FREELANCER_SPEND"
    AGENCY_SPEND = "AGENCY_SPEND"
    EXPLICIT_BUDGET = "EXPLICIT_BUDGET"
    PURCHASE_SEARCH = "PURCHASE_SEARCH"
    SWITCHING_INTENT = "SWITCHING_INTENT"
    PRICE_COMPLAINT = "PRICE_COMPLAINT"
    EXPLICIT_WILLINGNESS_TO_PAY = "EXPLICIT_WILLINGNESS_TO_PAY"


class PipelineStage(StrEnum):
    EXTRACTION = "EXTRACTION"


class PipelineStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ModelRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelRunRecord:
    id: str
    operation_key: str
    pipeline_run_id: str | None
    provider: str
    model: str
    pipeline_stage: str
    template_version: str
    external_run_id: str | None
    status: ModelRunStatus
    input_tokens: int
    output_tokens: int
    latency_ms: int
    items_processed: int
    error: str | None
    measured_cost: str | None
    currency: str | None
    cost_measurement_source: str | None


class ResearchCaseStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    REVIEW = "REVIEW"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"


class OpportunityStatus(StrEnum):
    DRAFT = "DRAFT"
    REPORT_READY = "REPORT_READY"


class OpportunityType(StrEnum):
    RECURRING_PROBLEM = "RECURRING_PROBLEM"
    STRONG_SINGLE_SIGNAL = "STRONG_SINGLE_SIGNAL"
    WORKFLOW_GAP = "WORKFLOW_GAP"
    INTEGRATION_GAP = "INTEGRATION_GAP"
    INCUMBENT_GAP = "INCUMBENT_GAP"
    UNDERSERVED_SEGMENT = "UNDERSERVED_SEGMENT"
    LOCALIZATION_GAP = "LOCALIZATION_GAP"
    REGULATION_GAP = "REGULATION_GAP"
    EMERGING_PROBLEM = "EMERGING_PROBLEM"


class OpportunityClaimRole(StrEnum):
    PROBLEM = "PROBLEM"
    SUPPORTING = "SUPPORTING"
    CONTEXT = "CONTEXT"
    CONTRADICTING = "CONTRADICTING"


class ResearchRequirement(StrEnum):
    WORKAROUND_RESEARCH = "WORKAROUND_RESEARCH"
    COMPETITION = "COMPETITION"
    DACH_TRANSFER = "DACH_TRANSFER"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"


class ResearchOutcome(StrEnum):
    EVIDENCE_FOUND = "EVIDENCE_FOUND"
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"


class RequirementStatus(StrEnum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"


class ActorEquivalence(StrEnum):
    DIRECT = "DIRECT"
    SIMILAR = "SIMILAR"
    DIFFERENT = "DIFFERENT"
    UNCLEAR = "UNCLEAR"


class WorkflowEquivalence(StrEnum):
    DIRECT = "DIRECT"
    LOCALIZED = "LOCALIZED"
    MATERIALLY_DIFFERENT = "MATERIALLY_DIFFERENT"
    UNKNOWN = "UNKNOWN"


class DachTransferType(StrEnum):
    DIRECT_TRANSFER = "DIRECT_TRANSFER"
    LOCALIZATION_REQUIRED = "LOCALIZATION_REQUIRED"
    LOCAL_FRICTION = "LOCAL_FRICTION"
    WEAK_LOCAL_EVIDENCE = "WEAK_LOCAL_EVIDENCE"
    MATERIAL_DIFFERENCE = "MATERIAL_DIFFERENCE"
    UNKNOWN = "UNKNOWN"


class LocalEvidenceState(StrEnum):
    NONE_FOUND = "NONE_FOUND"
    SINGLE_LOCAL_SIGNAL = "SINGLE_LOCAL_SIGNAL"
    MULTIPLE_LOCAL_SIGNALS = "MULTIPLE_LOCAL_SIGNALS"
    MULTI_SOURCE_LOCAL_SIGNALS = "MULTI_SOURCE_LOCAL_SIGNALS"


class StakeholderRole(StrEnum):
    END_USER = "END_USER"
    BUYER = "BUYER"
    DECISION_MAKER = "DECISION_MAKER"
    GATEKEEPER = "GATEKEEPER"
    INFLUENCER = "INFLUENCER"


class StakeholderKnowledge(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class SolutionType(StrEnum):
    DIRECT_SOFTWARE = "DIRECT_SOFTWARE"
    INDIRECT_SOFTWARE = "INDIRECT_SOFTWARE"
    LEGACY_SOFTWARE = "LEGACY_SOFTWARE"
    INTERNAL_TOOL = "INTERNAL_TOOL"
    MANUAL_PROCESS = "MANUAL_PROCESS"
    FREELANCER = "FREELANCER"
    AGENCY = "AGENCY"
    SERVICE_PROVIDER = "SERVICE_PROVIDER"
    DIY_SCRIPT = "DIY_SCRIPT"
    NO_SOLUTION_FOUND = "NO_SOLUTION_FOUND"


class CompetitorEvidenceRole(StrEnum):
    PROFILE = "PROFILE"
    PRICING = "PRICING"
    FEATURE = "FEATURE"
    INTEGRATION = "INTEGRATION"
    AVAILABILITY = "AVAILABILITY"
    INCUMBENT_FIX_RISK = "INCUMBENT_FIX_RISK"


class CounterEvidenceType(StrEnum):
    TEMPORARY_PROBLEM = "TEMPORARY_PROBLEM"
    FEATURE_ALREADY_EXISTS = "FEATURE_ALREADY_EXISTS"
    FEATURE_ANNOUNCED = "FEATURE_ANNOUNCED"
    FREE_WORKAROUND = "FREE_WORKAROUND"
    SATISFIED_WITH_WORKAROUND = "SATISFIED_WITH_WORKAROUND"
    LOW_FREQUENCY = "LOW_FREQUENCY"
    LOW_IMPACT = "LOW_IMPACT"
    VERY_SMALL_SEGMENT = "VERY_SMALL_SEGMENT"
    NO_PAYMENT_SIGNAL = "NO_PAYMENT_SIGNAL"
    HIGH_SWITCHING_COST = "HIGH_SWITCHING_COST"
    INCUMBENT_FIX_RISK = "INCUMBENT_FIX_RISK"
    REGULATORY_BARRIER = "REGULATORY_BARRIER"
    DISTRIBUTION_DIFFICULTY = "DISTRIBUTION_DIFFICULTY"
    DEPENDENCY_RISK = "DEPENDENCY_RISK"
    WEAK_DACH_TRANSFER = "WEAK_DACH_TRANSFER"
    CONTRADICTING_USERS = "CONTRADICTING_USERS"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class EvidenceRange:
    """A half-open range into the exact raw text of a source item."""

    start: int
    end: int

    def excerpt_from(self, text: str) -> str:
        if self.start < 0 or self.end <= self.start or self.end > len(text):
            raise ValueError("evidence range is outside source text")
        return text[self.start : self.end]


@dataclass(frozen=True, slots=True)
class WorkaroundSignalDraft:
    workaround_type: WorkaroundType
    description: str
    evidence_index: int


@dataclass(frozen=True, slots=True)
class ImpactSignalDraft:
    impact_type: ImpactType
    quantified: bool
    value: str | None
    unit: str | None
    frequency: str | None
    evidence_index: int


@dataclass(frozen=True, slots=True)
class PaymentSignalDraft:
    payment_type: PaymentEvidenceType
    amount: str | None
    currency: str | None
    frequency: str | None
    evidence_index: int


@dataclass(frozen=True, slots=True)
class SourceItemRecord:
    id: int
    source_id: int
    external_id: str
    raw_text: str
    country_code: str | None
    language_code: str | None


@dataclass(frozen=True, slots=True)
class SourceScanCandidate:
    source_id: int
    name: str
    primary_industry: str | None
    audience_type: AudienceType
    curation_priority: str | None
    research_role: str | None
    scan_directive: str
    recommended_action: str | None
    pilot_posts: int | None
    commercial_use_status: str | None
    production_ready: bool


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    id: int
    problem_type: ProblemType
    problem_family: ProblemFamily | None
    problem: str
    actor: str | None
    job_to_be_done: str | None
    context: str | None
    root_cause: str | None
    current_workaround: str | None
    tools_used: str | None


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    evidence_span_id: int
    source_name: str
    source_url: str | None
    excerpt: str
    evidence_scope: EvidenceScope
    commercial_use_status: str | None
    quoting_rules: str | None
    rights_reviewed_at: str | None


@dataclass(frozen=True, slots=True)
class EvidenceScopeSummary:
    evidence_scope: EvidenceScope
    problem_observation_count: int
    evidence_span_count: int
    cited_item_count: int
    source_count: int
    source_names: tuple[str, ...]
    country_codes: tuple[str, ...]
    dated_item_count: int
    earliest_published_at: str | None
    latest_published_at: str | None


@dataclass(frozen=True, slots=True)
class RequirementFinding:
    requirement: ResearchRequirement
    outcome: ResearchOutcome
    claim_text: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ValidationQuestion:
    question: str
    rationale: str | None


@dataclass(frozen=True, slots=True)
class DachAssessment:
    actor_equivalence: ActorEquivalence
    actor_rationale: str
    workflow_equivalence: WorkflowEquivalence
    workflow_rationale: str
    transfer_type: DachTransferType
    transfer_rationale: str
    local_evidence_state: LocalEvidenceState
    dach_observation_count: int
    dach_unique_author_count: int
    dach_source_count: int
    buyer_structure: str | None
    ecosystem_dependencies: tuple[str, ...]
    regulatory_dependencies: tuple[str, ...]
    switching_barriers: tuple[str, ...]
    localization_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseStakeholder:
    role: StakeholderRole
    knowledge: StakeholderKnowledge
    party: str | None
    note: str
    factual_claim_id: int | None


@dataclass(frozen=True, slots=True)
class CompetitorComplaint:
    complaint_id: int
    complaint_type: str
    statement: str
    affected_segment: str | None
    frequency_observed: str | None
    factual_claim_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Competitor:
    competitor_id: int
    name: str
    url: str | None
    solution_type: SolutionType
    target_customer: str | None
    market: str | None
    pricing: str | None
    pricing_model: str | None
    features: tuple[str, ...]
    integrations: tuple[str, ...]
    dach_available: bool | None
    dach_specific: bool | None
    incumbent_fix_risk: bool | None
    incumbent_fix_rationale: str | None
    factual_claim_ids: tuple[int, ...]
    complaints: tuple[CompetitorComplaint, ...]


@dataclass(frozen=True, slots=True)
class CounterEvidenceItem:
    counter_evidence_id: int
    evidence_type: CounterEvidenceType
    statement: str
    factual_claim_id: int


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    opportunity_id: int
    case_id: int
    title: str
    status: OpportunityStatus
    evidence_state: EvidenceState
    opportunity_types: tuple[OpportunityType, ...]


@dataclass(frozen=True, slots=True)
class SavedOpportunity:
    opportunity: OpportunityRecord
    note: str | None
    saved_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProblemProfile:
    problems: tuple[str, ...]
    actors: tuple[str, ...]
    jobs_to_be_done: tuple[str, ...]
    contexts: tuple[str, ...]
    tools_used: tuple[str, ...]
    workarounds: tuple[str, ...]
    impacts: tuple[str, ...]
    payment_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchCaseReportData:
    opportunity_id: int | None
    case_id: int
    title: str
    status: ResearchCaseStatus
    opportunity_status: OpportunityStatus | None
    opportunity_types: tuple[OpportunityType, ...]
    evidence_state: EvidenceState
    problem_profile: ProblemProfile
    global_evidence_summary: EvidenceScopeSummary
    dach_evidence_summary: EvidenceScopeSummary
    citations: tuple[EvidenceCitation, ...]
    findings: tuple[RequirementFinding, ...]
    competitors: tuple[Competitor, ...]
    counter_evidence: tuple[CounterEvidenceItem, ...]
    dach_assessment: DachAssessment | None
    stakeholders: tuple[CaseStakeholder, ...]
    unknowns: tuple[str, ...]
    validation_questions: tuple[ValidationQuestion, ...]


@dataclass(frozen=True, slots=True)
class RequirementProgress:
    requirement: ResearchRequirement
    status: RequirementStatus
    outcome: ResearchOutcome | None
    factual_claim_id: int | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ResearchCaseSummary:
    case_id: int
    cluster_id: int
    title: str
    status: ResearchCaseStatus
    requirements: tuple[RequirementProgress, ...]
    validation_question_count: int
    unknown_count: int

"""Small operational CLI for the initial vertical slice."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from .benchmark import benchmark_provenance_summary, benchmark_summary, load_benchmark
from .candidates import research_case_candidates
from .cluster_benchmark import evaluate_exact_clustering, load_clustering_benchmark
from .clustering import cluster_exact
from .connectors import JsonlFileConnector, ResearchJsonlCapture, SourceDescriptor
from .cost_reporting import build_cost_efficiency_report
from .domain import (
    OBSERVATION_FIELDS,
    ActorEquivalence,
    ClaimKind,
    CounterEvidenceType,
    DachTransferType,
    EvidenceRange,
    EvidenceScope,
    EvidenceState,
    ImpactType,
    LocalEvidenceState,
    ModelRunStatus,
    OpportunityStatus,
    OpportunityType,
    PaymentEvidenceType,
    ProblemFamily,
    ProblemType,
    ResearchCaseStatus,
    ResearchRequirement,
    SolutionType,
    SourceLifecycle,
    StakeholderKnowledge,
    StakeholderRole,
    WorkaroundType,
    WorkflowEquivalence,
)
from .evaluation import evaluate_predictions, load_predictions
from .evaluation_readiness import evaluate_readiness
from .extraction import run_extraction
from .ingestion import ingest, ingest_research_capture
from .integrity_audit import audit_evidence_integrity
from .pilot_planner import build_pilot_plan
from .prediction_extractor import JsonlPredictionExtractor
from .reddit import (
    DEFAULT_SUBREDDITS,
    QUERY_GROUPS,
    JsonlAcquisitionProvider,
    JsonlSearchProvider,
    acquire_discoveries,
    discover_subreddits,
)
from .reddit_reporting import build_reddit_report
from .reporting import build_opportunity_report
from .repository import Repository
from .research_benchmark import (
    evaluate_competition,
    evaluate_dach_transfer,
    load_competition_benchmark,
    load_dach_benchmark,
)
from .source_import import import_subreddit_csv
from .source_metrics import (
    plan_source_budget,
    ranked_source_performance,
    refresh_source_metrics,
    source_problem_family_performance,
)
from .source_policy import audit_source_policies


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="problem-intelligence")
    commands = result.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-db", help="initialize the database schema")
    init.add_argument("--database", type=Path, required=True)

    ingest = commands.add_parser("ingest-item", help="idempotently ingest one source item")
    ingest.add_argument("--database", type=Path, required=True)
    ingest.add_argument("--source-type", required=True)
    ingest.add_argument("--source-name", required=True)
    ingest.add_argument("--external-id", required=True)
    ingest.add_argument("--url")
    ingest.add_argument("--title")
    ingest.add_argument("--text", required=True)
    ingest.add_argument("--country")
    ingest.add_argument("--language")

    ingest_jsonl = commands.add_parser(
        "ingest-jsonl", help="idempotently ingest source items from a local JSONL file"
    )
    ingest_jsonl.add_argument("--database", type=Path, required=True)
    ingest_jsonl.add_argument("--file", type=Path, required=True)
    ingest_jsonl.add_argument("--source-type", required=True)
    ingest_jsonl.add_argument("--source-name", required=True)
    ingest_jsonl.add_argument("--commercial-use-status")
    ingest_jsonl.add_argument("--retention-rules")
    ingest_jsonl.add_argument("--attribution-requirements")
    ingest_jsonl.add_argument("--quoting-rules")
    ingest_jsonl.add_argument("--deletion-requirements")
    ingest_jsonl.add_argument("--rate-limit-notes")
    ingest_jsonl.add_argument("--rights-reviewed-at")

    ingest_research = commands.add_parser(
        "ingest-research-jsonl",
        help="ingest heterogeneous research evidence with explicit source policy",
    )
    ingest_research.add_argument("--database", type=Path, required=True)
    ingest_research.add_argument("--file", type=Path, required=True)

    source_lifecycle = commands.add_parser(
        "set-source-lifecycle", help="explicitly classify an ingested source"
    )
    source_lifecycle.add_argument("--database", type=Path, required=True)
    source_lifecycle.add_argument("--source-id", type=int, required=True)
    source_lifecycle.add_argument(
        "--lifecycle", choices=[item.value for item in SourceLifecycle], required=True
    )

    observation = commands.add_parser(
        "add-observation", help="record one manually reviewed structured problem observation"
    )
    observation.add_argument("--database", type=Path, required=True)
    observation.add_argument("--source-item-id", type=int, required=True)
    observation.add_argument(
        "--problem-type", choices=[item.value for item in ProblemType], required=True
    )
    observation.add_argument(
        "--problem-family", choices=[item.value for item in ProblemFamily], required=True
    )
    observation.add_argument(
        "--evidence-scope", choices=[item.value for item in EvidenceScope], required=True
    )
    observation.add_argument("--problem", required=True)
    observation.add_argument("--extraction-version", default="manual-v1")
    observation.add_argument(
        "--fields-json", default="{}", help="JSON object containing nullable extraction fields"
    )

    evidence = commands.add_parser(
        "add-evidence", help="record an exact character range from a source item"
    )
    evidence.add_argument("--database", type=Path, required=True)
    evidence.add_argument("--source-item-id", type=int, required=True)
    evidence.add_argument("--observation-id", type=int)
    evidence.add_argument("--start", type=int, required=True)
    evidence.add_argument("--end", type=int, required=True)
    evidence.add_argument(
        "--evidence-scope", choices=[item.value for item in EvidenceScope], required=True
    )

    classify_observation = commands.add_parser(
        "classify-observation",
        help="assign a versioned ontology family to an existing observation",
    )
    classify_observation.add_argument("--database", type=Path, required=True)
    classify_observation.add_argument("--observation-id", type=int, required=True)
    classify_observation.add_argument(
        "--problem-family", choices=[item.value for item in ProblemFamily], required=True
    )
    classify_observation.add_argument(
        "--ontology-version", default="problem-ontology-v1"
    )

    revise_observation = commands.add_parser(
        "revise-observation",
        help="apply an evidence-backed reviewed field correction with audit history",
    )
    revise_observation.add_argument("--database", type=Path, required=True)
    revise_observation.add_argument("--observation-id", type=int, required=True)
    revise_observation.add_argument(
        "--field",
        choices=sorted(OBSERVATION_FIELDS - {"pipeline_run_id"}),
        required=True,
    )
    revise_observation.add_argument(
        "--value-json", required=True, help="new string, boolean, or null encoded as JSON"
    )
    revise_observation.add_argument("--reason", required=True)
    revise_observation.add_argument("--evidence-id", type=int, required=True)
    revise_observation.add_argument("--revision-version", required=True)

    workaround = commands.add_parser(
        "add-workaround", help="attach an evidence-backed workaround to an observation"
    )
    workaround.add_argument("--database", type=Path, required=True)
    workaround.add_argument("--observation-id", type=int, required=True)
    workaround.add_argument("--evidence-id", type=int, required=True)
    workaround.add_argument(
        "--type", choices=[item.value for item in WorkaroundType], required=True
    )
    workaround.add_argument("--description", required=True)

    impact = commands.add_parser(
        "add-impact", help="attach an evidence-backed impact signal to an observation"
    )
    impact.add_argument("--database", type=Path, required=True)
    impact.add_argument("--observation-id", type=int, required=True)
    impact.add_argument("--evidence-id", type=int, required=True)
    impact.add_argument("--type", choices=[item.value for item in ImpactType], required=True)
    impact.add_argument("--quantified", action="store_true")
    impact.add_argument("--value")
    impact.add_argument("--unit")
    impact.add_argument("--frequency")

    payment = commands.add_parser(
        "add-payment", help="attach an evidence-backed payment signal to an observation"
    )
    payment.add_argument("--database", type=Path, required=True)
    payment.add_argument("--observation-id", type=int, required=True)
    payment.add_argument("--evidence-id", type=int, required=True)
    payment.add_argument(
        "--type", choices=[item.value for item in PaymentEvidenceType], required=True
    )
    payment.add_argument("--amount")
    payment.add_argument("--currency")
    payment.add_argument("--frequency")

    claim = commands.add_parser(
        "create-claim", help="record a typed claim and link its evidence atomically"
    )
    claim.add_argument("--database", type=Path, required=True)
    claim.add_argument("--claim-kind", choices=[item.value for item in ClaimKind], required=True)
    claim.add_argument("--text", required=True)
    claim.add_argument("--observation-id", type=int)
    claim.add_argument("--evidence-id", type=int, action="append", default=[])

    extract_predictions = commands.add_parser(
        "extract-predictions", help="run validated offline JSONL predictions"
    )
    extract_predictions.add_argument("--database", type=Path, required=True)
    extract_predictions.add_argument("--file", type=Path, required=True)
    extract_predictions.add_argument("--version", required=True)
    extract_predictions.add_argument("--source-item-id", type=int, action="append")
    extract_predictions.add_argument("--model-operation-key")
    extract_predictions.add_argument("--model-provider")
    extract_predictions.add_argument("--model")
    extract_predictions.add_argument("--template-version")
    extract_predictions.add_argument("--external-run-id")
    extract_predictions.add_argument("--input-tokens", type=int)
    extract_predictions.add_argument("--output-tokens", type=int)
    extract_predictions.add_argument("--latency-ms", type=int)
    extract_predictions.add_argument("--measured-cost")
    extract_predictions.add_argument("--currency")
    extract_predictions.add_argument("--cost-measurement-source")

    export_items = commands.add_parser(
        "export-items", help="export provider-neutral extraction inputs as JSONL"
    )
    export_items.add_argument("--database", type=Path, required=True)
    export_items.add_argument("--source-item-id", type=int, action="append")
    export_items.add_argument("--output", type=Path)

    stats = commands.add_parser("stats", help="print record counts as JSON")
    stats.add_argument("--database", type=Path, required=True)

    evidence_audit = commands.add_parser(
        "evidence-audit",
        help="measure unsupported facts and completed-research integrity violations",
    )
    evidence_audit.add_argument("--database", type=Path, required=True)
    evidence_audit.add_argument("--fail-on-violation", action="store_true")

    source_policy_audit = commands.add_parser(
        "source-policy-audit",
        help="measure source rights-policy completeness independently of write-time defaults",
    )
    source_policy_audit.add_argument("--database", type=Path, required=True)
    source_policy_audit.add_argument("--include-unused", action="store_true")
    source_policy_audit.add_argument("--fail-on-violation", action="store_true")

    model_run = commands.add_parser(
        "record-model-run",
        help="idempotently record exact provider/model usage and optional measured cost",
    )
    model_run.add_argument("--database", type=Path, required=True)
    model_run.add_argument("--operation-key", required=True)
    model_run.add_argument("--provider", required=True)
    model_run.add_argument("--model", required=True)
    model_run.add_argument("--pipeline-stage", required=True)
    model_run.add_argument("--template-version", required=True)
    model_run.add_argument(
        "--status", choices=[item.value for item in ModelRunStatus], required=True
    )
    model_run.add_argument("--input-tokens", type=int, required=True)
    model_run.add_argument("--output-tokens", type=int, required=True)
    model_run.add_argument("--latency-ms", type=int, required=True)
    model_run.add_argument("--items-processed", type=int, required=True)
    model_run.add_argument("--pipeline-run-id")
    model_run.add_argument("--external-run-id")
    model_run.add_argument("--error")
    model_run.add_argument("--measured-cost")
    model_run.add_argument("--currency")
    model_run.add_argument("--cost-measurement-source")

    show_model_run = commands.add_parser(
        "show-model-run", help="show one recorded provider/model operation"
    )
    show_model_run.add_argument("--database", type=Path, required=True)
    show_model_run.add_argument("--model-run-id", required=True)

    discover_reddit = commands.add_parser(
        "reddit-discover", help="replay a provider search capture into Reddit discoveries"
    )
    discover_reddit.add_argument("--database", type=Path, required=True)
    discover_reddit.add_argument("--capture", type=Path, required=True)
    discover_reddit.add_argument("--subreddit", action="append")
    discover_reddit.add_argument(
        "--query-group", action="append", choices=list(QUERY_GROUPS)
    )
    discover_reddit.add_argument(
        "--time-context", help='optional deterministic search phrase, for example "past year"'
    )

    acquire_reddit = commands.add_parser(
        "reddit-acquire", help="replay a provider content capture for pending discoveries"
    )
    acquire_reddit.add_argument("--database", type=Path, required=True)
    acquire_reddit.add_argument("--capture", type=Path, required=True)

    reddit_report = commands.add_parser(
        "reddit-report", help="render Reddit discovery/acquisition performance"
    )
    reddit_report.add_argument("--database", type=Path, required=True)
    reddit_report.add_argument("--json-output", type=Path)
    reddit_report.add_argument("--markdown-output", type=Path)

    sources_import = commands.add_parser(
        "sources-import", help="import a legacy subreddit CSV as untrusted metadata"
    )
    sources_import.add_argument("--database", type=Path, required=True)
    sources_import.add_argument("--file", type=Path, required=True)

    sources_plan = commands.add_parser(
        "sources-plan", help="list curated immediate-scan candidates with policy readiness"
    )
    sources_plan.add_argument("--database", type=Path, required=True)
    sources_plan.add_argument("--priority", action="append")
    sources_plan.add_argument("--limit", type=int)

    sources_pilot_plan = commands.add_parser(
        "sources-pilot-plan",
        help="build the deterministic CORE/PILOT scan plan from the strict audit",
    )
    sources_pilot_plan.add_argument("--database", type=Path, required=True)
    sources_pilot_plan.add_argument("--json-output", type=Path)
    sources_pilot_plan.add_argument("--csv-output", type=Path)
    sources_pilot_plan.add_argument("--markdown-output", type=Path)

    source_metrics = commands.add_parser(
        "source-metrics-refresh",
        help="persist empirical source-performance snapshots from stored evidence",
    )
    source_metrics.add_argument("--database", type=Path, required=True)
    source_metrics.add_argument("--measurement-key", default="cumulative")

    source_performance = commands.add_parser(
        "source-performance",
        help="rank persisted source measurements by one transparent dimension",
    )
    source_performance.add_argument("--database", type=Path, required=True)
    source_performance.add_argument("--measurement-key", default="cumulative")
    source_performance.add_argument(
        "--sort",
        choices=(
            "strong-signal-yield",
            "payment-yield",
            "active-search-yield",
            "cluster-yield",
            "cross-source-yield",
            "cost-per-strong-signal",
            "newest-evidence",
        ),
        default="strong-signal-yield",
    )
    source_performance.add_argument(
        "--lifecycle", choices=[item.value for item in SourceLifecycle], action="append"
    )
    source_performance.add_argument("--minimum-items", type=int, default=0)
    source_performance.add_argument("--production-ready-only", action="store_true")
    source_performance.add_argument("--limit", type=int)

    source_budget = commands.add_parser(
        "source-budget-plan",
        help="allocate explicit performance and exploration scan lanes",
    )
    source_budget.add_argument("--database", type=Path, required=True)
    source_budget.add_argument("--measurement-key", default="cumulative")
    source_budget.add_argument("--total-items", type=int, required=True)
    source_budget.add_argument("--exploration-items", type=int, required=True)
    source_budget.add_argument("--per-source-cap", type=int, required=True)
    source_budget.add_argument("--minimum-performance-items", type=int, required=True)
    source_budget.add_argument(
        "--performance-sort",
        choices=(
            "strong-signal-yield",
            "payment-yield",
            "active-search-yield",
            "cluster-yield",
            "cross-source-yield",
            "cost-per-strong-signal",
            "newest-evidence",
        ),
        default="strong-signal-yield",
    )

    cost_report = commands.add_parser(
        "cost-report",
        help="report measured provider-cost coverage and exact unit costs",
    )
    cost_report.add_argument("--database", type=Path, required=True)
    cost_report.add_argument("--provider")
    cost_report.add_argument("--pipeline-stage")

    benchmark = commands.add_parser(
        "validate-benchmark", help="validate a manually labelled JSONL benchmark"
    )
    benchmark.add_argument("--fixture", type=Path, required=True)

    evaluate = commands.add_parser(
        "evaluate-benchmark", help="score JSONL predictions against a benchmark fixture"
    )
    evaluate.add_argument("--fixture", type=Path, required=True)
    evaluate.add_argument("--predictions", type=Path, required=True)

    cluster_benchmark = commands.add_parser(
        "evaluate-clustering", help="score exact fingerprint clustering against a fixture"
    )
    cluster_benchmark.add_argument("--fixture", type=Path, required=True)

    validate_competition = commands.add_parser(
        "validate-competition-benchmark",
        help="validate evidence-linked competition benchmark labels",
    )
    validate_competition.add_argument("--fixture", type=Path, required=True)

    evaluate_competition_parser = commands.add_parser(
        "evaluate-competition", help="measure strict existing-solution recall and precision"
    )
    evaluate_competition_parser.add_argument("--fixture", type=Path, required=True)
    evaluate_competition_parser.add_argument("--predictions", type=Path, required=True)

    validate_dach = commands.add_parser(
        "validate-dach-benchmark",
        help="validate evidence-linked DACH transfer benchmark labels",
    )
    validate_dach.add_argument("--fixture", type=Path, required=True)

    evaluate_dach = commands.add_parser(
        "evaluate-dach-transfer", help="measure strict DACH transfer classification accuracy"
    )
    evaluate_dach.add_argument("--fixture", type=Path, required=True)
    evaluate_dach.add_argument("--predictions", type=Path, required=True)

    readiness = commands.add_parser(
        "evaluation-readiness",
        help="evaluate explicit benchmark coverage and quality gates before scaling",
    )
    readiness.add_argument("--manifest", type=Path, required=True)
    readiness.add_argument("--require-ready", action="store_true")

    cluster = commands.add_parser(
        "cluster-exact", help="persist deterministic exact-fingerprint clusters"
    )
    cluster.add_argument("--database", type=Path, required=True)
    cluster.add_argument("--version", default="exact-fingerprint-v1")

    candidates = commands.add_parser(
        "case-candidates",
        help="list explainable research candidates without an opportunity score",
    )
    candidates.add_argument("--database", type=Path, required=True)
    candidates.add_argument(
        "--sort",
        choices=(
            "strongest-evidence",
            "newest",
            "active-search",
            "payment-evidence",
            "manual-workarounds",
            "dach-evidence",
        ),
        default="strongest-evidence",
    )
    candidates.add_argument("--include-opened", action="store_true")
    candidates.add_argument("--research-ready-only", action="store_true")
    candidates.add_argument("--algorithm-version", default="exact-fingerprint-v1")

    create_case = commands.add_parser("create-case", help="open a research case for a cluster")
    create_case.add_argument("--database", type=Path, required=True)
    create_case.add_argument("--cluster-id", type=int, required=True)
    create_case.add_argument("--title", required=True)

    show_case = commands.add_parser(
        "show-case", help="show research state, requirements, and validation progress"
    )
    show_case.add_argument("--database", type=Path, required=True)
    show_case.add_argument("--case-id", type=int, required=True)

    dach = commands.add_parser(
        "set-dach-assessment", help="create or replace a structured DACH assessment"
    )
    dach.add_argument("--database", type=Path, required=True)
    dach.add_argument("--case-id", type=int, required=True)
    dach.add_argument(
        "--actor-equivalence",
        choices=[item.value for item in ActorEquivalence],
        required=True,
    )
    dach.add_argument("--actor-rationale", required=True)
    dach.add_argument(
        "--workflow-equivalence",
        choices=[item.value for item in WorkflowEquivalence],
        required=True,
    )
    dach.add_argument("--workflow-rationale", required=True)
    dach.add_argument(
        "--transfer-type", choices=[item.value for item in DachTransferType], required=True
    )
    dach.add_argument("--transfer-rationale", required=True)
    dach.add_argument(
        "--local-evidence-state",
        choices=[item.value for item in LocalEvidenceState],
        required=True,
    )
    dach.add_argument("--dach-observation-count", type=int, required=True)
    dach.add_argument("--dach-unique-author-count", type=int, required=True)
    dach.add_argument("--dach-source-count", type=int, required=True)
    dach.add_argument("--buyer-structure")
    dach.add_argument("--ecosystem-dependency", action="append", default=[])
    dach.add_argument("--regulatory-dependency", action="append", default=[])
    dach.add_argument("--switching-barrier", action="append", default=[])
    dach.add_argument("--localization-gap", action="append", default=[])

    stakeholder = commands.add_parser(
        "set-stakeholder",
        help="record a known evidence-backed or explicitly unknown case stakeholder",
    )
    stakeholder.add_argument("--database", type=Path, required=True)
    stakeholder.add_argument("--case-id", type=int, required=True)
    stakeholder.add_argument(
        "--role", choices=[item.value for item in StakeholderRole], required=True
    )
    stakeholder.add_argument(
        "--knowledge",
        choices=[item.value for item in StakeholderKnowledge],
        required=True,
    )
    stakeholder.add_argument("--party")
    stakeholder.add_argument("--claim-id", type=int)
    stakeholder.add_argument("--note", required=True)

    competitor = commands.add_parser(
        "add-competitor", help="record an evidence-backed solution or alternative"
    )
    competitor.add_argument("--database", type=Path, required=True)
    competitor.add_argument("--case-id", type=int, required=True)
    competitor.add_argument("--name", required=True)
    competitor.add_argument("--url")
    competitor.add_argument(
        "--solution-type", choices=[item.value for item in SolutionType], required=True
    )
    competitor.add_argument("--profile-claim-id", type=int, required=True)
    competitor.add_argument("--target-customer")
    competitor.add_argument("--market")
    competitor.add_argument("--pricing")
    competitor.add_argument("--pricing-model")
    competitor.add_argument("--feature", action="append", default=[])
    competitor.add_argument("--integration", action="append", default=[])
    competitor.add_argument("--dach-available", choices=("UNKNOWN", "YES", "NO"), default="UNKNOWN")
    competitor.add_argument("--dach-specific", choices=("UNKNOWN", "YES", "NO"), default="UNKNOWN")
    competitor.add_argument(
        "--incumbent-fix-risk", choices=("UNKNOWN", "YES", "NO"), default="UNKNOWN"
    )
    competitor.add_argument("--incumbent-fix-rationale")

    complaint = commands.add_parser(
        "add-competitor-complaint", help="record an evidence-backed competitor complaint"
    )
    complaint.add_argument("--database", type=Path, required=True)
    complaint.add_argument("--competitor-id", type=int, required=True)
    complaint.add_argument("--complaint-type", required=True)
    complaint.add_argument("--statement", required=True)
    complaint.add_argument("--claim-id", type=int, action="append", required=True)
    complaint.add_argument("--affected-segment")
    complaint.add_argument("--frequency-observed")

    counter = commands.add_parser(
        "add-counter-evidence", help="record a typed evidence-backed counterargument"
    )
    counter.add_argument("--database", type=Path, required=True)
    counter.add_argument("--case-id", type=int, required=True)
    counter.add_argument(
        "--type", choices=[item.value for item in CounterEvidenceType], required=True
    )
    counter.add_argument("--statement", required=True)
    counter.add_argument("--claim-id", type=int, required=True)

    satisfy = commands.add_parser(
        "satisfy-requirement", help="link factual evidence to a research requirement"
    )
    satisfy.add_argument("--database", type=Path, required=True)
    satisfy.add_argument("--case-id", type=int, required=True)
    satisfy.add_argument(
        "--requirement", choices=[item.value for item in ResearchRequirement], required=True
    )
    satisfy.add_argument("--claim-id", type=int)
    satisfy.add_argument("--no-evidence-found", action="store_true")
    satisfy.add_argument("--note")

    unknown = commands.add_parser(
        "add-unknown", help="record an unresolved research question or missing fact"
    )
    unknown.add_argument("--database", type=Path, required=True)
    unknown.add_argument("--case-id", type=int, required=True)
    unknown.add_argument("--statement", required=True)

    question = commands.add_parser(
        "add-validation-question", help="add a question that must be answered by validation"
    )
    question.add_argument("--database", type=Path, required=True)
    question.add_argument("--case-id", type=int, required=True)
    question.add_argument("--question", required=True)
    question.add_argument("--rationale")

    transition = commands.add_parser("transition-case", help="move a research case to a new state")
    transition.add_argument("--database", type=Path, required=True)
    transition.add_argument("--case-id", type=int, required=True)
    transition.add_argument(
        "--status", choices=[item.value for item in ResearchCaseStatus], required=True
    )

    create_opportunity = commands.add_parser(
        "create-opportunity", help="project a completed research case into an opportunity"
    )
    create_opportunity.add_argument("--database", type=Path, required=True)
    create_opportunity.add_argument("--case-id", type=int, required=True)
    create_opportunity.add_argument("--title")
    create_opportunity.add_argument(
        "--type",
        dest="opportunity_types",
        choices=[item.value for item in OpportunityType],
        action="append",
        required=True,
    )

    show_opportunity = commands.add_parser(
        "show-opportunity", help="show an opportunity projection and evidence state"
    )
    show_opportunity.add_argument("--database", type=Path, required=True)
    show_opportunity.add_argument("--opportunity-id", type=int, required=True)

    search_opportunities = commands.add_parser(
        "search-opportunities",
        help="search and filter researched opportunities without an opportunity score",
    )
    search_opportunities.add_argument("--database", type=Path, required=True)
    search_opportunities.add_argument("--query")
    search_opportunities.add_argument(
        "--status", choices=[item.value for item in OpportunityStatus]
    )
    search_opportunities.add_argument(
        "--evidence-state", choices=[item.value for item in EvidenceState]
    )
    search_opportunities.add_argument(
        "--type", choices=[item.value for item in OpportunityType]
    )
    search_opportunities.add_argument("--saved-only", action="store_true")
    search_opportunities.add_argument("--limit", type=int, default=100)

    transition_opportunity = commands.add_parser(
        "transition-opportunity", help="move an opportunity to REPORT_READY"
    )
    transition_opportunity.add_argument("--database", type=Path, required=True)
    transition_opportunity.add_argument("--opportunity-id", type=int, required=True)
    transition_opportunity.add_argument(
        "--status", choices=[OpportunityStatus.REPORT_READY.value], required=True
    )

    save_opportunity = commands.add_parser(
        "save-opportunity", help="save a report-ready opportunity for later investigation"
    )
    save_opportunity.add_argument("--database", type=Path, required=True)
    save_opportunity.add_argument("--opportunity-id", type=int, required=True)
    save_opportunity.add_argument("--note")

    unsave_opportunity = commands.add_parser(
        "unsave-opportunity", help="remove an opportunity from the local saved list"
    )
    unsave_opportunity.add_argument("--database", type=Path, required=True)
    unsave_opportunity.add_argument("--opportunity-id", type=int, required=True)

    saved_opportunities = commands.add_parser(
        "saved-opportunities", help="list locally saved report-ready opportunities"
    )
    saved_opportunities.add_argument("--database", type=Path, required=True)

    report = commands.add_parser("report", help="render a REPORT_READY opportunity as Markdown")
    report.add_argument("--database", type=Path, required=True)
    report.add_argument("--opportunity-id", type=int, required=True)
    report.add_argument("--output", type=Path)
    report.add_argument("--language", choices=("de", "en"), default="de")
    report.add_argument(
        "--include-unapproved-excerpts",
        action="store_true",
        help="internal review only: show excerpts whose display rights are not approved",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "validate-benchmark":
        print(json.dumps(benchmark_summary(load_benchmark(args.fixture)), indent=2, sort_keys=True))
        return 0
    if args.command == "evaluate-benchmark":
        cases = load_benchmark(args.fixture)
        predictions = load_predictions(args.predictions, cases)
        print(json.dumps(evaluate_predictions(cases, predictions), indent=2, sort_keys=True))
        return 0
    if args.command == "evaluate-clustering":
        cases = load_clustering_benchmark(args.fixture)
        print(
            json.dumps(
                {
                    **evaluate_exact_clustering(cases),
                    **benchmark_provenance_summary(case.provenance for case in cases),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "validate-competition-benchmark":
        cases = load_competition_benchmark(args.fixture)
        print(
            json.dumps(
                {
                    "cases": len(cases),
                    "solutions": sum(len(case.solutions) for case in cases),
                    "evidence_urls": sum(len(case.evidence_urls) for case in cases),
                    **benchmark_provenance_summary(
                        case.provenance
                        for case in cases
                        if case.provenance is not None
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "evaluate-competition":
        cases = load_competition_benchmark(args.fixture)
        predictions = load_competition_benchmark(
            args.predictions, require_evidence=False
        )
        print(
            json.dumps(
                evaluate_competition(cases, predictions), indent=2, sort_keys=True
            )
        )
        return 0
    if args.command == "validate-dach-benchmark":
        cases = load_dach_benchmark(args.fixture)
        print(
            json.dumps(
                {
                    "cases": len(cases),
                    "evidence_urls": sum(len(case.evidence_urls) for case in cases),
                    **benchmark_provenance_summary(
                        case.provenance
                        for case in cases
                        if case.provenance is not None
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "evaluate-dach-transfer":
        cases = load_dach_benchmark(args.fixture)
        predictions = load_dach_benchmark(args.predictions, require_evidence=False)
        print(
            json.dumps(
                evaluate_dach_transfer(cases, predictions), indent=2, sort_keys=True
            )
        )
        return 0
    if args.command == "evaluation-readiness":
        readiness_result = evaluate_readiness(args.manifest)
        print(json.dumps(readiness_result.to_dict(), indent=2, sort_keys=True))
        if args.require_ready and not readiness_result.ready_for_scale:
            return 1
        return 0

    repository = Repository(args.database)
    try:
        repository.initialize()
        if args.command == "init-db":
            print(f"Initialized {args.database}")
        elif args.command == "ingest-item":
            source_id = repository.upsert_source(
                source_type=args.source_type, name=args.source_name
            )
            item_id = repository.upsert_source_item(
                source_id=source_id,
                external_id=args.external_id,
                raw_text=args.text,
                url=args.url,
                title=args.title,
                country_code=args.country,
                language_code=args.language,
            )
            print(json.dumps({"source_id": source_id, "source_item_id": item_id}))
        elif args.command == "ingest-jsonl":
            connector = JsonlFileConnector(
                args.file,
                source=SourceDescriptor(
                    source_type=args.source_type,
                    name=args.source_name,
                    access_method="operator-supplied-local-jsonl",
                    commercial_use_status=args.commercial_use_status,
                    retention_rules=args.retention_rules,
                    attribution_requirements=args.attribution_requirements,
                    quoting_rules=args.quoting_rules,
                    deletion_requirements=args.deletion_requirements,
                    rate_limit_notes=args.rate_limit_notes,
                    rights_reviewed_at=args.rights_reviewed_at,
                ),
            )
            result = ingest(repository, connector)
            print(
                json.dumps(
                    {
                        "source_id": result.source_id,
                        "processed_items": result.processed_items,
                        "source_item_ids": result.source_item_ids,
                    }
                )
            )
        elif args.command == "ingest-research-jsonl":
            capture_result = ingest_research_capture(
                repository, ResearchJsonlCapture(args.file)
            )
            print(
                json.dumps(
                    {
                        "processed_sources": capture_result.processed_sources,
                        "processed_items": capture_result.processed_items,
                        "source_ids": capture_result.source_ids,
                        "source_item_ids": capture_result.source_item_ids,
                    }
                )
            )
        elif args.command == "set-source-lifecycle":
            repository.set_source_lifecycle(
                args.source_id, SourceLifecycle(args.lifecycle)
            )
            print(json.dumps({"source_id": args.source_id, "lifecycle": args.lifecycle}))
        elif args.command == "add-observation":
            fields = json.loads(args.fields_json)
            if not isinstance(fields, dict) or any(
                not isinstance(key, str) for key in cast(dict[object, object], fields)
            ):
                raise ValueError("--fields-json must contain a JSON object with string keys")
            typed_fields = cast(dict[str, Any], fields)
            observation_id = repository.create_observation(
                source_item_id=args.source_item_id,
                problem_type=ProblemType(args.problem_type),
                problem_family=ProblemFamily(args.problem_family),
                ontology_version="problem-ontology-v1",
                evidence_scope=EvidenceScope(args.evidence_scope),
                problem=args.problem,
                extraction_version=args.extraction_version,
                fields=typed_fields,
            )
            print(json.dumps({"observation_id": observation_id}))
        elif args.command == "add-evidence":
            evidence_id = repository.add_evidence_span(
                source_item_id=args.source_item_id,
                observation_id=args.observation_id,
                evidence_range=EvidenceRange(args.start, args.end),
                evidence_scope=EvidenceScope(args.evidence_scope),
            )
            print(json.dumps({"evidence_id": evidence_id}))
        elif args.command == "classify-observation":
            repository.set_observation_problem_family(
                args.observation_id,
                problem_family=ProblemFamily(args.problem_family),
                ontology_version=args.ontology_version,
            )
            print(
                json.dumps(
                    {
                        "observation_id": args.observation_id,
                        "problem_family": args.problem_family,
                        "ontology_version": args.ontology_version,
                    }
                )
            )
        elif args.command == "revise-observation":
            revision_id = repository.revise_observation_field(
                observation_id=args.observation_id,
                field_name=args.field,
                value=json.loads(args.value_json),
                reason=args.reason,
                evidence_span_id=args.evidence_id,
                revision_version=args.revision_version,
            )
            print(
                json.dumps(
                    {
                        "revision_id": revision_id,
                        "observation_id": args.observation_id,
                        "field": args.field,
                        "clustering_invalidated": True,
                    }
                )
            )
        elif args.command == "add-workaround":
            signal_id = repository.add_workaround_signal(
                observation_id=args.observation_id,
                evidence_span_id=args.evidence_id,
                workaround_type=WorkaroundType(args.type),
                description=args.description,
            )
            print(json.dumps({"workaround_id": signal_id}))
        elif args.command == "add-impact":
            signal_id = repository.add_impact_signal(
                observation_id=args.observation_id,
                evidence_span_id=args.evidence_id,
                impact_type=ImpactType(args.type),
                quantified=args.quantified,
                value=args.value,
                unit=args.unit,
                frequency=args.frequency,
            )
            print(json.dumps({"impact_signal_id": signal_id}))
        elif args.command == "add-payment":
            signal_id = repository.add_payment_signal(
                observation_id=args.observation_id,
                evidence_span_id=args.evidence_id,
                payment_type=PaymentEvidenceType(args.type),
                amount=args.amount,
                currency=args.currency,
                frequency=args.frequency,
            )
            print(json.dumps({"payment_signal_id": signal_id}))
        elif args.command == "create-claim":
            claim_id = repository.create_claim(
                claim_kind=ClaimKind(args.claim_kind),
                text=args.text,
                observation_id=args.observation_id,
                evidence_span_ids=args.evidence_id,
            )
            print(json.dumps({"claim_id": claim_id}))
        elif args.command == "extract-predictions":
            telemetry_values = {
                "model_operation_key": args.model_operation_key,
                "model_provider": args.model_provider,
                "model": args.model,
                "template_version": args.template_version,
                "input_tokens": args.input_tokens,
                "output_tokens": args.output_tokens,
                "latency_ms": args.latency_ms,
            }
            cost_values = {
                "measured_cost": args.measured_cost,
                "currency": args.currency,
                "cost_measurement_source": args.cost_measurement_source,
            }
            telemetry_requested = any(
                value is not None
                for value in (
                    *telemetry_values.values(),
                    args.external_run_id,
                    *cost_values.values(),
                )
            )
            if telemetry_requested:
                missing = [
                    name for name, value in telemetry_values.items() if value is None
                ]
                if missing:
                    raise ValueError(
                        "model telemetry is missing: " + ", ".join(sorted(missing))
                    )
                for name in (
                    "model_operation_key",
                    "model_provider",
                    "model",
                    "template_version",
                ):
                    if not str(telemetry_values[name]).strip():
                        raise ValueError(f"{name} must not be empty")
                for name in ("input_tokens", "output_tokens", "latency_ms"):
                    if int(telemetry_values[name]) < 0:
                        raise ValueError(f"{name} must not be negative")
                if any(value is not None for value in cost_values.values()) and not all(
                    value is not None for value in cost_values.values()
                ):
                    raise ValueError(
                        "measured cost, currency, and measurement source must be supplied together"
                    )
                if args.measured_cost is not None:
                    try:
                        amount = Decimal(args.measured_cost)
                    except InvalidOperation as exc:
                        raise ValueError("measured cost must be a decimal number") from exc
                    if not amount.is_finite() or amount < 0:
                        raise ValueError("measured cost must be finite and non-negative")
                    if len(args.currency.strip()) != 3 or not args.currency.isalpha():
                        raise ValueError("currency must be a three-letter code")
                    if not args.cost_measurement_source.strip():
                        raise ValueError("cost measurement source must not be empty")
            extractor = JsonlPredictionExtractor(args.file, version=args.version)
            result = run_extraction(
                repository,
                extractor,
                source_item_ids=args.source_item_id,
            )
            model_run_id = None
            if telemetry_requested:
                model_run = repository.record_model_run(
                    operation_key=args.model_operation_key,
                    provider=args.model_provider,
                    model=args.model,
                    pipeline_stage="structured-extraction",
                    template_version=args.template_version,
                    status=ModelRunStatus.COMPLETED,
                    input_tokens=args.input_tokens,
                    output_tokens=args.output_tokens,
                    latency_ms=args.latency_ms,
                    items_processed=result.processed_items,
                    pipeline_run_id=result.pipeline_run_id,
                    external_run_id=args.external_run_id,
                    measured_cost=args.measured_cost,
                    currency=args.currency,
                    cost_measurement_source=args.cost_measurement_source,
                )
                model_run_id = model_run.id
            print(
                json.dumps(
                    {
                        "pipeline_run_id": result.pipeline_run_id,
                        "processed_items": result.processed_items,
                        "created_observations": result.created_observations,
                        "model_run_id": model_run_id,
                    }
                )
            )
        elif args.command == "export-items":
            items = repository.source_items(args.source_item_id)
            if args.source_item_id is not None and len(items) != len(set(args.source_item_id)):
                raise ValueError("one or more source items do not exist")
            payload = "".join(
                json.dumps(
                    {
                        "source_item_id": item.id,
                        "external_id": item.external_id,
                        "text": item.raw_text,
                        "country_code": item.country_code,
                        "language_code": item.language_code,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for item in items
            )
            if args.output:
                args.output.write_text(payload, encoding="utf-8")
                print(json.dumps({"items": len(items), "output": str(args.output)}))
            else:
                print(payload, end="")
        elif args.command == "evidence-audit":
            audit = audit_evidence_integrity(repository)
            print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
            if args.fail_on_violation and not audit.clean:
                return 1
        elif args.command == "source-policy-audit":
            policy_audit = audit_source_policies(repository, include_unused=args.include_unused)
            print(json.dumps(policy_audit.to_dict(), indent=2, sort_keys=True))
            if args.fail_on_violation and not policy_audit.clean:
                return 1
        elif args.command == "record-model-run":
            run = repository.record_model_run(
                operation_key=args.operation_key,
                provider=args.provider,
                model=args.model,
                pipeline_stage=args.pipeline_stage,
                template_version=args.template_version,
                status=ModelRunStatus(args.status),
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                latency_ms=args.latency_ms,
                items_processed=args.items_processed,
                pipeline_run_id=args.pipeline_run_id,
                external_run_id=args.external_run_id,
                error=args.error,
                measured_cost=args.measured_cost,
                currency=args.currency,
                cost_measurement_source=args.cost_measurement_source,
            )
            print(
                json.dumps(
                    {
                        "model_run_id": run.id,
                        "operation_key": run.operation_key,
                        "status": run.status.value,
                        "measured_cost": run.measured_cost,
                        "currency": run.currency,
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "show-model-run":
            run = repository.model_run(args.model_run_id)
            print(
                json.dumps(
                    {
                        "id": run.id,
                        "operation_key": run.operation_key,
                        "pipeline_run_id": run.pipeline_run_id,
                        "provider": run.provider,
                        "model": run.model,
                        "pipeline_stage": run.pipeline_stage,
                        "template_version": run.template_version,
                        "external_run_id": run.external_run_id,
                        "status": run.status.value,
                        "input_tokens": run.input_tokens,
                        "output_tokens": run.output_tokens,
                        "latency_ms": run.latency_ms,
                        "items_processed": run.items_processed,
                        "error": run.error,
                        "measured_cost": run.measured_cost,
                        "currency": run.currency,
                        "cost_measurement_source": run.cost_measurement_source,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "stats":
            print(json.dumps(repository.stats(), indent=2, sort_keys=True))
        elif args.command == "reddit-discover":
            provider = JsonlSearchProvider(args.capture)
            run_ids = discover_subreddits(
                repository,
                provider,
                subreddits=tuple(args.subreddit or DEFAULT_SUBREDDITS),
                query_groups=tuple(args.query_group or QUERY_GROUPS),
                time_context=args.time_context,
            )
            print(json.dumps({"provider": provider.name, "discovery_run_ids": run_ids}))
        elif args.command == "reddit-acquire":
            provider = JsonlAcquisitionProvider(args.capture)
            acquisition_ids = acquire_discoveries(repository, provider)
            print(json.dumps({"provider": provider.name, "acquisition_ids": acquisition_ids}))
        elif args.command == "reddit-report":
            reddit = build_reddit_report(repository)
            if args.json_output:
                args.json_output.write_text(reddit.to_json(), encoding="utf-8")
            if args.markdown_output:
                args.markdown_output.write_text(reddit.to_markdown(), encoding="utf-8")
            if args.json_output or args.markdown_output:
                print(
                    json.dumps(
                        {
                            "json_output": str(args.json_output) if args.json_output else None,
                            "markdown_output": (
                                str(args.markdown_output) if args.markdown_output else None
                            ),
                        }
                    )
                )
            else:
                print(reddit.to_json(), end="")
        elif args.command == "sources-import":
            sources_before = repository.stats()["sources"]
            source_ids = import_subreddit_csv(repository, args.file)
            created = repository.stats()["sources"] - sources_before
            print(
                json.dumps(
                    {
                        "imported_rows": len(source_ids),
                        "created_sources": created,
                        "updated_sources": len(source_ids) - created,
                        "source_ids": source_ids,
                    }
                )
            )
        elif args.command == "sources-plan":
            candidates = repository.source_scan_candidates(
                priorities=args.priority,
                limit=args.limit,
            )
            print(
                json.dumps(
                    {
                        "candidate_count": len(candidates),
                        "production_ready_count": sum(
                            candidate.production_ready for candidate in candidates
                        ),
                        "candidates": [
                            {
                                "source_id": candidate.source_id,
                                "name": candidate.name,
                                "primary_industry": candidate.primary_industry,
                                "audience_type": candidate.audience_type.value,
                                "curation_priority": candidate.curation_priority,
                                "research_role": candidate.research_role,
                                "scan_directive": candidate.scan_directive,
                                "recommended_action": candidate.recommended_action,
                                "pilot_posts": candidate.pilot_posts,
                                "commercial_use_status": candidate.commercial_use_status,
                                "production_ready": candidate.production_ready,
                            }
                            for candidate in candidates
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "sources-pilot-plan":
            plan = build_pilot_plan(repository)
            if args.json_output:
                args.json_output.write_text(plan.to_json(), encoding="utf-8")
            if args.csv_output:
                args.csv_output.write_text(plan.to_csv(), encoding="utf-8")
            if args.markdown_output:
                args.markdown_output.write_text(plan.to_markdown(), encoding="utf-8")
            if args.json_output or args.csv_output or args.markdown_output:
                print(
                    json.dumps(
                        {
                            "entry_count": len(plan.entries),
                            "manifest_count": len(plan.manifest),
                            "json_output": str(args.json_output) if args.json_output else None,
                            "csv_output": str(args.csv_output) if args.csv_output else None,
                            "markdown_output": (
                                str(args.markdown_output) if args.markdown_output else None
                            ),
                        }
                    )
                )
            else:
                print(plan.to_json(), end="")
        elif args.command == "source-metrics-refresh":
            snapshots = refresh_source_metrics(
                repository,
                measurement_key=args.measurement_key,
            )
            family_performance = source_problem_family_performance(
                repository,
                measurement_key=args.measurement_key,
            )
            print(
                json.dumps(
                    {
                        "measurement_key": args.measurement_key,
                        "source_count": len(snapshots),
                        "sources": [snapshot.to_dict() for snapshot in snapshots],
                        "problem_family_performance": [
                            item.to_dict() for item in family_performance
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "source-performance":
            performance = ranked_source_performance(
                repository,
                measurement_key=args.measurement_key,
                sort_by=args.sort,
                lifecycles=tuple(
                    SourceLifecycle(value) for value in (args.lifecycle or ())
                ),
                minimum_items=args.minimum_items,
                production_ready_only=args.production_ready_only,
                limit=args.limit,
            )
            print(
                json.dumps(
                    {
                        "measurement_key": args.measurement_key,
                        "sort": args.sort,
                        "source_count": len(performance),
                        "sources": [item.to_dict() for item in performance],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "source-budget-plan":
            budget_plan = plan_source_budget(
                repository,
                measurement_key=args.measurement_key,
                total_item_budget=args.total_items,
                exploration_item_budget=args.exploration_items,
                per_source_cap=args.per_source_cap,
                minimum_performance_items=args.minimum_performance_items,
                performance_sort=args.performance_sort,
            )
            print(json.dumps(budget_plan.to_dict(), indent=2, sort_keys=True))
        elif args.command == "cost-report":
            cost_report_data = build_cost_efficiency_report(
                repository,
                provider=args.provider,
                pipeline_stage=args.pipeline_stage,
            )
            print(json.dumps(cost_report_data.to_dict(), indent=2, sort_keys=True))
        elif args.command == "cluster-exact":
            result = cluster_exact(repository, version=args.version)
            print(
                json.dumps(
                    {
                        "algorithm_version": result.algorithm_version,
                        "observation_count": result.observation_count,
                        "cluster_count": result.cluster_count,
                        "cluster_ids": result.cluster_ids,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "case-candidates":
            candidate_rows = research_case_candidates(
                repository,
                sort_by=args.sort,
                include_opened=args.include_opened,
                algorithm_version=args.algorithm_version,
            )
            if args.research_ready_only:
                candidate_rows = tuple(
                    candidate for candidate in candidate_rows if candidate.research_ready
                )
            print(
                json.dumps(
                    {
                        "sort": args.sort,
                        "candidate_count": len(candidate_rows),
                        "research_ready_count": sum(
                            candidate.research_ready for candidate in candidate_rows
                        ),
                        "candidates": [candidate.to_dict() for candidate in candidate_rows],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "create-case":
            case_id = repository.create_research_case(
                cluster_id=args.cluster_id, title=args.title
            )
            print(json.dumps({"case_id": case_id, "status": ResearchCaseStatus.OPEN.value}))
        elif args.command == "show-case":
            summary = repository.research_case_summary(args.case_id)
            print(
                json.dumps(
                    {
                        "case_id": summary.case_id,
                        "cluster_id": summary.cluster_id,
                        "title": summary.title,
                        "status": summary.status.value,
                        "requirements": [
                            {
                                "requirement": requirement.requirement.value,
                                "status": requirement.status.value,
                                "outcome": (
                                    requirement.outcome.value
                                    if requirement.outcome is not None
                                    else None
                                ),
                                "factual_claim_id": requirement.factual_claim_id,
                                "note": requirement.note,
                            }
                            for requirement in summary.requirements
                        ],
                        "validation_question_count": summary.validation_question_count,
                        "unknown_count": summary.unknown_count,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "set-dach-assessment":
            repository.upsert_dach_assessment(
                case_id=args.case_id,
                actor_equivalence=ActorEquivalence(args.actor_equivalence),
                actor_rationale=args.actor_rationale,
                workflow_equivalence=WorkflowEquivalence(args.workflow_equivalence),
                workflow_rationale=args.workflow_rationale,
                transfer_type=DachTransferType(args.transfer_type),
                transfer_rationale=args.transfer_rationale,
                local_evidence_state=LocalEvidenceState(args.local_evidence_state),
                dach_observation_count=args.dach_observation_count,
                dach_unique_author_count=args.dach_unique_author_count,
                dach_source_count=args.dach_source_count,
                buyer_structure=args.buyer_structure,
                ecosystem_dependencies=args.ecosystem_dependency,
                regulatory_dependencies=args.regulatory_dependency,
                switching_barriers=args.switching_barrier,
                localization_gaps=args.localization_gap,
            )
            print(json.dumps({"case_id": args.case_id, "dach_assessment": "updated"}))
        elif args.command == "set-stakeholder":
            repository.upsert_case_stakeholder(
                case_id=args.case_id,
                role=StakeholderRole(args.role),
                knowledge=StakeholderKnowledge(args.knowledge),
                party=args.party,
                factual_claim_id=args.claim_id,
                note=args.note,
            )
            print(
                json.dumps(
                    {
                        "case_id": args.case_id,
                        "role": args.role,
                        "knowledge": args.knowledge,
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "add-competitor":
            optional_bool = {"UNKNOWN": None, "YES": True, "NO": False}
            competitor_id = repository.upsert_competitor(
                case_id=args.case_id,
                name=args.name,
                url=args.url,
                solution_type=SolutionType(args.solution_type),
                profile_claim_id=args.profile_claim_id,
                target_customer=args.target_customer,
                market=args.market,
                pricing=args.pricing,
                pricing_model=args.pricing_model,
                features=args.feature,
                integrations=args.integration,
                dach_available=optional_bool[args.dach_available],
                dach_specific=optional_bool[args.dach_specific],
                incumbent_fix_risk=optional_bool[args.incumbent_fix_risk],
                incumbent_fix_rationale=args.incumbent_fix_rationale,
            )
            print(json.dumps({"case_id": args.case_id, "competitor_id": competitor_id}))
        elif args.command == "add-competitor-complaint":
            complaint_id = repository.add_competitor_complaint(
                competitor_id=args.competitor_id,
                complaint_type=args.complaint_type,
                statement=args.statement,
                factual_claim_ids=args.claim_id,
                affected_segment=args.affected_segment,
                frequency_observed=args.frequency_observed,
            )
            print(
                json.dumps(
                    {"competitor_id": args.competitor_id, "complaint_id": complaint_id}
                )
            )
        elif args.command == "add-counter-evidence":
            counter_evidence_id = repository.add_counter_evidence(
                case_id=args.case_id,
                evidence_type=CounterEvidenceType(args.type),
                statement=args.statement,
                factual_claim_id=args.claim_id,
            )
            print(
                json.dumps(
                    {
                        "case_id": args.case_id,
                        "counter_evidence_id": counter_evidence_id,
                    }
                )
            )
        elif args.command == "satisfy-requirement":
            if args.no_evidence_found:
                if args.claim_id is not None:
                    raise ValueError("--claim-id cannot be used with --no-evidence-found")
                repository.complete_research_requirement_without_evidence(
                    case_id=args.case_id,
                    requirement=ResearchRequirement(args.requirement),
                    note=args.note or "",
                )
            else:
                if args.claim_id is None:
                    raise ValueError("--claim-id is required unless --no-evidence-found is used")
                repository.satisfy_research_requirement(
                    case_id=args.case_id,
                    requirement=ResearchRequirement(args.requirement),
                    factual_claim_id=args.claim_id,
                    note=args.note,
                )
            print(json.dumps({"case_id": args.case_id, "requirement": args.requirement}))
        elif args.command == "add-unknown":
            unknown_id = repository.add_research_unknown(
                case_id=args.case_id,
                statement=args.statement,
            )
            print(json.dumps({"case_id": args.case_id, "unknown_id": unknown_id}))
        elif args.command == "add-validation-question":
            question_id = repository.add_validation_question(
                case_id=args.case_id,
                question=args.question,
                rationale=args.rationale,
            )
            print(json.dumps({"case_id": args.case_id, "question_id": question_id}))
        elif args.command == "transition-case":
            repository.transition_research_case(
                args.case_id, ResearchCaseStatus(args.status)
            )
            print(json.dumps({"case_id": args.case_id, "status": args.status}))
        elif args.command == "create-opportunity":
            opportunity_id = repository.create_opportunity(
                case_id=args.case_id,
                opportunity_types=tuple(
                    OpportunityType(value) for value in args.opportunity_types
                ),
                title=args.title,
            )
            opportunity = repository.opportunity(opportunity_id)
            print(
                json.dumps(
                    {
                        "opportunity_id": opportunity_id,
                        "case_id": opportunity.case_id,
                        "status": opportunity.status.value,
                        "evidence_state": opportunity.evidence_state.value,
                    }
                )
            )
        elif args.command == "show-opportunity":
            opportunity = repository.opportunity(args.opportunity_id)
            print(
                json.dumps(
                    {
                        "opportunity_id": opportunity.opportunity_id,
                        "case_id": opportunity.case_id,
                        "title": opportunity.title,
                        "status": opportunity.status.value,
                        "evidence_state": opportunity.evidence_state.value,
                        "types": [item.value for item in opportunity.opportunity_types],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "search-opportunities":
            opportunities = repository.search_opportunities(
                query=args.query,
                status=(OpportunityStatus(args.status) if args.status else None),
                evidence_state=(
                    EvidenceState(args.evidence_state) if args.evidence_state else None
                ),
                opportunity_type=(
                    OpportunityType(args.type) if args.type else None
                ),
                saved_only=args.saved_only,
                limit=args.limit,
            )
            saved_ids = {
                item.opportunity.opportunity_id
                for item in repository.saved_opportunities()
            }
            print(
                json.dumps(
                    {
                        "result_count": len(opportunities),
                        "opportunities": [
                            {
                                "opportunity_id": item.opportunity_id,
                                "case_id": item.case_id,
                                "title": item.title,
                                "status": item.status.value,
                                "evidence_state": item.evidence_state.value,
                                "types": [value.value for value in item.opportunity_types],
                                "saved": item.opportunity_id in saved_ids,
                            }
                            for item in opportunities
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "save-opportunity":
            saved = repository.save_opportunity(
                args.opportunity_id, note=args.note
            )
            print(
                json.dumps(
                    {
                        "opportunity_id": saved.opportunity.opportunity_id,
                        "saved": True,
                        "note": saved.note,
                        "saved_at": saved.saved_at,
                        "updated_at": saved.updated_at,
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "unsave-opportunity":
            removed = repository.unsave_opportunity(args.opportunity_id)
            print(
                json.dumps(
                    {"opportunity_id": args.opportunity_id, "removed": removed},
                    sort_keys=True,
                )
            )
        elif args.command == "saved-opportunities":
            saved_rows = repository.saved_opportunities()
            print(
                json.dumps(
                    {
                        "saved_count": len(saved_rows),
                        "opportunities": [
                            {
                                "opportunity_id": item.opportunity.opportunity_id,
                                "case_id": item.opportunity.case_id,
                                "title": item.opportunity.title,
                                "status": item.opportunity.status.value,
                                "evidence_state": item.opportunity.evidence_state.value,
                                "types": [
                                    value.value
                                    for value in item.opportunity.opportunity_types
                                ],
                                "note": item.note,
                                "saved_at": item.saved_at,
                                "updated_at": item.updated_at,
                            }
                            for item in saved_rows
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "transition-opportunity":
            repository.transition_opportunity(
                args.opportunity_id, OpportunityStatus(args.status)
            )
            print(json.dumps({"opportunity_id": args.opportunity_id, "status": args.status}))
        elif args.command == "report":
            markdown = build_opportunity_report(repository, args.opportunity_id).to_markdown(
                include_unapproved_excerpts=args.include_unapproved_excerpts,
                language=args.language,
            )
            if args.output:
                args.output.write_text(markdown, encoding="utf-8")
                print(
                    json.dumps(
                        {"opportunity_id": args.opportunity_id, "output": str(args.output)}
                    )
                )
            else:
                print(markdown, end="")
    finally:
        repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

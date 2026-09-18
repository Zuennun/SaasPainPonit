#!/usr/bin/env python3
"""Rebuild the reviewed SEO-reporting research case from stored captures.

This is an auditable reference workflow, not a general-purpose classifier.  It
records the human review decisions that connect the captured source excerpts to
the research case.  Database rows are resolved through stable external IDs and
semantic keys rather than environment-specific integer IDs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from problem_intelligence.clustering import cluster_exact
from problem_intelligence.connectors import ResearchJsonlCapture
from problem_intelligence.domain import (
    ActorEquivalence,
    ClaimKind,
    CompetitorEvidenceRole,
    CounterEvidenceType,
    DachTransferType,
    EvidenceRange,
    EvidenceScope,
    LocalEvidenceState,
    OpportunityStatus,
    OpportunityType,
    ProblemFamily,
    ProblemType,
    ResearchCaseStatus,
    ResearchRequirement,
    SolutionType,
    StakeholderKnowledge,
    StakeholderRole,
    WorkaroundType,
    WorkflowEquivalence,
)
from problem_intelligence.ingestion import ingest_research_capture
from problem_intelligence.reporting import build_opportunity_report
from problem_intelligence.repository import IntegrityError, Repository

CASE_TITLE = "Manual data entry in recurring SEO reports"
GLOBAL_ITEM = "reddit:submission:hp9l64"
LOCAL_ITEM = "seo-tool-checkliste-2025#reporting-check-7"
GOOGLE_ITEM = "search-console-analytics-looker-studio#monitor"
VENDOR_PRODUCT_ITEM = "seo-reporting-page#automated-alternative"


def _single_id(repository: Repository, query: str, parameters: tuple[object, ...]) -> int:
    rows = repository.connection.execute(query, parameters).fetchall()
    if len(rows) != 1:
        raise IntegrityError(f"expected exactly one row, found {len(rows)}")
    return int(rows[0]["id"])


def _source_item_id(repository: Repository, external_id: str) -> int:
    return _single_id(
        repository,
        "SELECT id FROM source_items WHERE external_id = ?",
        (external_id,),
    )


def _observation_id(repository: Repository, external_id: str, version: str) -> int:
    return _single_id(
        repository,
        """SELECT po.id FROM problem_observations po
           JOIN source_items si ON si.id = po.source_item_id
           WHERE si.external_id = ? AND po.extraction_version = ?""",
        (external_id, version),
    )


def _observation_evidence_id(repository: Repository, observation_id: int) -> int:
    return _single_id(
        repository,
        "SELECT id FROM evidence_spans WHERE observation_id = ?",
        (observation_id,),
    )


def _item_evidence(
    repository: Repository, external_id: str, scope: EvidenceScope
) -> int:
    item_id = _source_item_id(repository, external_id)
    row = repository.connection.execute(
        "SELECT raw_text FROM source_items WHERE id = ?", (item_id,)
    ).fetchone()
    assert row is not None
    return repository.add_evidence_span(
        source_item_id=item_id,
        evidence_range=EvidenceRange(0, len(str(row["raw_text"]))),
        evidence_scope=scope,
    )


def _fact(
    repository: Repository,
    *,
    text: str,
    evidence_ids: tuple[int, ...],
    observation_id: int | None = None,
) -> int:
    rows = repository.connection.execute(
        "SELECT id FROM claims WHERE claim_kind = 'FACT' AND text = ? AND observation_id IS ?",
        (text, observation_id),
    ).fetchall()
    if len(rows) > 1:
        raise IntegrityError(f"duplicate factual claim: {text}")
    if rows:
        claim_id = int(rows[0]["id"])
        actual = {
            int(row["evidence_span_id"])
            for row in repository.connection.execute(
                "SELECT evidence_span_id FROM claim_evidence WHERE claim_id = ?", (claim_id,)
            )
        }
        if actual != set(evidence_ids):
            raise IntegrityError(f"existing factual claim has different evidence: {text}")
        return claim_id
    return repository.create_claim(
        claim_kind=ClaimKind.FACT,
        text=text,
        observation_id=observation_id,
        evidence_span_ids=evidence_ids,
    )


def _ensure_context_revision(repository: Repository, observation_id: int) -> None:
    row = repository.connection.execute(
        "SELECT context FROM problem_observations WHERE id = ?", (observation_id,)
    ).fetchone()
    assert row is not None
    if row["context"] == "while producing SEO reports":
        return
    if row["context"] is not None:
        raise IntegrityError("global SEO observation has an unexpected context")
    repository.revise_observation_field(
        observation_id=observation_id,
        field_name="context",
        value="while producing SEO reports",
        reason="The evidence explicitly ties manual data entry to reporting.",
        evidence_span_id=_observation_evidence_id(repository, observation_id),
        revision_version="manual-context-review-v1",
    )


def _ensure_local_observation(repository: Repository) -> tuple[int, int]:
    item_id = _source_item_id(repository, LOCAL_ITEM)
    existing = repository.connection.execute(
        """SELECT id FROM problem_observations
           WHERE source_item_id = ? AND extraction_version = 'manual-research-seo-v1'""",
        (item_id,),
    ).fetchall()
    if len(existing) > 1:
        raise IntegrityError("duplicate reviewed local SEO observations")
    if existing:
        observation_id = int(existing[0]["id"])
        return observation_id, _observation_evidence_id(repository, observation_id)

    row = repository.connection.execute(
        "SELECT raw_text FROM source_items WHERE id = ?", (item_id,)
    ).fetchone()
    assert row is not None
    observation_id = repository.create_observation(
        source_item_id=item_id,
        problem_type=ProblemType.WORKFLOW_GAP,
        problem_family=ProblemFamily.REPORTING,
        ontology_version="problem-ontology-v1",
        evidence_scope=EvidenceScope.DACH,
        problem=(
            "A German vendor checklist describes monthly SEO reports assembled "
            "manually from multiple tools."
        ),
        extraction_version="manual-research-seo-v1",
        fields={
            "industry": "SEO services",
            "job_to_be_done": "assemble a monthly SEO report",
            "context": "monthly SEO reporting",
            "current_workaround": "manually copy information from multiple tools",
            "country_code": "DE",
            "language_code": "de",
        },
    )
    evidence_id = repository.add_evidence_span(
        source_item_id=item_id,
        observation_id=observation_id,
        evidence_range=EvidenceRange(0, len(str(row["raw_text"]))),
        evidence_scope=EvidenceScope.DACH,
    )
    repository.add_workaround_signal(
        observation_id=observation_id,
        evidence_span_id=evidence_id,
        workaround_type=WorkaroundType.MULTIPLE_TOOLS,
        description="Manually copy information from multiple tools into a monthly report.",
    )
    return observation_id, evidence_id


def _ensure_case(repository: Repository, cluster_id: int) -> int:
    rows = repository.connection.execute(
        "SELECT id, cluster_id FROM research_cases WHERE title = ?", (CASE_TITLE,)
    ).fetchall()
    if len(rows) > 1:
        raise IntegrityError("duplicate SEO reporting research cases")
    if rows:
        if int(rows[0]["cluster_id"]) != cluster_id:
            raise IntegrityError("existing SEO reporting case points to another cluster")
        return int(rows[0]["id"])
    return repository.create_research_case(cluster_id=cluster_id, title=CASE_TITLE)


def rebuild(database: Path, capture: Path, output: Path) -> tuple[int, int]:
    repository = Repository(database)
    try:
        repository.initialize()
        ingest_research_capture(repository, ResearchJsonlCapture(capture))

        global_observation = _observation_id(
            repository, GLOBAL_ITEM, "manual-reviewed-reddit-real-v1"
        )
        _ensure_context_revision(repository, global_observation)
        _, local_evidence = _ensure_local_observation(repository)
        cluster_exact(repository)
        cluster_id = _single_id(
            repository,
            "SELECT cluster_id AS id FROM cluster_members WHERE observation_id = ?",
            (global_observation,),
        )
        case_id = _ensure_case(repository, cluster_id)

        global_evidence = _observation_evidence_id(repository, global_observation)
        google_evidence = _item_evidence(repository, GOOGLE_ITEM, EvidenceScope.GLOBAL)
        product_evidence = _item_evidence(
            repository, VENDOR_PRODUCT_ITEM, EvidenceScope.DACH
        )
        workaround_claim = _fact(
            repository,
            text=(
                "One SEO practitioner reports that recurring reporting involves "
                "manual data entry."
            ),
            observation_id=global_observation,
            evidence_ids=(global_evidence,),
        )
        google_claim = _fact(
            repository,
            text=(
                "Google documents a Looker Studio view combining Search Console and "
                "Google Analytics organic-search data."
            ),
            evidence_ids=(google_evidence,),
        )
        local_claim = _fact(
            repository,
            text=(
                "A German vendor-authored checklist describes monthly SEO reports "
                "containing information manually copied from multiple tools."
            ),
            evidence_ids=(local_evidence,),
        )
        product_claim = _fact(
            repository,
            text="A German vendor markets automated, individually tailored SEO reports.",
            evidence_ids=(product_evidence,),
        )
        counter_claim = _fact(
            repository,
            text=(
                "Existing alternatives already cover parts of the workflow: Google "
                "documents a combined dashboard and a German vendor markets automated reports."
            ),
            evidence_ids=(google_evidence, product_evidence),
        )

        repository.upsert_competitor(
            case_id=case_id,
            name="Google Looker Studio",
            solution_type=SolutionType.INDIRECT_SOFTWARE,
            profile_claim_id=google_claim,
            url="https://developers.google.com/search/docs/monitor-debug/google-analytics-search-console",
            target_customer="site owners and SEO practitioners",
            market="Global",
            features=("Combined organic-search visualization",),
            integrations=("Google Search Console", "Google Analytics"),
            dach_specific=False,
            incumbent_fix_risk=True,
            incumbent_fix_rationale=(
                "The documented dashboard already covers combined monitoring for two "
                "core data sources."
            ),
        )
        repository.upsert_competitor(
            case_id=case_id,
            name="Performance Suite",
            solution_type=SolutionType.DIRECT_SOFTWARE,
            profile_claim_id=product_claim,
            url="https://www.seoagentur.de/seo-reporting/",
            target_customer="companies and SEO agencies",
            market="Germany",
            features=("Automated tailored SEO reports",),
            dach_available=True,
            dach_specific=True,
            incumbent_fix_risk=True,
            incumbent_fix_rationale=(
                "The vendor explicitly markets automation of the observed reporting workflow."
            ),
            additional_evidence=((CompetitorEvidenceRole.FEATURE, product_claim),),
        )
        repository.add_counter_evidence(
            case_id=case_id,
            evidence_type=CounterEvidenceType.FEATURE_ALREADY_EXISTS,
            statement=(
                "Existing dashboards and automated reporting products already address "
                "substantial parts of the workflow."
            ),
            factual_claim_id=counter_claim,
        )
        repository.upsert_dach_assessment(
            case_id=case_id,
            actor_equivalence=ActorEquivalence.UNCLEAR,
            actor_rationale=(
                "The local material is vendor-authored and does not independently identify "
                "affected German practitioners."
            ),
            workflow_equivalence=WorkflowEquivalence.DIRECT,
            workflow_rationale=(
                "The German checklist describes monthly SEO reporting and manual copying "
                "from multiple tools."
            ),
            transfer_type=DachTransferType.WEAK_LOCAL_EVIDENCE,
            transfer_rationale=(
                "The workflow appears locally relevant, but the only local signal is "
                "vendor-authored rather than independent user testimony."
            ),
            local_evidence_state=LocalEvidenceState.SINGLE_LOCAL_SIGNAL,
            dach_observation_count=1,
            dach_unique_author_count=1,
            dach_source_count=1,
            buyer_structure=(
                "End user: SEO practitioner or agency analyst; buyer and decision maker: unknown."
            ),
            switching_barriers=(
                "Existing configurable dashboards or agency workflows may already be sufficient.",
            ),
        )
        repository.upsert_case_stakeholder(
            case_id=case_id,
            role=StakeholderRole.END_USER,
            knowledge=StakeholderKnowledge.KNOWN,
            party="SEO practitioner",
            factual_claim_id=workaround_claim,
            note="The original practitioner signal identifies the affected end user.",
        )
        for role, note in (
            (
                StakeholderRole.BUYER,
                "No evidence identifies who holds the purchasing budget.",
            ),
            (
                StakeholderRole.DECISION_MAKER,
                "No evidence identifies who approves reporting-tool adoption.",
            ),
            (
                StakeholderRole.GATEKEEPER,
                "No evidence identifies a technical, procurement, or agency gatekeeper.",
            ),
            (
                StakeholderRole.INFLUENCER,
                "No evidence identifies an additional adoption influencer.",
            ),
        ):
            repository.upsert_case_stakeholder(
                case_id=case_id,
                role=role,
                knowledge=StakeholderKnowledge.UNKNOWN,
                note=note,
            )

        requirements = (
            (
                ResearchRequirement.WORKAROUND_RESEARCH,
                workaround_claim,
                "The original individual signal reports manual entry during reporting.",
            ),
            (
                ResearchRequirement.COMPETITION,
                google_claim,
                "Two structured alternatives are recorded; pricing remains unverified.",
            ),
            (
                ResearchRequirement.DACH_TRANSFER,
                local_claim,
                "One German vendor-authored workflow signal exists; independent local "
                "recurrence is not established.",
            ),
            (
                ResearchRequirement.COUNTER_EVIDENCE,
                counter_claim,
                "Existing products materially weaken a broad unmet-need interpretation.",
            ),
        )
        for requirement, claim_id, note in requirements:
            repository.satisfy_research_requirement(
                case_id=case_id,
                requirement=requirement,
                factual_claim_id=claim_id,
                note=note,
            )

        unknowns = (
            "Independent DACH user confirmation is missing.",
            "Recurrence beyond the original global signal is unknown.",
            "No payment evidence from affected practitioners was found.",
            "The buyer, decision maker, and switching willingness are unknown.",
            "Production display rights for the German vendor excerpts require review.",
        )
        for statement in unknowns:
            repository.add_research_unknown(case_id=case_id, statement=statement)
        questions = (
            (
                "How many German SEO practitioners still assemble recurring reports manually?",
                "Establish local recurrence using independent practitioner evidence.",
            ),
            (
                "Which data sources still require manual transfer despite Looker Studio "
                "or existing tools?",
                "Narrow the unresolved workflow rather than assuming all reporting is manual.",
            ),
            (
                "Why are existing dashboards and automated reporting products insufficient?",
                "Test whether the observed workaround reflects a real product gap or "
                "configuration friction.",
            ),
            (
                "Who pays for reporting automation and what do they currently spend?",
                "No payment evidence is present in the captured practitioner signal.",
            ),
            (
                "How much time is spent per client and reporting cycle?",
                "The current global signal is qualitative rather than quantified.",
            ),
        )
        for question, rationale in questions:
            repository.add_validation_question(
                case_id=case_id, question=question, rationale=rationale
            )

        case_status = repository.connection.execute(
            "SELECT status FROM research_cases WHERE id = ?", (case_id,)
        ).fetchone()
        assert case_status is not None
        if case_status["status"] != ResearchCaseStatus.COMPLETE.value:
            for status in (
                ResearchCaseStatus.INVESTIGATING,
                ResearchCaseStatus.REVIEW,
                ResearchCaseStatus.COMPLETE,
            ):
                repository.transition_research_case(case_id, status)

        opportunity = repository.connection.execute(
            "SELECT id FROM opportunities WHERE case_id = ?", (case_id,)
        ).fetchone()
        if opportunity is None:
            opportunity_id = repository.create_opportunity(
                case_id=case_id,
                opportunity_types=(
                    OpportunityType.STRONG_SINGLE_SIGNAL,
                    OpportunityType.WORKFLOW_GAP,
                ),
            )
            repository.transition_opportunity(
                opportunity_id, OpportunityStatus.REPORT_READY
            )
        else:
            opportunity_id = int(opportunity["id"])
            record = repository.opportunity(opportunity_id)
            if record.status is not OpportunityStatus.REPORT_READY:
                repository.transition_opportunity(
                    opportunity_id, OpportunityStatus.REPORT_READY
                )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            build_opportunity_report(repository, opportunity_id).to_markdown(),
            encoding="utf-8",
        )
        return case_id, opportunity_id
    finally:
        repository.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--capture",
        type=Path,
        default=Path("data/research/seo_reporting_research_v1.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("exports/seo_reporting_opportunity_v1.md")
    )
    arguments = parser.parse_args()
    case_id, opportunity_id = rebuild(
        arguments.database, arguments.capture, arguments.output
    )
    print(f"rebuilt case_id={case_id} opportunity_id={opportunity_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

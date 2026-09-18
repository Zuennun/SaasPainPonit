import sqlite3
import unittest

from problem_intelligence.clustering import cluster_exact
from problem_intelligence.domain import (
    ActorEquivalence,
    ClaimKind,
    CounterEvidenceType,
    DachTransferType,
    EvidenceRange,
    EvidenceScope,
    EvidenceState,
    LocalEvidenceState,
    OpportunityStatus,
    OpportunityType,
    ProblemType,
    ResearchCaseStatus,
    ResearchRequirement,
    SolutionType,
    WorkflowEquivalence,
)
from problem_intelligence.reporting import build_opportunity_report
from problem_intelligence.repository import IntegrityError, Repository


class ReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        global_source = self.repository.upsert_source(
            source_type="forum",
            name="Global Forum",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        dach_source = self.repository.upsert_source(
            source_type="interview",
            name="DACH Interview",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        self.global_text = (
            "Teams manually reconcile every invoice. Existing tools solve some cases."
        )
        self.dach_text = (
            "In Germany existing automation handles standard invoices, "
            "but exceptions take two hours each week."
        )
        self.global_item = self.repository.upsert_source_item(
            source_id=global_source,
            external_id="global-1",
            raw_text=self.global_text,
        )
        self.dach_item = self.repository.upsert_source_item(
            source_id=dach_source,
            external_id="dach-1",
            raw_text=self.dach_text,
            country_code="DE",
        )
        observation_id = self.repository.create_observation(
            source_item_id=self.global_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Teams manually reconcile invoices.",
            extraction_version="manual-v1",
            fields={
                "actor": "finance teams",
                "job_to_be_done": "reconcile invoices",
                "context": "period close",
            },
        )
        global_start = self.global_text.index("manually reconcile every invoice")
        self.global_evidence = self.repository.add_evidence_span(
            source_item_id=self.global_item,
            observation_id=observation_id,
            evidence_range=EvidenceRange(
                global_start, global_start + len("manually reconcile every invoice")
            ),
            evidence_scope=EvidenceScope.GLOBAL,
        )
        self.cluster_id = cluster_exact(self.repository).cluster_ids[0]

    def tearDown(self) -> None:
        self.repository.close()

    def test_opportunity_requires_completed_research_case(self) -> None:
        case_id = self.repository.create_research_case(
            cluster_id=self.cluster_id, title="Manual invoice reconciliation"
        )
        with self.assertRaises(IntegrityError):
            self.repository.create_opportunity(
                case_id=case_id,
                opportunity_types=(OpportunityType.WORKFLOW_GAP,),
            )

    def test_report_separates_global_and_dach_evidence(self) -> None:
        case_id = self.repository.create_research_case(
            cluster_id=self.cluster_id, title="Manual invoice reconciliation"
        )
        competition_claim = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="Existing tools solve some cases.",
            evidence_span_ids=[self.global_evidence],
        )
        dach_excerpt = "existing automation handles standard invoices"
        dach_start = self.dach_text.index(dach_excerpt)
        dach_evidence = self.repository.add_evidence_span(
            source_item_id=self.dach_item,
            evidence_range=EvidenceRange(
                dach_start, dach_start + len(dach_excerpt)
            ),
            evidence_scope=EvidenceScope.DACH,
        )
        dach_problem_excerpt = "exceptions take two hours each week"
        dach_problem_start = self.dach_text.index(dach_problem_excerpt)
        dach_observation = self.repository.create_observation(
            source_item_id=self.dach_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Teams manually reconcile invoices.",
            extraction_version="manual-v1",
            fields={
                "actor": "finance teams",
                "job_to_be_done": "reconcile invoices",
                "context": "period close",
            },
        )
        self.repository.add_evidence_span(
            source_item_id=self.dach_item,
            observation_id=dach_observation,
            evidence_range=EvidenceRange(
                dach_problem_start, dach_problem_start + len(dach_problem_excerpt)
            ),
            evidence_scope=EvidenceScope.DACH,
        )
        cluster_exact(self.repository)
        counter_claim = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="Existing automation handles standard invoices in the DACH example.",
            evidence_span_ids=[dach_evidence],
        )
        competitor_id = self.repository.upsert_competitor(
            case_id=case_id,
            name="Invoice Automator",
            url="https://example.test/invoice-automator",
            solution_type=SolutionType.DIRECT_SOFTWARE,
            profile_claim_id=competition_claim,
            target_customer="finance teams",
            market="Global with DACH availability",
            pricing="Price not stated in the evidence",
            features=("Standard invoice automation",),
            integrations=("Accounting system",),
            dach_available=True,
            dach_specific=False,
            incumbent_fix_risk=True,
            incumbent_fix_rationale="The incumbent already handles standard invoices.",
        )
        self.repository.add_competitor_complaint(
            competitor_id=competitor_id,
            complaint_type="EXCEPTION_GAP",
            statement="Invoice exceptions remain manual.",
            affected_segment="finance teams with non-standard invoices",
            frequency_observed="single local signal",
            factual_claim_ids=[counter_claim],
        )
        self.repository.add_counter_evidence(
            case_id=case_id,
            evidence_type=CounterEvidenceType.FEATURE_ALREADY_EXISTS,
            statement="The incumbent handles standard invoices.",
            factual_claim_id=counter_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=case_id,
            requirement=ResearchRequirement.COMPETITION,
            factual_claim_id=competition_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=case_id,
            requirement=ResearchRequirement.COUNTER_EVIDENCE,
            factual_claim_id=counter_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=case_id,
            requirement=ResearchRequirement.WORKAROUND_RESEARCH,
            factual_claim_id=competition_claim,
            note="The same evidence documents the existing workflow.",
        )
        self.repository.upsert_dach_assessment(
            case_id=case_id,
            actor_equivalence=ActorEquivalence.SIMILAR,
            actor_rationale="The DACH source describes a comparable finance team.",
            workflow_equivalence=WorkflowEquivalence.LOCALIZED,
            workflow_rationale="Standard invoices are automated, while exceptions remain.",
            transfer_type=DachTransferType.LOCALIZATION_REQUIRED,
            transfer_rationale="The core problem transfers with local workflow differences.",
            local_evidence_state=LocalEvidenceState.SINGLE_LOCAL_SIGNAL,
            dach_observation_count=1,
            dach_unique_author_count=1,
            dach_source_count=1,
            buyer_structure="End user: finance team; buyer: unknown",
            ecosystem_dependencies=("German accounting stack",),
            regulatory_dependencies=("German invoice retention rules",),
            switching_barriers=("Integration dependency",),
            localization_gaps=("Local workflow",),
        )
        self.repository.complete_research_requirement_without_evidence(
            case_id=case_id,
            requirement=ResearchRequirement.DACH_TRANSFER,
            note="No broader DACH transfer evidence was found in this fixture.",
        )
        self.repository.add_research_unknown(
            case_id=case_id,
            statement="The buyer for exception-handling software is unknown.",
        )
        self.repository.add_validation_question(
            case_id=case_id,
            question="Which reconciliation exceptions remain unsolved?",
            rationale="Avoid assuming the entire workflow is underserved.",
        )
        self.repository.transition_research_case(case_id, ResearchCaseStatus.INVESTIGATING)
        self.repository.transition_research_case(case_id, ResearchCaseStatus.REVIEW)
        self.repository.transition_research_case(case_id, ResearchCaseStatus.COMPLETE)

        opportunity_id = self.repository.create_opportunity(
            case_id=case_id,
            opportunity_types=(
                OpportunityType.WORKFLOW_GAP,
                OpportunityType.LOCALIZATION_GAP,
            ),
        )
        with self.assertRaises(IntegrityError):
            build_opportunity_report(self.repository, opportunity_id)
        self.repository.connection.execute(
            "UPDATE opportunities SET evidence_state = 'RECURRING' WHERE id = ?",
            (opportunity_id,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE opportunities SET status = 'REPORT_READY' WHERE id = ?",
                (opportunity_id,),
            )
        self.repository.transition_opportunity(
            opportunity_id, OpportunityStatus.REPORT_READY
        )

        report = build_opportunity_report(self.repository, opportunity_id)
        markdown = report.to_markdown(language="en")

        self.assertEqual(report.evidence_state, EvidenceState.CROSS_MARKET)
        self.assertIn("`WORKFLOW_GAP`", markdown)
        self.assertIn("`LOCALIZATION_GAP`", markdown)
        self.assertIn("## Problem", markdown)
        self.assertIn("Teams manually reconcile invoices.", markdown)
        self.assertIn("## Who experiences it?", markdown)
        self.assertIn("finance teams", markdown)
        self.assertIn("## When does it happen?", markdown)
        self.assertIn("period close", markdown)
        self.assertIn("## Current workflow", markdown)
        self.assertIn("reconcile invoices", markdown)
        self.assertIn("## Current workaround", markdown)
        self.assertIn("## Impact", markdown)
        self.assertIn("## Payment evidence", markdown)
        self.assertIn("Unknown; no evidence recorded.", markdown)
        self.assertIn("## Global evidence", markdown)
        self.assertIn("## DACH evidence", markdown)
        self.assertIn("- Problem observations: 1", markdown)
        self.assertIn("- Evidence spans: 2 across 1 cited item", markdown)
        self.assertIn("- Sources (1): DACH Interview", markdown)
        self.assertIn("- Countries: DE", markdown)
        self.assertIn(
            "Publication window: Unknown; source publication dates not recorded.",
            markdown,
        )
        self.assertIn("## Original evidence", markdown)
        self.assertIn("## DACH relevance", markdown)
        self.assertIn("## Existing solutions", markdown)
        self.assertIn("## What existing solutions appear to miss", markdown)
        self.assertIn("Invoice Automator", markdown)
        self.assertIn("EXCEPTION_GAP", markdown)
        self.assertIn("## Local solutions", markdown)
        self.assertIn("## Local dependencies", markdown)
        self.assertIn("German invoice retention rules", markdown)
        self.assertIn("This report is not legal advice.", markdown)
        self.assertIn("## Switching barriers", markdown)
        self.assertIn("## What speaks against this opportunity?", markdown)
        self.assertIn("FEATURE_ALREADY_EXISTS", markdown)
        self.assertIn("LOCALIZATION_REQUIRED", markdown)
        self.assertIn("German accounting stack", markdown)
        self.assertIn("manually reconcile every invoice", markdown)
        self.assertIn("existing automation handles standard invoices", markdown)
        self.assertIn("## What we do not know", markdown)
        self.assertIn("buyer for exception-handling software is unknown", markdown)
        self.assertIn("NO_EVIDENCE_FOUND", markdown)
        self.assertIn("Which reconciliation exceptions remain unsolved?", markdown)
        self.assertIn("not a build recommendation", markdown)
        self.assertLess(
            markdown.index("## Global evidence"), markdown.index("## Original evidence")
        )
        self.assertLess(markdown.index("## Original evidence"), markdown.index("## Impact"))
        self.assertLess(markdown.index("## DACH relevance"), markdown.index("## DACH evidence"))

        self.repository.connection.execute(
            "UPDATE sources SET commercial_use_status = 'REVIEW_REQUIRED' WHERE id = ?",
            (self.repository.connection.execute(
                "SELECT source_id FROM source_items WHERE id = ?", (self.global_item,)
            ).fetchone()[0],),
        )
        safe_markdown = build_opportunity_report(
            self.repository, opportunity_id
        ).to_markdown(language="en")
        self.assertIn("excerpt withheld pending source-use review", safe_markdown)
        self.assertNotIn("manually reconcile every invoice", safe_markdown)
        internal_markdown = build_opportunity_report(
            self.repository, opportunity_id
        ).to_markdown(include_unapproved_excerpts=True, language="en")
        self.assertIn("manually reconcile every invoice", internal_markdown)
        self.assertIn("Internal review view", internal_markdown)

        german_markdown = build_opportunity_report(
            self.repository, opportunity_id
        ).to_markdown()
        self.assertIn("## Wer ist betroffen?", german_markdown)
        self.assertIn("## Globale Evidenz", german_markdown)
        self.assertIn("## Originalbelege", german_markdown)
        self.assertIn("## Lokale Lösungen", german_markdown)
        self.assertIn("## Lokale Abhängigkeiten", german_markdown)
        self.assertIn("keine Rechtsberatung", german_markdown)
        self.assertIn("## Was wir nicht wissen", german_markdown)
        self.assertIn("keine Bauempfehlung", german_markdown)
        self.assertIn("existing automation handles standard invoices", german_markdown)


if __name__ == "__main__":
    unittest.main()

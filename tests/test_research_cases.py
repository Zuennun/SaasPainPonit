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
    LocalEvidenceState,
    ProblemType,
    ResearchCaseStatus,
    ResearchRequirement,
    SolutionType,
    WorkflowEquivalence,
)
from problem_intelligence.repository import IntegrityError, Repository


class ResearchCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        source_id = self.repository.upsert_source(source_type="fixture", name="case research")
        self.text = (
            "Teams manually reconcile invoices; "
            "some report that existing tools already work."
        )
        self.item_id = self.repository.upsert_source_item(
            source_id=source_id,
            external_id="one",
            raw_text=self.text,
        )
        observation_id = self.repository.create_observation(
            source_item_id=self.item_id,
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
        problem_excerpt = "Teams manually reconcile invoices"
        self.repository.add_evidence_span(
            source_item_id=self.item_id,
            observation_id=observation_id,
            evidence_range=EvidenceRange(0, len(problem_excerpt)),
            evidence_scope=EvidenceScope.GLOBAL,
        )
        cluster = cluster_exact(self.repository)
        self.assertEqual(cluster.cluster_count, 1)
        self.cluster_id = cluster.cluster_ids[0]
        self.case_id = self.repository.create_research_case(
            cluster_id=self.cluster_id,
            title="Manual invoice reconciliation",
        )
        self.assertGreater(observation_id, 0)

    def test_new_case_summary_exposes_pending_completion_requirements(self) -> None:
        summary = self.repository.research_case_summary(self.case_id)

        self.assertEqual(summary.status, ResearchCaseStatus.OPEN)
        self.assertEqual(summary.validation_question_count, 0)
        self.assertEqual(
            {item.requirement for item in summary.requirements},
            set(ResearchRequirement),
        )
        self.assertTrue(all(item.status.value == "PENDING" for item in summary.requirements))
        self.assertEqual(summary.unknown_count, 0)

    def tearDown(self) -> None:
        self.repository.close()

    def factual_claim(self, excerpt: str, text: str) -> int:
        start = self.text.index(excerpt)
        evidence_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(start, start + len(excerpt)),
            evidence_scope=EvidenceScope.GLOBAL,
        )
        return self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text=text,
            evidence_span_ids=[evidence_id],
        )

    def add_empty_dach_assessment(self) -> None:
        self.repository.upsert_dach_assessment(
            case_id=self.case_id,
            actor_equivalence=ActorEquivalence.UNCLEAR,
            actor_rationale="No DACH-specific actor evidence was found.",
            workflow_equivalence=WorkflowEquivalence.UNKNOWN,
            workflow_rationale="The DACH workflow has not been established.",
            transfer_type=DachTransferType.UNKNOWN,
            transfer_rationale="There is not enough local evidence to classify transfer.",
            local_evidence_state=LocalEvidenceState.NONE_FOUND,
            dach_observation_count=0,
            dach_unique_author_count=0,
            dach_source_count=0,
        )

    def add_competitor(self, profile_claim_id: int) -> int:
        return self.repository.upsert_competitor(
            case_id=self.case_id,
            name="Existing invoice tool",
            solution_type=SolutionType.DIRECT_SOFTWARE,
            profile_claim_id=profile_claim_id,
            target_customer="finance teams",
            market="global",
        )

    def test_completion_requires_competition_and_counter_evidence(self) -> None:
        self.repository.transition_research_case(
            self.case_id, ResearchCaseStatus.INVESTIGATING
        )
        self.repository.transition_research_case(self.case_id, ResearchCaseStatus.REVIEW)

        with self.assertRaises(IntegrityError):
            self.repository.transition_research_case(self.case_id, ResearchCaseStatus.COMPLETE)

        competition_claim = self.factual_claim(
            "existing tools already work", "Some sources report that existing tools work."
        )
        counter_claim = self.factual_claim(
            "some report", "The source includes evidence against a universal unmet need."
        )
        workaround_claim = self.factual_claim(
            "manually reconcile invoices", "Teams use a manual reconciliation workflow."
        )
        self.add_competitor(competition_claim)
        self.repository.add_counter_evidence(
            case_id=self.case_id,
            evidence_type=CounterEvidenceType.FEATURE_ALREADY_EXISTS,
            statement="Some sources report that existing tools already work.",
            factual_claim_id=counter_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.WORKAROUND_RESEARCH,
            factual_claim_id=workaround_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.COMPETITION,
            factual_claim_id=competition_claim,
        )
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.COUNTER_EVIDENCE,
            factual_claim_id=counter_claim,
        )
        self.add_empty_dach_assessment()
        self.repository.complete_research_requirement_without_evidence(
            case_id=self.case_id,
            requirement=ResearchRequirement.DACH_TRANSFER,
            note="The controlled fixture contains no DACH-local market evidence.",
        )
        self.repository.add_research_unknown(
            case_id=self.case_id,
            statement="The frequency of manual exceptions is unknown.",
        )
        self.repository.add_validation_question(
            case_id=self.case_id,
            question="How often does reconciliation require manual correction?",
        )
        self.repository.transition_research_case(self.case_id, ResearchCaseStatus.COMPLETE)

        status = self.repository.connection.execute(
            "SELECT status FROM research_cases WHERE id = ?", (self.case_id,)
        ).fetchone()[0]
        self.assertEqual(status, "COMPLETE")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "DELETE FROM dach_assessments WHERE case_id = ?", (self.case_id,)
            )

    def test_no_evidence_outcome_requires_note_and_no_claim(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a note"):
            self.repository.complete_research_requirement_without_evidence(
                case_id=self.case_id,
                requirement=ResearchRequirement.DACH_TRANSFER,
                note=" ",
            )
        self.add_empty_dach_assessment()
        self.repository.complete_research_requirement_without_evidence(
            case_id=self.case_id,
            requirement=ResearchRequirement.DACH_TRANSFER,
            note="No local evidence was found in the controlled search.",
        )
        summary = self.repository.research_case_summary(self.case_id)
        dach = next(
            item
            for item in summary.requirements
            if item.requirement is ResearchRequirement.DACH_TRANSFER
        )
        self.assertEqual(dach.outcome.value, "NO_EVIDENCE_FOUND")
        self.assertIsNone(dach.factual_claim_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """UPDATE research_passes
                   SET status = 'SATISFIED', outcome = 'NO_EVIDENCE_FOUND', note = NULL
                   WHERE case_id = ? AND pass_type = 'WORKAROUND_RESEARCH'""",
                (self.case_id,),
            )

    def test_non_factual_claim_cannot_satisfy_requirement(self) -> None:
        analysis_id = self.repository.create_claim(
            claim_kind=ClaimKind.ANALYSIS,
            text="This market might already be served.",
        )
        with self.assertRaises(IntegrityError):
            self.add_competitor(analysis_id)
        with self.assertRaises(IntegrityError):
            self.repository.satisfy_research_requirement(
                case_id=self.case_id,
                requirement=ResearchRequirement.COMPETITION,
                factual_claim_id=analysis_id,
            )
        self.repository.connection.execute(
            """DELETE FROM research_passes
               WHERE case_id = ? AND pass_type = 'COMPETITION'""",
            (self.case_id,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """INSERT INTO research_passes (
                       case_id, pass_type, status, outcome, summary_claim_id
                   ) VALUES (?, 'COMPETITION', 'SATISFIED', 'EVIDENCE_FOUND', ?)""",
                (self.case_id, analysis_id),
            )

    def test_competition_pass_requires_structured_inventory(self) -> None:
        claim_id = self.factual_claim(
            "existing tools already work", "An existing tool is reported to work."
        )
        with self.assertRaisesRegex(IntegrityError, "competitor record"):
            self.repository.satisfy_research_requirement(
                case_id=self.case_id,
                requirement=ResearchRequirement.COMPETITION,
                factual_claim_id=claim_id,
            )

        competitor_id = self.add_competitor(claim_id)
        complaint_claim = self.factual_claim(
            "some report", "Some reports contradict a universal workflow gap."
        )
        complaint_id = self.repository.add_competitor_complaint(
            competitor_id=competitor_id,
            complaint_type="LIMITED_COVERAGE",
            statement="The available evidence only establishes partial coverage.",
            factual_claim_ids=[complaint_claim],
            affected_segment="teams with exceptions",
            frequency_observed="one source",
        )
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.COMPETITION,
            factual_claim_id=claim_id,
        )

        inventory = self.repository.competition_inventory(self.case_id)
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0].competitor_id, competitor_id)
        self.assertEqual(inventory[0].complaints[0].complaint_id, complaint_id)
        self.assertEqual(inventory[0].complaints[0].complaint_type, "LIMITED_COVERAGE")

    def test_counter_pass_requires_structured_counter_evidence(self) -> None:
        claim_id = self.factual_claim(
            "some report", "Some users contradict a universal unmet need."
        )
        with self.assertRaisesRegex(IntegrityError, "structured counter-evidence"):
            self.repository.satisfy_research_requirement(
                case_id=self.case_id,
                requirement=ResearchRequirement.COUNTER_EVIDENCE,
                factual_claim_id=claim_id,
            )

        counter_id = self.repository.add_counter_evidence(
            case_id=self.case_id,
            evidence_type=CounterEvidenceType.CONTRADICTING_USERS,
            statement="Some users report that their existing tools work.",
            factual_claim_id=claim_id,
        )
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.COUNTER_EVIDENCE,
            factual_claim_id=claim_id,
        )
        items = self.repository.counter_evidence_for_case(self.case_id)
        self.assertEqual(items[0].counter_evidence_id, counter_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE claims SET claim_kind = 'ANALYSIS' WHERE id = ?", (claim_id,)
            )

    def test_dach_pass_requires_structured_assessment(self) -> None:
        with self.assertRaisesRegex(IntegrityError, "structured DACH assessment"):
            self.repository.complete_research_requirement_without_evidence(
                case_id=self.case_id,
                requirement=ResearchRequirement.DACH_TRANSFER,
                note="No DACH-local evidence was found.",
            )
        self.repository.connection.execute(
            """DELETE FROM research_passes
               WHERE case_id = ? AND pass_type = 'DACH_TRANSFER'""",
            (self.case_id,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """INSERT INTO research_passes (
                       case_id, pass_type, status, outcome, note
                   ) VALUES (?, 'DACH_TRANSFER', 'SATISFIED',
                             'NO_EVIDENCE_FOUND', 'No local evidence found.')""",
                (self.case_id,),
            )
        self.repository.connection.execute(
            """INSERT INTO research_passes (case_id, pass_type)
               VALUES (?, 'DACH_TRANSFER')""",
            (self.case_id,),
        )

        self.add_empty_dach_assessment()
        self.repository.complete_research_requirement_without_evidence(
            case_id=self.case_id,
            requirement=ResearchRequirement.DACH_TRANSFER,
            note="No DACH-local evidence was found.",
        )
        assessment = self.repository.dach_assessment(self.case_id)
        assert assessment is not None
        self.assertEqual(assessment.local_evidence_state, LocalEvidenceState.NONE_FOUND)

    def test_dach_evidence_state_rejects_inconsistent_counts(self) -> None:
        with self.assertRaises(IntegrityError):
            self.repository.upsert_dach_assessment(
                case_id=self.case_id,
                actor_equivalence=ActorEquivalence.UNCLEAR,
                actor_rationale="The local actor is unknown.",
                workflow_equivalence=WorkflowEquivalence.UNKNOWN,
                workflow_rationale="The local workflow is unknown.",
                transfer_type=DachTransferType.WEAK_LOCAL_EVIDENCE,
                transfer_rationale="Only a claimed signal was supplied.",
                local_evidence_state=LocalEvidenceState.NONE_FOUND,
                dach_observation_count=1,
                dach_unique_author_count=1,
                dach_source_count=1,
            )

    def test_direct_sql_cannot_bypass_transition_or_completion_rules(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE research_cases SET status = 'COMPLETE' WHERE id = ?", (self.case_id,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """INSERT INTO research_cases (cluster_id, title, status)
                   VALUES (?, 'Bypass', 'COMPLETE')""",
                (self.cluster_id,),
            )

    def test_requirement_claim_cannot_be_downgraded(self) -> None:
        claim_id = self.factual_claim(
            "existing tools already work", "Some existing tools are reported to work."
        )
        self.add_competitor(claim_id)
        self.repository.satisfy_research_requirement(
            case_id=self.case_id,
            requirement=ResearchRequirement.COMPETITION,
            factual_claim_id=claim_id,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE claims SET claim_kind = 'ANALYSIS' WHERE id = ?", (claim_id,)
            )

    def test_actor_role_alone_satisfies_clear_actor_gate(self) -> None:
        observation_id = self.repository.connection.execute(
            "SELECT observation_id FROM cluster_members WHERE cluster_id = ?",
            (self.cluster_id,),
        ).fetchone()[0]
        self.repository.connection.execute(
            """UPDATE problem_observations
               SET actor = NULL, actor_role = 'finance analyst'
               WHERE id = ?""",
            (observation_id,),
        )
        self.add_empty_dach_assessment()
        for requirement in ResearchRequirement:
            self.repository.complete_research_requirement_without_evidence(
                case_id=self.case_id,
                requirement=requirement,
                note=f"Controlled search completed for {requirement.value}.",
            )
        self.repository.add_research_unknown(
            case_id=self.case_id,
            statement="The exception rate is unknown.",
        )
        self.repository.add_validation_question(
            case_id=self.case_id,
            question="How often do exceptions occur?",
        )
        self.repository.transition_research_case(
            self.case_id, ResearchCaseStatus.INVESTIGATING
        )
        self.repository.transition_research_case(self.case_id, ResearchCaseStatus.REVIEW)
        self.repository.transition_research_case(self.case_id, ResearchCaseStatus.COMPLETE)

        summary = self.repository.research_case_summary(self.case_id)
        self.assertEqual(summary.status, ResearchCaseStatus.COMPLETE)

    def test_v8_complete_case_is_reopened_for_stricter_v9_review(self) -> None:
        competition_claim = self.factual_claim(
            "existing tools already work", "Some existing tools are reported to work."
        )
        counter_claim = self.factual_claim(
            "some report", "The report contains counter-evidence."
        )
        self.repository.connection.executemany(
            """INSERT INTO research_requirements (
                   case_id, requirement_type, status, satisfied_by_claim_id
               ) VALUES (?, ?, 'SATISFIED', ?)""",
            (
                (self.case_id, "COMPETITION", competition_claim),
                (self.case_id, "COUNTER_EVIDENCE", counter_claim),
            ),
        )
        self.repository.connection.execute(
            "DELETE FROM research_passes WHERE case_id = ?", (self.case_id,)
        )
        self.repository.connection.execute("DROP TRIGGER research_case_completion_guard")
        self.repository.connection.execute("DROP TRIGGER research_case_transition_guard")
        self.repository.connection.execute(
            "UPDATE research_cases SET status = 'COMPLETE' WHERE id = ?", (self.case_id,)
        )
        self.repository.connection.execute("PRAGMA user_version = 8")

        self.repository.initialize()

        summary = self.repository.research_case_summary(self.case_id)
        self.assertEqual(summary.status, ResearchCaseStatus.REVIEW)
        self.assertEqual(len(summary.requirements), 4)
        migrated = {
            item.requirement: item.status.value for item in summary.requirements
        }
        self.assertEqual(migrated[ResearchRequirement.COMPETITION], "PENDING")
        self.assertEqual(migrated[ResearchRequirement.COUNTER_EVIDENCE], "PENDING")
        self.assertEqual(migrated[ResearchRequirement.WORKAROUND_RESEARCH], "PENDING")
        self.assertEqual(migrated[ResearchRequirement.DACH_TRANSFER], "PENDING")


if __name__ == "__main__":
    unittest.main()

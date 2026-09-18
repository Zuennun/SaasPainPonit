from __future__ import annotations

import unittest

from problem_intelligence.candidates import research_case_candidates
from problem_intelligence.clustering import cluster_exact
from problem_intelligence.domain import (
    EvidenceRange,
    EvidenceScope,
    ImpactSignalDraft,
    ImpactType,
    PaymentEvidenceType,
    PaymentSignalDraft,
    PipelineStage,
    ProblemFamily,
    ProblemType,
    SourceLifecycle,
    WorkaroundSignalDraft,
    WorkaroundType,
)
from problem_intelligence.repository import Repository
from problem_intelligence.source_metrics import (
    plan_source_budget,
    ranked_source_performance,
    refresh_source_metrics,
    source_problem_family_performance,
)


class SourceMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()

    def tearDown(self) -> None:
        self.repository.close()

    def test_metrics_are_persisted_idempotently_with_unknowns(self) -> None:
        first_source = self.repository.upsert_source(source_type="forum", name="operators")
        second_source = self.repository.upsert_source(source_type="forum", name="owners")
        first_item = self.repository.upsert_source_item(
            source_id=first_source,
            external_id="one",
            raw_text=(
                "We manually reconcile invoices for two hours every week "
                "and pay an accountant."
            ),
        )
        second_item = self.repository.upsert_source_item(
            source_id=second_source,
            external_id="two",
            raw_text="Our team also manually reconciles invoices every week.",
        )
        fingerprint_fields = {
            "actor": "finance team",
            "job_to_be_done": "reconcile invoices",
            "context": "weekly close",
            "current_workaround": "accountant",
        }
        strong_fields = {
            **fingerprint_fields,
            "existing_spend": "accountant labor",
            "active_solution_search": True,
        }
        first_text = self.repository.source_items((first_item,))[0].raw_text
        self.repository.create_observation_with_evidence(
            source_item_id=first_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Teams manually reconcile invoices.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(first_text)),),
            fields=strong_fields,
            workarounds=(
                WorkaroundSignalDraft(WorkaroundType.MANUAL_ENTRY, "manual reconciliation", 0),
            ),
            impact_signals=(
                ImpactSignalDraft(ImpactType.TIME, True, "2", "hours", "weekly", 0),
            ),
            payment_signals=(
                PaymentSignalDraft(PaymentEvidenceType.EMPLOYEE_LABOR, None, None, "weekly", 0),
            ),
        )
        self.repository.create_observation(
            source_item_id=second_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Teams manually reconcile invoices.",
            extraction_version="manual-v1",
            fields=fingerprint_fields,
        )
        self.repository.create_observation(
            source_item_id=first_item,
            problem_type=ProblemType.SUPPORT_QUESTION,
            problem_family=ProblemFamily.OTHER,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="A user asks how to configure an existing feature.",
            extraction_version="manual-v1",
        )
        cluster_exact(self.repository)

        first = refresh_source_metrics(self.repository)
        second = refresh_source_metrics(self.repository)
        self.assertEqual(first, second)
        self.assertEqual(self.repository.stats()["source_metrics"], 2)

        operators = next(item for item in first if item.source_name == "operators")
        self.assertEqual(operators.items_scanned, 1)
        self.assertIsNone(operators.items_after_prefilter)
        self.assertEqual(operators.pain_observations, 2)
        self.assertEqual(operators.strong_single_signals, 1)
        self.assertEqual(operators.active_search_signals, 1)
        self.assertEqual(operators.payment_signals, 1)
        self.assertEqual(operators.problem_clusters_contributed, 2)
        self.assertEqual(operators.cross_source_confirmations, 1)
        self.assertEqual(operators.support_questions, 1)
        self.assertEqual(operators.quantified_impact_signals, 1)
        self.assertIsNone(operators.promo_items)
        self.assertIsNone(operators.known_processing_cost_usd)
        self.assertFalse(operators.processing_cost_complete)
        self.assertEqual(operators.to_dict()["pain_yield_per_1000"], 2000.0)
        self.assertIsNone(operators.to_dict()["research_cost_per_strong_signal_usd"])
        families = source_problem_family_performance(self.repository)
        reconciliation = next(
            item
            for item in families
            if item.source_name == "operators"
            and item.problem_family == "RECONCILIATION"
        )
        self.assertEqual(reconciliation.observation_count, 1)
        self.assertEqual(reconciliation.strong_signal_count, 1)
        self.assertEqual(reconciliation.cluster_count, 1)
        self.assertEqual(reconciliation.to_dict()["observation_yield_per_1000"], 1000.0)

        self.repository.set_source_lifecycle(first_source, SourceLifecycle.CORE)
        self.repository.set_source_lifecycle(second_source, SourceLifecycle.EXPLORATION)
        self.repository.upsert_source(
            source_type="forum",
            name="operators",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        self.repository.upsert_source(
            source_type="forum",
            name="owners",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        ranked = ranked_source_performance(
            self.repository, sort_by="strong-signal-yield"
        )
        self.assertEqual([item.snapshot.source_name for item in ranked], ["operators", "owners"])
        self.assertEqual(ranked[0].lifecycle, SourceLifecycle.CORE)
        self.assertTrue(ranked[0].production_ready)
        self.assertIn("strong_signal_yield_per_1000", ranked[0].to_dict())
        production_ready = ranked_source_performance(
            self.repository,
            lifecycles=(SourceLifecycle.CORE,),
            production_ready_only=True,
        )
        self.assertEqual(len(production_ready), 1)
        self.assertEqual(production_ready[0].snapshot.source_id, first_source)
        self.assertEqual(
            ranked_source_performance(self.repository, minimum_items=2), ()
        )
        with self.assertRaisesRegex(ValueError, "unsupported source performance sort"):
            ranked_source_performance(self.repository, sort_by="legacy-score")

        candidate_source = self.repository.upsert_source(
            source_type="forum",
            name="new candidate",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        self.repository.connection.execute(
            """INSERT INTO source_registry_profiles (source_id, platform, pilot_posts)
               VALUES (?, 'forum', 2)""",
            (candidate_source,),
        )
        self.repository.upsert_source(
            source_type="forum",
            name="policy review candidate",
            commercial_use_status="REVIEW_REQUIRED",
        )
        plan = plan_source_budget(
            self.repository,
            total_item_budget=9,
            exploration_item_budget=3,
            per_source_cap=4,
            minimum_performance_items=1,
        )
        self.assertEqual(
            [(item.source_name, item.lane, item.allocated_items) for item in plan.allocations],
            [
                ("operators", "PERFORMANCE", 4),
                ("owners", "PERFORMANCE", 2),
                ("new candidate", "EXPLORATION", 2),
            ],
        )
        self.assertEqual(plan.allocations[-1].source_id, candidate_source)
        self.assertEqual(plan.allocations[-1].per_source_cap, 2)
        self.assertEqual(plan.allocated_performance_items, 6)
        self.assertEqual(plan.allocated_exploration_items, 2)
        self.assertEqual(plan.to_dict()["unallocated_exploration_items"], 1)
        self.assertFalse(plan.to_dict()["policy"]["composite_score_used"])

        cost_plan = plan_source_budget(
            self.repository,
            total_item_budget=4,
            exploration_item_budget=1,
            per_source_cap=4,
            minimum_performance_items=1,
            performance_sort="cost-per-strong-signal",
        )
        self.assertEqual(cost_plan.allocated_performance_items, 0)
        self.assertEqual(cost_plan.to_dict()["unallocated_performance_items"], 3)
        self.assertEqual(cost_plan.allocated_exploration_items, 1)
        with self.assertRaisesRegex(ValueError, "between zero and total budget"):
            plan_source_budget(
                self.repository,
                total_item_budget=2,
                exploration_item_budget=3,
                per_source_cap=1,
                minimum_performance_items=1,
            )

    def test_strong_signal_count_agrees_with_candidates_for_column_only_payment(self) -> None:
        # A payment evidence column (existing_spend/paid_workaround) with no structured
        # payment_signals row must count as payment evidence in both the SQL strong-signal
        # predicate (source_metrics) and the Python one (candidates) identically.
        source = self.repository.upsert_source(source_type="forum", name="operators")
        text = "We pay 200 EUR per month for a manual reconciliation tool and it still breaks."
        item = self.repository.upsert_source_item(
            source_id=source, external_id="one", raw_text=text
        )
        self.repository.create_observation_with_evidence(
            source_item_id=item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Manual reconciliation breaks",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, 40),),
            fields={
                "actor": "finance team",
                "job_to_be_done": "reconcile payments",
                "context": "monthly close",
                "existing_spend": "200 EUR per month",
            },
        )
        cluster_exact(self.repository)

        candidates = research_case_candidates(self.repository)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].strong_individual_signal_count, 1)

        snapshot = refresh_source_metrics(self.repository)[0]
        self.assertEqual(
            snapshot.strong_single_signals,
            candidates[0].strong_individual_signal_count,
        )

    def test_observations_from_a_failed_pipeline_run_are_excluded_from_metrics(self) -> None:
        # Extraction commits observations as it goes and only marks the run FAILED if a
        # later item in the same batch blows up; already-committed rows must not leak into
        # source performance counters, which back scan-budget allocation.
        source = self.repository.upsert_source(source_type="forum", name="operators")
        text = "We manually reconcile every payment and it takes hours each week."
        item = self.repository.upsert_source_item(
            source_id=source, external_id="one", raw_text=text
        )
        run_id = self.repository.start_pipeline_run(
            stage=PipelineStage.EXTRACTION, version="v1", input_count=2
        )
        self.repository.create_observation_with_evidence(
            source_item_id=item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Manual reconciliation",
            extraction_version="v1",
            evidence_ranges=(EvidenceRange(0, 40),),
            fields={
                "actor": "finance team",
                "job_to_be_done": "reconcile payments",
                "context": "weekly close",
                "existing_spend": "hours of labor",
            },
            pipeline_run_id=run_id,
        )
        self.repository.fail_pipeline_run(run_id, output_count=1, error="provider timeout")

        snapshot = refresh_source_metrics(self.repository)[0]
        self.assertEqual(snapshot.pain_observations, 0)
        self.assertEqual(snapshot.strong_single_signals, 0)

        family_performance = source_problem_family_performance(self.repository)
        self.assertEqual(family_performance, ())


if __name__ == "__main__":
    unittest.main()

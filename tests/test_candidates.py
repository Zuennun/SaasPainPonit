from __future__ import annotations

import unittest

from problem_intelligence.candidates import research_case_candidates
from problem_intelligence.clustering import cluster_exact
from problem_intelligence.domain import (
    EvidenceRange,
    EvidenceScope,
    EvidenceState,
    ImpactSignalDraft,
    ImpactType,
    PaymentEvidenceType,
    PaymentSignalDraft,
    ProblemFamily,
    ProblemType,
    WorkaroundSignalDraft,
    WorkaroundType,
)
from problem_intelligence.repository import Repository


class ResearchCaseCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()

    def tearDown(self) -> None:
        self.repository.close()

    def _source_item(self, source: str, external_id: str, text: str) -> int:
        source_id = self.repository.upsert_source(source_type="fixture", name=source)
        return self.repository.upsert_source_item(
            source_id=source_id,
            external_id=external_id,
            raw_text=text,
        )

    def test_recurring_cross_market_cluster_exposes_dimensions_without_score(self) -> None:
        text = "We manually reconcile invoices for two hours and pay an accountant."
        global_item = self._source_item("global-forum", "one", text)
        dach_item = self._source_item("dach-forum", "two", text)
        fields = {
            "actor": "finance team",
            "job_to_be_done": "reconcile invoices",
            "context": "month-end close",
            "current_workaround": "manual reconciliation",
        }
        self.repository.create_observation_with_evidence(
            source_item_id=global_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Finance teams manually reconcile invoices.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields=fields,
            workarounds=(
                WorkaroundSignalDraft(WorkaroundType.MANUAL_ENTRY, "manual reconciliation", 0),
            ),
            impact_signals=(
                ImpactSignalDraft(ImpactType.TIME, True, "2", "hours", None, 0),
            ),
            payment_signals=(
                PaymentSignalDraft(PaymentEvidenceType.EMPLOYEE_LABOR, None, None, None, 0),
            ),
        )
        self.repository.create_observation_with_evidence(
            source_item_id=dach_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.DACH,
            problem="Finance teams manually reconcile invoices.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields=fields,
        )
        cluster_exact(self.repository)

        candidate = research_case_candidates(self.repository)[0]
        payload = candidate.to_dict()
        self.assertEqual(candidate.evidence_state, EvidenceState.CROSS_MARKET)
        self.assertEqual(candidate.observation_count, 2)
        self.assertEqual(candidate.source_count, 2)
        self.assertEqual(candidate.quantified_impact_count, 1)
        self.assertEqual(candidate.payment_evidence_count, 1)
        self.assertTrue(candidate.research_ready)
        self.assertTrue(candidate.minimum_problem_evidence_complete)
        self.assertEqual(candidate.missing_for_completion, ())
        self.assertNotIn("score", payload)
        self.assertIn("global and DACH evidence are both present", candidate.reasons)

    def test_strong_single_signal_is_ready_but_noise_only_cluster_is_not(self) -> None:
        signal_text = "I manually export reports every week and need another tool."
        signal_item = self._source_item("operators", "signal", signal_text)
        self.repository.create_observation_with_evidence(
            source_item_id=signal_item,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.REPORTING,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Operators manually export recurring reports.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(signal_text)),),
            fields={
                "actor_role": "operator",
                "job_to_be_done": "export weekly reports",
                "current_workaround": "manual export",
                "active_solution_search": True,
            },
        )
        noise_text = "How do I enable the export button?"
        noise_item = self._source_item("support", "noise", noise_text)
        self.repository.create_observation_with_evidence(
            source_item_id=noise_item,
            problem_type=ProblemType.SUPPORT_QUESTION,
            problem_family=ProblemFamily.OTHER,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="A user asks how to enable an existing feature.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(noise_text)),),
            fields={
                "actor": "user",
                "job_to_be_done": "export data",
                "context": "configuration",
                "active_solution_search": True,
            },
        )
        cluster_exact(self.repository)

        candidates = research_case_candidates(self.repository)
        signal = next(item for item in candidates if item.problem_family is ProblemFamily.REPORTING)
        noise = next(item for item in candidates if item.problem_family is ProblemFamily.OTHER)
        self.assertTrue(signal.research_ready)
        self.assertEqual(signal.strong_individual_signal_count, 1)
        self.assertFalse(signal.minimum_problem_evidence_complete)
        self.assertEqual(signal.missing_for_completion, ("context",))
        self.assertFalse(noise.research_ready)
        self.assertIn("incidents", noise.exclusion_reason or "")

    def test_observation_count_reflects_multiple_observations_from_one_item(self) -> None:
        text = (
            "We manually reconcile invoices every week. "
            "We also manually reconcile invoices every week."
        )
        item_id = self._source_item("forum", "one", text)
        fields = {
            "actor": "finance team",
            "job_to_be_done": "reconcile invoices",
            "context": "week close",
        }
        for _ in range(2):
            self.repository.create_observation_with_evidence(
                source_item_id=item_id,
                problem_type=ProblemType.WORKFLOW_GAP,
                problem_family=ProblemFamily.RECONCILIATION,
                ontology_version="problem-ontology-v1",
                evidence_scope=EvidenceScope.GLOBAL,
                problem="Finance teams manually reconcile invoices.",
                extraction_version="manual-v1",
                evidence_ranges=(EvidenceRange(0, len("We manually reconcile invoices")),),
                fields=fields,
            )
        cluster_exact(self.repository)

        candidate = research_case_candidates(self.repository)[0]
        # Two problem_observations rows share the same source item; the count must
        # reflect the observations, not the distinct source item count (1).
        self.assertEqual(candidate.observation_count, 2)
        self.assertEqual(candidate.source_count, 1)
        self.assertEqual(candidate.evidence_state, EvidenceState.SINGLE_SIGNAL)

    def test_opened_cases_are_hidden_by_default_and_can_be_included(self) -> None:
        text = "I manually copy orders every day."
        item_id = self._source_item("retail", "one", text)
        self.repository.create_observation_with_evidence(
            source_item_id=item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Retail staff manually copy orders.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields={
                "actor": "retail staff",
                "job_to_be_done": "record orders",
                "context": "daily operations",
            },
        )
        result = cluster_exact(self.repository)
        self.repository.create_research_case(
            cluster_id=result.cluster_ids[0], title="Manual orders"
        )

        self.assertEqual(research_case_candidates(self.repository), ())
        included = research_case_candidates(self.repository, include_opened=True)
        self.assertEqual(len(included), 1)
        self.assertIsNotNone(included[0].existing_case_id)


if __name__ == "__main__":
    unittest.main()

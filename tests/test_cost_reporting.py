from __future__ import annotations

import unittest

from problem_intelligence.clustering import cluster_exact
from problem_intelligence.cost_reporting import build_cost_efficiency_report
from problem_intelligence.domain import (
    ActorEquivalence,
    ClaimKind,
    CounterEvidenceType,
    DachTransferType,
    EvidenceRange,
    EvidenceScope,
    LocalEvidenceState,
    ModelRunStatus,
    PipelineStage,
    ProblemFamily,
    ProblemType,
    ResearchCaseStatus,
    ResearchRequirement,
    SolutionType,
    WorkflowEquivalence,
)
from problem_intelligence.repository import Repository


class CostReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()

    def tearDown(self) -> None:
        self.repository.close()

    def test_unit_costs_require_complete_attribution_and_one_currency(self) -> None:
        source_id = self.repository.upsert_source(
            source_type="forum",
            name="operators",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        text = "Finance teams reconcile invoices manually and seek another tool."
        item_id = self.repository.upsert_source_item(
            source_id=source_id,
            external_id="item-1",
            raw_text=text,
        )
        self.repository.upsert_source_item(
            source_id=source_id,
            external_id="item-2",
            raw_text="A release announcement without a problem report.",
        )
        pipeline_id = self.repository.start_pipeline_run(
            stage=PipelineStage.EXTRACTION,
            version="test-v1",
            input_count=2,
        )
        observation_id, evidence_ids = self.repository.create_observation_with_evidence(
            source_item_id=item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Finance teams reconcile invoices manually.",
            extraction_version="test-v1",
            pipeline_run_id=pipeline_id,
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields={
                "actor": "finance teams",
                "job_to_be_done": "reconcile invoices",
                "context": "monthly close",
                "current_workaround": "manual reconciliation",
                "active_solution_search": True,
            },
        )
        self.repository.finish_pipeline_run(
            pipeline_id, output_count=1, input_signature="cost-test-signature"
        )
        cluster_id = cluster_exact(self.repository).cluster_ids[0]
        case_id = self.repository.create_research_case(
            cluster_id=cluster_id, title="Manual reconciliation"
        )
        claim_id = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="The source reports manual invoice reconciliation.",
            observation_id=observation_id,
            evidence_span_ids=evidence_ids,
        )
        self.repository.upsert_competitor(
            case_id=case_id,
            name="Manual process",
            solution_type=SolutionType.MANUAL_PROCESS,
            profile_claim_id=claim_id,
        )
        self.repository.add_counter_evidence(
            case_id=case_id,
            evidence_type=CounterEvidenceType.SATISFIED_WITH_WORKAROUND,
            statement="The current manual process remains available.",
            factual_claim_id=claim_id,
        )
        self.repository.upsert_dach_assessment(
            case_id=case_id,
            actor_equivalence=ActorEquivalence.UNCLEAR,
            actor_rationale="No local actor evidence was recorded.",
            workflow_equivalence=WorkflowEquivalence.UNKNOWN,
            workflow_rationale="No local workflow evidence was recorded.",
            transfer_type=DachTransferType.UNKNOWN,
            transfer_rationale="Transfer remains unknown.",
            local_evidence_state=LocalEvidenceState.NONE_FOUND,
            dach_observation_count=0,
            dach_unique_author_count=0,
            dach_source_count=0,
        )
        for requirement in (
            ResearchRequirement.COMPETITION,
            ResearchRequirement.COUNTER_EVIDENCE,
            ResearchRequirement.WORKAROUND_RESEARCH,
        ):
            self.repository.satisfy_research_requirement(
                case_id=case_id,
                requirement=requirement,
                factual_claim_id=claim_id,
            )
        self.repository.complete_research_requirement_without_evidence(
            case_id=case_id,
            requirement=ResearchRequirement.DACH_TRANSFER,
            note="No local evidence was found in the bounded fixture.",
        )
        self.repository.add_research_unknown(
            case_id=case_id, statement="The local buyer remains unknown."
        )
        self.repository.add_validation_question(
            case_id=case_id, question="Does the workflow recur in DACH?"
        )
        for status in (
            ResearchCaseStatus.INVESTIGATING,
            ResearchCaseStatus.REVIEW,
            ResearchCaseStatus.COMPLETE,
        ):
            self.repository.transition_research_case(case_id, status)

        self.repository.record_model_run(
            operation_key="extract-costed",
            provider="model-provider",
            model="model-a",
            pipeline_stage="structured-extraction",
            template_version="v1",
            status=ModelRunStatus.COMPLETED,
            input_tokens=100,
            output_tokens=20,
            latency_ms=50,
            items_processed=2,
            pipeline_run_id=pipeline_id,
            measured_cost="1.20",
            currency="EUR",
            cost_measurement_source="provider-response",
        )
        self._record_acquisition_costs(source_id, item_id)

        report = build_cost_efficiency_report(self.repository)

        self.assertEqual(report.acquisition.known_cost_usd, "0.3")
        self.assertEqual(
            report.acquisition.cost_per_acquired_source_item.amount_decimal, "0.3"
        )
        self.assertEqual(report.model.known_cost_by_currency, {"EUR": "1.2"})
        self.assertEqual(report.model.cost_per_processed_item.amount_decimal, "0.6")
        self.assertEqual(report.model.cost_per_useful_observation.amount_decimal, "1.2")
        self.assertEqual(
            report.model.cost_per_linked_complete_research_case.amount_decimal, "1.2"
        )
        self.assertEqual(report.model.strong_signal_observations, 1)
        self.assertEqual(report.model.linked_complete_research_cases, 1)
        self.assertEqual(
            report.to_dict()["end_to_end_cost_per_research_case"]["status"], "UNKNOWN"
        )

        self.repository.record_model_run(
            operation_key="extract-second-currency",
            provider="other-provider",
            model="model-b",
            pipeline_stage="structured-extraction",
            template_version="v1",
            status=ModelRunStatus.COMPLETED,
            input_tokens=10,
            output_tokens=2,
            latency_ms=5,
            items_processed=1,
            pipeline_run_id=pipeline_id,
            measured_cost="0.50",
            currency="USD",
            cost_measurement_source="provider-response",
        )
        mixed = build_cost_efficiency_report(self.repository)
        self.assertEqual(mixed.model.cost_per_processed_item.status, "UNKNOWN")
        self.assertIn(
            "measured costs use multiple currencies",
            mixed.model.cost_per_processed_item.unavailable_reasons,
        )
        filtered = build_cost_efficiency_report(
            self.repository, provider="model-provider"
        )
        self.assertEqual(filtered.model.cost_per_processed_item.amount_decimal, "0.6")

        self.repository.record_model_run(
            operation_key="extract-unknown-cost",
            provider="model-provider",
            model="model-a",
            pipeline_stage="structured-extraction",
            template_version="v1",
            status=ModelRunStatus.FAILED,
            input_tokens=5,
            output_tokens=0,
            latency_ms=3,
            items_processed=1,
            pipeline_run_id=pipeline_id,
            error="provider failure",
        )
        incomplete = build_cost_efficiency_report(
            self.repository, provider="model-provider"
        )
        self.assertEqual(incomplete.model.missing_cost_run_count, 1)
        self.assertIn(
            "1 operation has unknown cost",
            incomplete.model.cost_per_processed_item.unavailable_reasons,
        )

    def _record_acquisition_costs(self, source_id: int, item_id: int) -> None:
        self.repository.connection.execute(
            """INSERT INTO discovery_runs (
                   id, source_id, provider, query, availability, cost_usd,
                   provider_capabilities_json
               ) VALUES ('discovery-cost-test', ?, 'source-provider', 'test',
                         'RESULTS', 0.1, '{}')""",
            (source_id,),
        )
        discovery_row = self.repository.connection.execute(
            """INSERT INTO discovery_records (
                   run_id, source_id, provider, query, url, canonical_url, submission_id
               ) VALUES ('discovery-cost-test', ?, 'source-provider', 'test',
                         'https://example.test/item', 'https://example.test/item', 'item')
               RETURNING id""",
            (source_id,),
        ).fetchone()
        assert discovery_row is not None
        discovery_id = int(discovery_row[0])
        self.repository.connection.execute(
            """INSERT INTO acquisition_records (
                   discovery_id, source_item_id, provider, state, completeness,
                   cost_usd
               ) VALUES (?, ?, 'source-provider', 'CONTENT_COMPLETE', 'FULL', 0.2)""",
            (discovery_id, item_id),
        )

    def test_strong_signal_observations_excludes_failed_pipeline_runs(self) -> None:
        # A model run can COMPLETE while the pipeline run it fed into later FAILS (a
        # later item in the same batch broke the run); the already-committed observation
        # must not count as a useful output for cost-per-useful-observation.
        source_id = self.repository.upsert_source(
            source_type="forum",
            name="operators",
            commercial_use_status="APPROVED_TEST_FIXTURE",
        )
        text = "We pay 50 EUR a month and still manually reconcile invoices every week."
        item_id = self.repository.upsert_source_item(
            source_id=source_id, external_id="item-1", raw_text=text
        )
        pipeline_id = self.repository.start_pipeline_run(
            stage=PipelineStage.EXTRACTION, version="test-v1", input_count=2
        )
        self.repository.create_observation_with_evidence(
            source_item_id=item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Finance teams reconcile invoices manually.",
            extraction_version="test-v1",
            pipeline_run_id=pipeline_id,
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields={
                "actor": "finance teams",
                "job_to_be_done": "reconcile invoices",
                "context": "monthly close",
                "existing_spend": "50 EUR a month",
            },
        )
        self.repository.fail_pipeline_run(pipeline_id, output_count=1, error="provider timeout")
        self.repository.record_model_run(
            operation_key="extract-then-batch-failed",
            provider="model-provider",
            model="model-a",
            pipeline_stage="structured-extraction",
            template_version="v1",
            status=ModelRunStatus.COMPLETED,
            input_tokens=100,
            output_tokens=20,
            latency_ms=50,
            items_processed=1,
            pipeline_run_id=pipeline_id,
            measured_cost="1.00",
            currency="EUR",
            cost_measurement_source="provider-response",
        )

        report = build_cost_efficiency_report(self.repository)

        self.assertEqual(report.model.strong_signal_observations, 0)
        self.assertEqual(report.model.linked_complete_research_cases, 0)


if __name__ == "__main__":
    unittest.main()

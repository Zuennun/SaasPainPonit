import sqlite3
import unittest

from problem_intelligence.domain import (
    ClaimKind,
    EvidenceRange,
    EvidenceScope,
    ImpactSignalDraft,
    ImpactType,
    ModelRunStatus,
    PaymentEvidenceType,
    PaymentSignalDraft,
    PipelineStage,
    ProblemFamily,
    ProblemType,
    SourceAvailability,
    SourceLifecycle,
    StakeholderKnowledge,
    StakeholderRole,
    WorkaroundSignalDraft,
    WorkaroundType,
)
from problem_intelligence.repository import IntegrityError, Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(source_type="Forum", name="Bookkeepers")
        self.text = (
            "Every Friday I copy invoices into a spreadsheet for three hours "
            "and pay a contractor 50 EUR."
        )
        self.item_id = self.repository.upsert_source_item(
            source_id=self.source_id,
            external_id=" Post-42 ",
            raw_text=self.text,
            country_code="DE",
            language_code="en",
        )

    def tearDown(self) -> None:
        self.repository.close()

    def test_ingestion_is_idempotent(self) -> None:
        same_source_id = self.repository.upsert_source(source_type="forum", name="bookkeepers")
        same_item_id = self.repository.upsert_source_item(
            source_id=same_source_id,
            external_id="post-42",
            raw_text=self.text,
            title="Updated metadata",
        )
        self.assertEqual(same_source_id, self.source_id)
        self.assertEqual(same_item_id, self.item_id)
        self.assertEqual(self.repository.stats()["source_items"], 1)

    def test_reingestion_does_not_downgrade_source_lifecycle(self) -> None:
        self.repository.set_source_lifecycle(self.source_id, SourceLifecycle.CORE)
        self.repository.upsert_source(
            source_type="forum",
            name="bookkeepers",
            commercial_use_status="approved",
            retention_rules="90 days",
        )
        same_source_id = self.repository.upsert_source(
            source_type="forum", name="bookkeepers"
        )

        source = self.repository.connection.execute(
            """SELECT lifecycle, commercial_use_status, retention_rules
               FROM sources WHERE id = ?""",
            (same_source_id,),
        ).fetchone()
        self.assertEqual(source["lifecycle"], "CORE")
        self.assertEqual(source["commercial_use_status"], "approved")
        self.assertEqual(source["retention_rules"], "90 days")

    def test_explicit_source_lifecycle_change_is_applied(self) -> None:
        same_source_id = self.repository.upsert_source(
            source_type="forum",
            name="bookkeepers",
            lifecycle=SourceLifecycle.EXCLUDED,
        )
        lifecycle = self.repository.connection.execute(
            "SELECT lifecycle FROM sources WHERE id = ?", (same_source_id,)
        ).fetchone()[0]
        self.assertEqual(lifecycle, "EXCLUDED")

    def test_schema_is_versioned_and_initialization_is_idempotent(self) -> None:
        self.repository.initialize()
        version = self.repository.connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 23)

    def test_schema_22_discovery_requested_items_is_migrated(self) -> None:
        self.repository.connection.execute(
            "ALTER TABLE discovery_runs DROP COLUMN requested_items"
        )
        self.repository.connection.execute("PRAGMA user_version = 22")
        self.repository.initialize()
        columns = {
            row["name"]
            for row in self.repository.connection.execute(
                "PRAGMA table_info(discovery_runs)"
            )
        }
        self.assertIn("requested_items", columns)
        self.assertEqual(
            self.repository.connection.execute("PRAGMA user_version").fetchone()[0], 23
        )

    def test_schema_four_registry_is_migrated_with_scan_directive(self) -> None:
        self.repository.connection.execute(
            "ALTER TABLE source_registry_profiles DROP COLUMN scan_directive"
        )
        self.repository.connection.execute("PRAGMA user_version = 4")
        self.repository.initialize()
        columns = {
            row["name"]
            for row in self.repository.connection.execute(
                "PRAGMA table_info(source_registry_profiles)"
            ).fetchall()
        }
        self.assertIn("scan_directive", columns)
        version = self.repository.connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 23)

    def test_schema_fourteen_adds_complete_source_policy_columns(self) -> None:
        policy_columns = (
            "quoting_rules",
            "deletion_requirements",
            "rate_limit_notes",
            "rights_reviewed_at",
        )
        for column in policy_columns:
            self.repository.connection.execute(f"ALTER TABLE sources DROP COLUMN {column}")
        self.repository.connection.execute("PRAGMA user_version = 14")

        self.repository.initialize()

        columns = {
            row["name"]
            for row in self.repository.connection.execute("PRAGMA table_info(sources)")
        }
        self.assertTrue(set(policy_columns) <= columns)
        version = self.repository.connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 23)

    def test_schema_sixteen_normalizes_review_required_source_policy(self) -> None:
        self.repository.connection.execute(
            "UPDATE sources SET commercial_use_status = 'requires-review'"
        )
        self.repository.connection.execute("PRAGMA user_version = 16")

        self.repository.initialize()

        status = self.repository.connection.execute(
            "SELECT commercial_use_status FROM sources WHERE id = ?", (self.source_id,)
        ).fetchone()[0]
        self.assertEqual(status, "REVIEW_REQUIRED")
        version = self.repository.connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 23)

    def test_model_telemetry_is_exact_idempotent_and_cost_optional(self) -> None:
        pipeline_run_id = self.repository.start_pipeline_run(
            stage=PipelineStage.EXTRACTION,
            version="extract-v3",
            input_count=10,
        )
        self.repository.finish_pipeline_run(
            pipeline_run_id,
            output_count=2,
            input_signature="fixture-batch-42",
        )
        first = self.repository.record_model_run(
            operation_key="extract:batch-42",
            provider="provider-a",
            model="model-1",
            pipeline_stage="structured-extraction",
            template_version="extract-v3",
            status=ModelRunStatus.COMPLETED,
            input_tokens=1200,
            output_tokens=240,
            latency_ms=875,
            items_processed=10,
            pipeline_run_id=pipeline_run_id,
            external_run_id="request-99",
            measured_cost="0.012300",
            currency="usd",
            cost_measurement_source="provider-response",
        )
        repeated = self.repository.record_model_run(
            operation_key="extract:batch-42",
            provider="provider-a",
            model="model-1",
            pipeline_stage="structured-extraction",
            template_version="extract-v3",
            status=ModelRunStatus.COMPLETED,
            input_tokens=1200,
            output_tokens=240,
            latency_ms=875,
            items_processed=10,
            pipeline_run_id=pipeline_run_id,
            external_run_id="request-99",
            measured_cost="0.0123",
            currency="USD",
            cost_measurement_source="provider-response",
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.measured_cost, "0.0123")
        self.assertEqual(self.repository.stats()["model_runs"], 1)
        self.assertEqual(self.repository.stats()["cost_events"], 1)
        with self.assertRaisesRegex(IntegrityError, "different model telemetry"):
            self.repository.record_model_run(
                operation_key="extract:batch-42",
                provider="provider-a",
                model="model-1",
                pipeline_stage="structured-extraction",
                template_version="extract-v3",
                status=ModelRunStatus.COMPLETED,
                input_tokens=1200,
                output_tokens=241,
                latency_ms=875,
                items_processed=10,
                pipeline_run_id=pipeline_run_id,
            )

    def test_model_telemetry_does_not_invent_cost_and_validates_failures(self) -> None:
        failed = self.repository.record_model_run(
            operation_key="cluster:batch-7",
            provider="local",
            model="embedding-model",
            pipeline_stage="embedding",
            template_version="embedding-input-v1",
            status=ModelRunStatus.FAILED,
            input_tokens=0,
            output_tokens=0,
            latency_ms=25,
            items_processed=0,
            error="provider timeout",
        )
        self.assertIsNone(failed.measured_cost)
        self.assertEqual(self.repository.stats()["cost_events"], 0)
        with self.assertRaisesRegex(ValueError, "supplied together"):
            self.repository.record_model_run(
                operation_key="invalid-cost",
                provider="provider-a",
                model="model-1",
                pipeline_stage="extraction",
                template_version="v1",
                status=ModelRunStatus.COMPLETED,
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
                items_processed=1,
                measured_cost="0.01",
            )

    def test_reviewed_observation_revision_is_audited_and_invalidates_clustering(self) -> None:
        observation_id = self.repository.create_observation_with_evidence(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Invoices are manually copied.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(self.text)),),
            fields={"actor": "bookkeeper", "job_to_be_done": "record invoices"},
        )[0]
        evidence_id = self.repository.connection.execute(
            "SELECT id FROM evidence_spans WHERE observation_id = ?", (observation_id,)
        ).fetchone()[0]
        from problem_intelligence.clustering import cluster_exact

        cluster_exact(self.repository)
        self.assertGreater(self.repository.stats()["problem_clusters"], 0)

        revision_id = self.repository.revise_observation_field(
            observation_id=observation_id,
            field_name="context",
            value="every Friday",
            reason="The cited sentence explicitly states the weekly context.",
            evidence_span_id=evidence_id,
            revision_version="manual-review-v1",
        )
        repeated_id = self.repository.revise_observation_field(
            observation_id=observation_id,
            field_name="context",
            value="every Friday",
            reason="The cited sentence explicitly states the weekly context.",
            evidence_span_id=evidence_id,
            revision_version="manual-review-v1",
        )

        self.assertEqual(revision_id, repeated_id)
        row = self.repository.connection.execute(
            "SELECT context FROM problem_observations WHERE id = ?", (observation_id,)
        ).fetchone()
        self.assertEqual(row["context"], "every Friday")
        revision = self.repository.connection.execute(
            """SELECT old_value_json, new_value_json, evidence_span_id
               FROM observation_revisions WHERE id = ?""",
            (revision_id,),
        ).fetchone()
        self.assertEqual(revision["old_value_json"], "null")
        self.assertEqual(revision["new_value_json"], '"every Friday"')
        self.assertEqual(revision["evidence_span_id"], evidence_id)
        self.assertEqual(self.repository.stats()["problem_clusters"], 0)

    def test_observation_revision_is_blocked_after_case_creation(self) -> None:
        from problem_intelligence.clustering import cluster_exact

        observation_id, evidence_ids = self.repository.create_observation_with_evidence(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Invoices are manually copied.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(self.text)),),
            fields={"actor": "bookkeeper", "job_to_be_done": "record invoices"},
        )
        cluster_id = cluster_exact(self.repository).cluster_ids[0]
        self.repository.create_research_case(cluster_id=cluster_id, title="Invoice copying")

        with self.assertRaisesRegex(IntegrityError, "research case references"):
            self.repository.revise_observation_field(
                observation_id=observation_id,
                field_name="context",
                value="every Friday",
                reason="Reviewed correction.",
                evidence_span_id=evidence_ids[0],
                revision_version="manual-review-v1",
            )

    def test_rejects_database_from_a_newer_schema(self) -> None:
        repository = Repository()
        try:
            repository.connection.execute("PRAGMA user_version = 999")
            with self.assertRaisesRegex(IntegrityError, "newer than supported"):
                repository.initialize()
        finally:
            repository.close()

    def test_unknown_fields_are_null(self) -> None:
        observation_id = self.repository.create_observation(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Invoices are manually copied into a spreadsheet.",
            extraction_version="manual-v1",
            fields={"actor_role": "bookkeeper"},
        )
        row = self.repository.connection.execute(
            "SELECT actor_role, time_impact, existing_spend FROM problem_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        self.assertEqual(row["actor_role"], "bookkeeper")
        self.assertIsNone(row["time_impact"])
        self.assertIsNone(row["existing_spend"])

    def test_existing_observation_can_receive_versioned_problem_family(self) -> None:
        observation_id = self.repository.create_observation(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Invoices are reconciled manually.",
            extraction_version="historical-v1",
        )
        self.repository.set_observation_problem_family(
            observation_id,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
        )
        row = self.repository.connection.execute(
            """SELECT problem_family, ontology_version
               FROM problem_observations WHERE id = ?""",
            (observation_id,),
        ).fetchone()
        assert row is not None
        self.assertEqual(row["problem_family"], "RECONCILIATION")
        self.assertEqual(row["ontology_version"], "problem-ontology-v1")

    def test_observation_field_types_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            self.repository.create_observation(
                source_item_id=self.item_id,
                problem_type=ProblemType.WORKFLOW_GAP,
                evidence_scope=EvidenceScope.DACH,
                problem="Manual invoice copying.",
                extraction_version="manual-v1",
                fields={"active_solution_search": "probably"},
            )
        with self.assertRaisesRegex(ValueError, "must be a string"):
            self.repository.create_observation(
                source_item_id=self.item_id,
                problem_type=ProblemType.WORKFLOW_GAP,
                evidence_scope=EvidenceScope.DACH,
                problem="Manual invoice copying.",
                extraction_version="manual-v1",
                fields={"tools_used": ["spreadsheet"]},
            )

    def test_evidence_excerpt_is_exact_and_source_becomes_immutable(self) -> None:
        start = self.text.index("copy invoices")
        evidence_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(start, start + len("copy invoices")),
            evidence_scope=EvidenceScope.DACH,
        )
        excerpt = self.repository.connection.execute(
            "SELECT excerpt FROM evidence_spans WHERE id = ?", (evidence_id,)
        ).fetchone()["excerpt"]
        self.assertEqual(excerpt, "copy invoices")
        repeated_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(start, start + len("copy invoices")),
            evidence_scope=EvidenceScope.DACH,
        )
        self.assertEqual(repeated_id, evidence_id)
        self.assertEqual(self.repository.stats()["evidence_spans"], 1)
        with self.assertRaises(IntegrityError):
            self.repository.upsert_source_item(
                source_id=self.source_id,
                external_id="post-42",
                raw_text="Changed source text",
            )

    def test_observation_and_evidence_scope_must_match(self) -> None:
        observation_id = self.repository.create_observation(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Manual invoice copying.",
            extraction_version="manual-v1",
        )
        with self.assertRaises(IntegrityError):
            self.repository.add_evidence_span(
                source_item_id=self.item_id,
                evidence_range=EvidenceRange(0, 5),
                evidence_scope=EvidenceScope.GLOBAL,
                observation_id=observation_id,
            )

    def test_structured_signals_are_stored_atomically_with_exact_evidence(self) -> None:
        observation_id, evidence_ids = self.repository.create_observation_with_evidence(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.DACH,
            problem="Invoices are copied manually.",
            extraction_version="manual-v2",
            evidence_ranges=(EvidenceRange(0, len(self.text)),),
            workarounds=(
                WorkaroundSignalDraft(
                    WorkaroundType.SPREADSHEET,
                    "copy invoices into a spreadsheet",
                    0,
                ),
            ),
            impact_signals=(ImpactSignalDraft(ImpactType.TIME, True, "3", "hours", "weekly", 0),),
            payment_signals=(
                PaymentSignalDraft(
                    PaymentEvidenceType.FREELANCER_SPEND,
                    "50",
                    "EUR",
                    "weekly",
                    0,
                ),
            ),
        )
        self.assertEqual(len(evidence_ids), 1)
        counts = {
            table: self.repository.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()[0]
            for table in ("workarounds", "impact_signals", "payment_signals")
        }
        self.assertEqual(
            counts,
            {"workarounds": 1, "impact_signals": 1, "payment_signals": 1},
        )

        with self.assertRaisesRegex(ValueError, "evidence_index"):
            self.repository.create_observation_with_evidence(
                source_item_id=self.item_id,
                problem_type=ProblemType.WORKFLOW_GAP,
                evidence_scope=EvidenceScope.DACH,
                problem="Invalid signal bundle.",
                extraction_version="manual-v2",
                evidence_ranges=(EvidenceRange(0, len(self.text)),),
                workarounds=(
                    WorkaroundSignalDraft(WorkaroundType.SPREADSHEET, "spreadsheet", 1),
                ),
            )
        self.assertEqual(self.repository.stats()["problem_observations"], 1)

    def test_fact_claim_requires_evidence(self) -> None:
        with self.assertRaises(IntegrityError):
            self.repository.create_claim(claim_kind=ClaimKind.FACT, text="Manual work occurs.")

        evidence_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(0, len(self.text)),
            evidence_scope=EvidenceScope.DACH,
        )
        claim_id = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="The source reports a recurring manual workflow.",
            evidence_span_ids=[evidence_id],
        )
        links = self.repository.connection.execute(
            "SELECT COUNT(*) FROM claim_evidence WHERE claim_id = ?", (claim_id,)
        ).fetchone()[0]
        self.assertEqual(links, 1)

    def test_database_rejects_direct_unsupported_fact(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "INSERT INTO claims (claim_kind, text) VALUES ('FACT', 'Unsupported')"
            )

        cursor = self.repository.connection.execute(
            "INSERT INTO claims (claim_kind, text) VALUES ('ANALYSIS', 'Still unsupported')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE claims SET claim_kind = 'FACT' WHERE id = ?", (cursor.lastrowid,)
            )

    def test_database_protects_final_fact_evidence_link(self) -> None:
        evidence_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(0, len(self.text)),
            evidence_scope=EvidenceScope.DACH,
        )
        claim_id = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="The source contains a report.",
            evidence_span_ids=[evidence_id],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "DELETE FROM claim_evidence WHERE claim_id = ?", (claim_id,)
            )

    def test_database_rejects_retargeting_observation_fact_evidence(self) -> None:
        observation_id, evidence_ids = self.repository.create_observation_with_evidence(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Invoices are copied manually.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(self.text)),),
        )
        unrelated_evidence = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(0, len(self.text) - 1),
            evidence_scope=EvidenceScope.DACH,
        )
        claim_id = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="The observation reports manual invoice copying.",
            observation_id=observation_id,
            evidence_span_ids=evidence_ids,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """UPDATE claim_evidence SET evidence_span_id = ?
                   WHERE claim_id = ?""",
                (unrelated_evidence, claim_id),
            )

    def test_case_stakeholders_distinguish_known_from_unknown_roles(self) -> None:
        from problem_intelligence.clustering import cluster_exact

        observation_id, evidence_ids = self.repository.create_observation_with_evidence(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Bookkeepers copy invoices manually.",
            extraction_version="manual-v1",
            evidence_ranges=(EvidenceRange(0, len(self.text)),),
            fields={
                "actor": "bookkeeper",
                "job_to_be_done": "record invoices",
                "context": "weekly processing",
            },
        )
        case_id = self.repository.create_research_case(
            cluster_id=cluster_exact(self.repository).cluster_ids[0],
            title="Manual invoice recording",
        )
        claim_id = self.repository.create_claim(
            claim_kind=ClaimKind.FACT,
            text="A bookkeeper performs the workflow.",
            observation_id=observation_id,
            evidence_span_ids=evidence_ids,
        )
        self.repository.upsert_case_stakeholder(
            case_id=case_id,
            role=StakeholderRole.END_USER,
            knowledge=StakeholderKnowledge.KNOWN,
            party="bookkeeper",
            factual_claim_id=claim_id,
            note="The source identifies the practitioner.",
        )
        self.repository.upsert_case_stakeholder(
            case_id=case_id,
            role=StakeholderRole.BUYER,
            knowledge=StakeholderKnowledge.UNKNOWN,
            note="No buyer evidence is present.",
        )

        stakeholders = self.repository.case_stakeholders(case_id)

        self.assertEqual([item.role for item in stakeholders], [
            StakeholderRole.END_USER,
            StakeholderRole.BUYER,
        ])
        self.assertEqual(stakeholders[0].party, "bookkeeper")
        self.assertIsNone(stakeholders[1].party)
        with self.assertRaisesRegex(ValueError, "requires party and factual claim"):
            self.repository.upsert_case_stakeholder(
                case_id=case_id,
                role=StakeholderRole.DECISION_MAKER,
                knowledge=StakeholderKnowledge.KNOWN,
                note="Unsupported.",
            )

    def test_database_rejects_forged_excerpt_and_direct_text_change(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """INSERT INTO evidence_spans (
                       source_item_id, start_offset, end_offset, excerpt, evidence_scope
                   ) VALUES (?, 0, 5, 'forged', 'DACH')""",
                (self.item_id,),
            )
        self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(0, 5),
            evidence_scope=EvidenceScope.DACH,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                "UPDATE source_items SET raw_text = 'changed' WHERE id = ?", (self.item_id,)
            )

    def test_database_rejects_evidence_for_wrong_observation(self) -> None:
        other_item_id = self.repository.upsert_source_item(
            source_id=self.source_id,
            external_id="other",
            raw_text="Other text",
        )
        observation_id = self.repository.create_observation(
            source_item_id=other_item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Other problem.",
            extraction_version="manual-v1",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute(
                """INSERT INTO evidence_spans (
                       source_item_id, observation_id, start_offset, end_offset,
                       excerpt, evidence_scope
                   ) VALUES (?, ?, 0, 5, 'Every', 'DACH')""",
                (self.item_id, observation_id),
            )

    def test_claim_evidence_must_belong_to_claim_observation(self) -> None:
        observation_id = self.repository.create_observation(
            source_item_id=self.item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.DACH,
            problem="Manual copying.",
            extraction_version="manual-v1",
        )
        standalone_evidence_id = self.repository.add_evidence_span(
            source_item_id=self.item_id,
            evidence_range=EvidenceRange(0, 5),
            evidence_scope=EvidenceScope.DACH,
        )
        with self.assertRaises(IntegrityError):
            self.repository.create_claim(
                claim_kind=ClaimKind.FACT,
                observation_id=observation_id,
                text="Evidence belongs to the observation.",
                evidence_span_ids=[standalone_evidence_id],
            )

    def test_retried_acquisition_does_not_null_a_stored_source_item(self) -> None:
        from problem_intelligence.domain import ContentCompleteness, DiscoveryState
        from problem_intelligence.reddit import SearchResult

        reddit_source_id = self.repository.upsert_source(
            source_type="reddit", name="r/Bookkeepers"
        )
        run_id = self.repository.record_discovery_response(
            source_id=reddit_source_id,
            provider="test-search",
            query="manual work",
            availability=SourceAvailability.RESULTS,
            results=[
                SearchResult(url="https://www.reddit.com/r/Bookkeepers/comments/abc123/")
            ],
            capabilities={},
            latency_ms=None,
            cost_usd=None,
            error=None,
        )
        discovery_row = self.repository.connection.execute(
            "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
        ).fetchone()
        discovery_id = int(discovery_row["id"])
        acquired_item_id = self.repository.upsert_source_item(
            source_id=reddit_source_id,
            external_id="reddit:submission:abc123",
            raw_text="We manually reconcile every invoice each week.",
        )

        self.repository.record_acquisition(
            discovery_id=discovery_id,
            source_item_id=acquired_item_id,
            provider="test-content",
            state=DiscoveryState.CONTENT_PARTIAL,
            completeness=ContentCompleteness.PARTIAL,
            latency_ms=None,
            cost_usd=None,
            error=None,
            metadata={},
        )
        # A later retry for the same (discovery_id, provider) that fails must not
        # erase the already-recorded source item or completeness.
        self.repository.record_acquisition(
            discovery_id=discovery_id,
            source_item_id=None,
            provider="test-content",
            state=DiscoveryState.ACQUISITION_FAILED,
            completeness=None,
            latency_ms=None,
            cost_usd=None,
            error="transient failure",
            metadata={},
        )
        row = self.repository.connection.execute(
            """SELECT source_item_id, completeness, state, error
               FROM acquisition_records WHERE discovery_id = ? AND provider = 'test-content'""",
            (discovery_id,),
        ).fetchone()
        assert row is not None
        self.assertEqual(row["source_item_id"], acquired_item_id)
        self.assertEqual(row["completeness"], "PARTIAL")
        self.assertEqual(row["state"], "ACQUISITION_FAILED")
        self.assertEqual(row["error"], "transient failure")
        self.assertIn(acquired_item_id, self.repository.extraction_eligible_source_item_ids())


if __name__ == "__main__":
    unittest.main()

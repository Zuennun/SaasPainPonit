import unittest

from problem_intelligence.domain import EvidenceRange, EvidenceScope, ProblemFamily, ProblemType
from problem_intelligence.extraction import ObservationDraft, run_extraction
from problem_intelligence.repository import IntegrityError, Repository


class ManualExtractor:
    version = "manual-test-v1"

    def extract(self, item):
        start = item.raw_text.index("copy invoices")
        return (
            ObservationDraft(
                problem_type=ProblemType.WORKFLOW_GAP,
                problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
                evidence_scope=EvidenceScope.DACH,
                problem="Invoices are copied manually.",
                evidence_ranges=(EvidenceRange(start, start + len("copy invoices")),),
                fields={"frequency": "weekly"},
            ),
        )


class BrokenExtractor:
    version = "broken-v1"

    def extract(self, item):
        return (
            ObservationDraft(
                problem_type=ProblemType.WORKFLOW_GAP,
                problem_family=ProblemFamily.OTHER,
                evidence_scope=EvidenceScope.DACH,
                problem="Unsupported output.",
                evidence_ranges=(),
            ),
        )


class ExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        source_id = self.repository.upsert_source(source_type="forum", name="sample")
        self.item_id = self.repository.upsert_source_item(
            source_id=source_id,
            external_id="one",
            raw_text="Every week we copy invoices by hand.",
            country_code="DE",
            language_code="en",
        )

    def tearDown(self) -> None:
        self.repository.close()

    def test_versioned_run_stores_observation_and_exact_evidence(self) -> None:
        result = run_extraction(
            self.repository, ManualExtractor(), source_item_ids=[self.item_id]
        )

        self.assertEqual(result.processed_items, 1)
        self.assertEqual(result.created_observations, 1)
        run = self.repository.connection.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (result.pipeline_run_id,)
        ).fetchone()
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual(run["version"], "manual-test-v1")
        self.assertEqual(run["input_count"], 1)
        self.assertEqual(run["output_count"], 1)
        observation = self.repository.connection.execute(
            "SELECT * FROM problem_observations WHERE pipeline_run_id = ?",
            (result.pipeline_run_id,),
        ).fetchone()
        self.assertEqual(observation["country_code"], "DE")
        self.assertEqual(observation["frequency"], "weekly")
        evidence = self.repository.connection.execute(
            "SELECT excerpt FROM evidence_spans WHERE observation_id = ?", (observation["id"],)
        ).fetchone()
        self.assertEqual(evidence["excerpt"], "copy invoices")

        repeated = run_extraction(
            self.repository, ManualExtractor(), source_item_ids=[self.item_id]
        )
        self.assertEqual(repeated.pipeline_run_id, result.pipeline_run_id)
        self.assertEqual(self.repository.stats()["pipeline_runs"], 1)
        self.assertEqual(self.repository.stats()["problem_observations"], 1)
        self.assertEqual(self.repository.stats()["evidence_spans"], 1)

    def test_failed_run_is_recorded_and_unsupported_output_is_not_stored(self) -> None:
        with self.assertRaises(IntegrityError):
            run_extraction(self.repository, BrokenExtractor(), source_item_ids=[self.item_id])

        run = self.repository.connection.execute("SELECT * FROM pipeline_runs").fetchone()
        self.assertEqual(run["status"], "FAILED")
        self.assertIn("without evidence", run["error"])
        self.assertEqual(self.repository.stats()["problem_observations"], 0)

    def test_rejects_unknown_source_item_before_creating_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not exist"):
            run_extraction(self.repository, ManualExtractor(), source_item_ids=[999])
        self.assertEqual(self.repository.stats()["pipeline_runs"], 0)


if __name__ == "__main__":
    unittest.main()

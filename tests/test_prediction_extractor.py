import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import BenchmarkValidationError
from problem_intelligence.extraction import run_extraction
from problem_intelligence.prediction_extractor import JsonlPredictionExtractor
from problem_intelligence.repository import Repository


class PredictionExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        source_id = self.repository.upsert_source(source_type="fixture", name="predictions")
        self.text = (
            "Every Friday we manually reconcile invoices for two hours. "
            "We pay a contractor 50 EUR each week."
        )
        self.item_id = self.repository.upsert_source_item(
            source_id=source_id,
            external_id=" Thread-1 ",
            raw_text=self.text,
            country_code="DE",
            language_code="en",
        )
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "predictions.jsonl"

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def write(self, *records: dict) -> None:
        self.path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )

    def positive_record(self) -> dict:
        excerpt = "manually reconcile invoices for two hours"
        start = self.text.index(excerpt)
        payment_excerpt = "pay a contractor 50 EUR each week"
        payment_start = self.text.index(payment_excerpt)
        return {
            "source_item_id": self.item_id,
            "external_id": " Thread-1 ",
            "is_problem": True,
            "problem_type": "WORKFLOW_GAP",
            "problem_family": "RECONCILIATION",
            "evidence_scope": "DACH",
            "problem": "Invoices are reconciled manually.",
            "fields": {"frequency": "weekly", "time_impact": "two hours"},
            "evidence": [
                {"start": start, "end": start + len(excerpt), "excerpt": excerpt},
                {
                    "start": payment_start,
                    "end": payment_start + len(payment_excerpt),
                    "excerpt": payment_excerpt,
                },
            ],
            "workarounds": [
                {
                    "type": "MANUAL_ENTRY",
                    "description": "manual invoice reconciliation",
                    "evidence_index": 0,
                }
            ],
            "impact_signals": [
                {
                    "type": "TIME",
                    "quantified": True,
                    "value": "2",
                    "unit": "hours",
                    "frequency": "weekly",
                    "evidence_index": 0,
                }
            ],
            "payment_signals": [
                {
                    "type": "FREELANCER_SPEND",
                    "amount": "50",
                    "currency": "EUR",
                    "frequency": "weekly",
                    "evidence_index": 1,
                }
            ],
        }

    def test_replays_valid_prediction_through_versioned_pipeline(self) -> None:
        self.write(self.positive_record())
        extractor = JsonlPredictionExtractor(self.path, version="provider-a-v3")

        result = run_extraction(
            self.repository, extractor, source_item_ids=[self.item_id]
        )

        self.assertEqual(result.created_observations, 1)
        observation = self.repository.connection.execute(
            "SELECT * FROM problem_observations WHERE pipeline_run_id = ?",
            (result.pipeline_run_id,),
        ).fetchone()
        self.assertEqual(observation["extraction_version"], "provider-a-v3")
        self.assertEqual(observation["problem_family"], "RECONCILIATION")
        self.assertEqual(observation["ontology_version"], "problem-ontology-v1")
        self.assertEqual(observation["frequency"], "weekly")
        workaround = self.repository.connection.execute(
            "SELECT * FROM workarounds WHERE observation_id = ?", (observation["id"],)
        ).fetchone()
        impact = self.repository.connection.execute(
            "SELECT * FROM impact_signals WHERE observation_id = ?", (observation["id"],)
        ).fetchone()
        payment = self.repository.connection.execute(
            "SELECT * FROM payment_signals WHERE observation_id = ?", (observation["id"],)
        ).fetchone()
        assert workaround is not None and impact is not None and payment is not None
        self.assertEqual(workaround["workaround_type"], "MANUAL_ENTRY")
        self.assertEqual(impact["value"], "2")
        self.assertEqual(impact["unit"], "hours")
        self.assertEqual(payment["payment_type"], "FREELANCER_SPEND")
        self.assertEqual(payment["amount"], "50")
        self.assertEqual(payment["currency"], "EUR")

    def test_invalid_signal_reference_is_rejected_before_pipeline_write(self) -> None:
        record = self.positive_record()
        record["workarounds"][0]["evidence_index"] = 9
        self.write(record)
        with self.assertRaisesRegex(BenchmarkValidationError, "evidence_index"):
            JsonlPredictionExtractor(self.path, version="provider-a-v3")
        self.assertEqual(self.repository.stats()["pipeline_runs"], 0)

    def test_negative_prediction_creates_no_observation(self) -> None:
        self.write(
            {
                "source_item_id": self.item_id,
                "external_id": " Thread-1 ",
                "is_problem": False,
            }
        )
        result = run_extraction(
            self.repository,
            JsonlPredictionExtractor(self.path, version="provider-a-v3"),
            source_item_ids=[self.item_id],
        )
        self.assertEqual(result.created_observations, 0)

    def test_text_mismatch_fails_run_without_storing_output(self) -> None:
        record = self.positive_record()
        record["evidence"][0]["excerpt"] = "fabricated excerpt"
        self.write(record)
        extractor = JsonlPredictionExtractor(self.path, version="provider-a-v3")

        with self.assertRaisesRegex(BenchmarkValidationError, "does not match"):
            run_extraction(self.repository, extractor, source_item_ids=[self.item_id])
        run = self.repository.connection.execute("SELECT * FROM pipeline_runs").fetchone()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(self.repository.stats()["problem_observations"], 0)

    def test_out_of_range_evidence_span_fails_with_located_validation_error(self) -> None:
        record = self.positive_record()
        record["evidence"][0]["end"] = len(self.text) + 1000
        self.write(record)
        extractor = JsonlPredictionExtractor(self.path, version="provider-a-v3")

        with self.assertRaisesRegex(BenchmarkValidationError, "outside source text"):
            run_extraction(self.repository, extractor, source_item_ids=[self.item_id])
        run = self.repository.connection.execute("SELECT * FROM pipeline_runs").fetchone()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(self.repository.stats()["problem_observations"], 0)

    def test_requires_prediction_for_every_selected_item(self) -> None:
        self.write(
            {"source_item_id": 999, "external_id": "different", "is_problem": False}
        )
        extractor = JsonlPredictionExtractor(self.path, version="provider-a-v3")

        with self.assertRaisesRegex(BenchmarkValidationError, "missing source_item_ids"):
            run_extraction(self.repository, extractor, source_item_ids=[self.item_id])


if __name__ == "__main__":
    unittest.main()

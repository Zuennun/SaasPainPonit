from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import BenchmarkValidationError
from problem_intelligence.research_benchmark import (
    evaluate_competition,
    evaluate_dach_transfer,
    load_competition_benchmark,
    load_dach_benchmark,
)

PUBLIC_PROVENANCE = {
    "origin": "PUBLIC_SOURCE",
    "rights_status": "APPROVED",
    "source_url": "https://example.test/research",
    "label_method": "HUMAN",
    "reviewed_by": "test-reviewer",
    "reviewed_at": "2026-09-18",
}


class ResearchBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _jsonl(self, name: str, rows: list[dict[str, object]]) -> Path:
        path = self.root / name
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        return path

    def test_competition_metrics_measure_exact_solution_recall(self) -> None:
        gold_path = self._jsonl(
            "competition-gold.jsonl",
            [
                {
                    "id": "case-1",
                    "evidence_urls": ["https://example.test/research"],
                    "provenance": PUBLIC_PROVENANCE,
                    "solutions": [
                        {
                            "name": "Tool A",
                            "solution_type": "DIRECT_SOFTWARE",
                            "url": "https://example.test/tool-a/",
                        },
                        {
                            "name": "Manual service",
                            "solution_type": "SERVICE_PROVIDER",
                            "url": None,
                        },
                    ],
                }
            ],
        )
        prediction_path = self._jsonl(
            "competition-prediction.jsonl",
            [
                {
                    "id": "case-1",
                    "solutions": [
                        {
                            "name": "tool a",
                            "solution_type": "DIRECT_SOFTWARE",
                            "url": "https://example.test/tool-a",
                        }
                    ],
                }
            ],
        )
        gold = load_competition_benchmark(gold_path)
        prediction = load_competition_benchmark(
            prediction_path, require_evidence=False
        )

        metrics = evaluate_competition(gold, prediction)

        self.assertEqual(metrics["competition_precision"], 1.0)
        self.assertEqual(metrics["competition_recall"], 0.5)
        self.assertEqual(metrics["exact_case_accuracy"], 0.0)

    def test_dach_metrics_keep_each_classification_dimension_separate(self) -> None:
        gold_path = self._jsonl(
            "dach-gold.jsonl",
            [
                {
                    "id": "case-1",
                    "evidence_urls": ["https://example.test/dach-research"],
                    "provenance": {
                        **PUBLIC_PROVENANCE,
                        "source_url": "https://example.test/dach-research",
                    },
                    "actor_equivalence": "UNCLEAR",
                    "workflow_equivalence": "DIRECT",
                    "transfer_type": "WEAK_LOCAL_EVIDENCE",
                    "local_evidence_state": "SINGLE_LOCAL_SIGNAL",
                }
            ],
        )
        prediction_path = self._jsonl(
            "dach-prediction.jsonl",
            [
                {
                    "id": "case-1",
                    "actor_equivalence": "UNCLEAR",
                    "workflow_equivalence": "DIRECT",
                    "transfer_type": "DIRECT_TRANSFER",
                    "local_evidence_state": "SINGLE_LOCAL_SIGNAL",
                }
            ],
        )
        gold = load_dach_benchmark(gold_path)
        prediction = load_dach_benchmark(prediction_path, require_evidence=False)

        metrics = evaluate_dach_transfer(gold, prediction)

        self.assertEqual(metrics["actor_equivalence_accuracy"], 1.0)
        self.assertEqual(metrics["workflow_equivalence_accuracy"], 1.0)
        self.assertEqual(metrics["transfer_type_accuracy"], 0.0)
        self.assertEqual(metrics["local_evidence_state_accuracy"], 1.0)
        self.assertEqual(metrics["exact_case_accuracy"], 0.0)

    def test_gold_labels_require_research_urls_and_unique_ids(self) -> None:
        missing_evidence = self._jsonl(
            "missing-evidence.jsonl",
            [{"id": "case-1", "solutions": []}],
        )
        with self.assertRaisesRegex(BenchmarkValidationError, "evidence_urls"):
            load_competition_benchmark(missing_evidence)

        duplicate = self._jsonl(
            "duplicate.jsonl",
            [
                {
                    "id": "case-1",
                    "evidence_urls": ["https://example.test/one"],
                    "provenance": {
                        **PUBLIC_PROVENANCE,
                        "source_url": "https://example.test/one",
                    },
                    "actor_equivalence": "UNCLEAR",
                    "workflow_equivalence": "UNKNOWN",
                    "transfer_type": "UNKNOWN",
                    "local_evidence_state": "NONE_FOUND",
                },
                {
                    "id": "case-1",
                    "evidence_urls": ["https://example.test/two"],
                    "provenance": {
                        **PUBLIC_PROVENANCE,
                        "source_url": "https://example.test/two",
                    },
                    "actor_equivalence": "UNCLEAR",
                    "workflow_equivalence": "UNKNOWN",
                    "transfer_type": "UNKNOWN",
                    "local_evidence_state": "NONE_FOUND",
                },
            ],
        )
        with self.assertRaisesRegex(BenchmarkValidationError, "duplicate benchmark id"):
            load_dach_benchmark(duplicate)


if __name__ == "__main__":
    unittest.main()

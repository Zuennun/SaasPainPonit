from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import BenchmarkValidationError
from problem_intelligence.cli import main
from problem_intelligence.evaluation_readiness import evaluate_readiness


class EvaluationReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path(__file__).parents[1]
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manifest(self, suites: list[dict[str, object]]) -> Path:
        path = self.root / "readiness.json"
        path.write_text(
            json.dumps({"version": "test-v1", "suites": suites}), encoding="utf-8"
        )
        return path

    def test_checked_in_policy_truthfully_blocks_scale(self) -> None:
        manifest = self.project_root / "benchmarks/readiness_v1.json"

        result = evaluate_readiness(manifest)

        self.assertFalse(result.ready_for_scale)
        self.assertEqual(len(result.suites), 5)
        problem = next(item for item in result.suites if item.name == "problem_detection")
        self.assertEqual(problem.coverage["cases"], 7)
        self.assertEqual(problem.coverage["manually_labeled_cases"], 7)
        self.assertEqual(problem.coverage["permissioned_human_reviewed_cases"], 1)
        self.assertIsNone(problem.metrics)
        clustering = next(item for item in result.suites if item.name == "clustering")
        self.assertIsNotNone(clustering.metrics)
        self.assertGreater(result.to_dict()["failed_gate_count"], 0)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "evaluation-readiness",
                    "--manifest",
                    str(manifest),
                    "--require-ready",
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertFalse(json.loads(output.getvalue())["ready_for_scale"])

    def test_all_supported_suite_kinds_can_pass_explicit_gates(self) -> None:
        benchmark = self.project_root / "benchmarks/problem_detection_v1.jsonl"
        clustering = self.project_root / "benchmarks/clustering_v1.jsonl"
        competition = self.project_root / "benchmarks/competition_v1.jsonl"
        dach = self.project_root / "benchmarks/dach_transfer_v1.jsonl"
        manifest = self._manifest(
            [
                {
                    "name": "problem",
                    "kind": "problem",
                    "fixture": str(benchmark),
                    "predictions": str(benchmark),
                    "minimum_coverage": {
                        "cases": 6,
                        "negative_cases": 2,
                        "manually_labeled_cases": 6,
                        "permissioned_human_reviewed_cases": 0,
                    },
                    "minimum_metrics": {
                        "detection_f1": 1.0,
                        "field_exact_accuracy": 1.0,
                    },
                },
                {
                    "name": "clustering",
                    "kind": "clustering",
                    "fixture": str(clustering),
                    "predictions": None,
                    "minimum_coverage": {
                        "cases": 6,
                        "positive_pairs": 2,
                        "manually_labeled_cases": 6,
                        "permissioned_human_reviewed_cases": 0,
                    },
                    "minimum_metrics": {"pairwise_f1": 1.0},
                },
                {
                    "name": "competition",
                    "kind": "competition",
                    "fixture": str(competition),
                    "predictions": str(competition),
                    "minimum_coverage": {
                        "cases": 1,
                        "solutions": 2,
                        "manually_labeled_cases": 1,
                        "permissioned_human_reviewed_cases": 0,
                    },
                    "minimum_metrics": {"competition_recall": 1.0},
                },
                {
                    "name": "dach",
                    "kind": "dach_transfer",
                    "fixture": str(dach),
                    "predictions": str(dach),
                    "minimum_coverage": {
                        "cases": 1,
                        "distinct_transfer_types": 1,
                        "manually_labeled_cases": 1,
                        "permissioned_human_reviewed_cases": 0,
                    },
                    "minimum_metrics": {"exact_case_accuracy": 1.0},
                },
            ]
        )

        result = evaluate_readiness(manifest)

        self.assertTrue(result.ready_for_scale)
        self.assertEqual(result.to_dict()["failed_gate_count"], 0)

    def test_unknown_gate_name_is_rejected(self) -> None:
        benchmark = self.project_root / "benchmarks/problem_detection_v1.jsonl"
        manifest = self._manifest(
            [
                {
                    "name": "invalid",
                    "kind": "problem",
                    "fixture": str(benchmark),
                    "predictions": None,
                    "minimum_coverage": {
                        "imaginary_cases": 1,
                        "manually_labeled_cases": 0,
                        "permissioned_human_reviewed_cases": 0,
                    },
                    "minimum_metrics": {"detection_f1": 0.8},
                }
            ]
        )

        with self.assertRaisesRegex(BenchmarkValidationError, "unsupported coverage"):
            evaluate_readiness(manifest)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import BenchmarkValidationError, load_benchmark
from problem_intelligence.evaluation import evaluate_predictions, load_predictions

FIXTURE = Path(__file__).parents[1] / "benchmarks" / "problem_detection_v1.jsonl"


def prediction_record(case):
    return {
        "id": case.case_id,
        "is_problem": case.is_problem,
        "problem_type": case.problem_type.value if case.problem_type else None,
        "problem_family": case.problem_family.value if case.problem_family else None,
        "evidence_scope": case.evidence_scope.value if case.evidence_scope else None,
        "problem": case.problem,
        "fields": case.fields,
        "evidence": [
            {"start": item.range.start, "end": item.range.end, "excerpt": item.excerpt}
            for item in case.evidence
        ],
    }


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load_benchmark(FIXTURE)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "predictions.jsonl"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_predictions(self, records) -> None:
        self.path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )

    def test_perfect_predictions_score_one_for_every_metric(self) -> None:
        self.write_predictions(prediction_record(case) for case in self.cases)
        result = evaluate_predictions(self.cases, load_predictions(self.path, self.cases))

        metric_suffixes = ("accuracy", "precision", "recall", "f1")
        metric_values = [
            value for name, value in result.items() if name.endswith(metric_suffixes)
        ]
        self.assertTrue(metric_values)
        self.assertTrue(all(value == 1.0 for value in metric_values))

    def test_false_positive_and_missing_extraction_are_penalized(self) -> None:
        records = [prediction_record(case) for case in self.cases]
        records[0].update(
            {
                "problem_type": None,
                "problem_family": None,
                "evidence_scope": None,
                "problem": None,
                "fields": {},
                "evidence": [],
            }
        )
        records[2].update(
            {
                "is_problem": True,
                "problem_type": "SUPPORT_QUESTION",
                "problem_family": "OTHER",
                "evidence_scope": "GLOBAL",
                "problem": "A question was asked.",
            }
        )
        self.write_predictions(records)
        result = evaluate_predictions(self.cases, load_predictions(self.path, self.cases))

        self.assertEqual(result["false_positives"], 1)
        self.assertLess(result["detection_precision"], 1.0)
        self.assertLess(result["problem_type_accuracy"], 1.0)
        self.assertLess(result["evidence_recall"], 1.0)

    def test_requires_one_prediction_for_every_case(self) -> None:
        self.write_predictions([prediction_record(self.cases[0])])
        predictions = load_predictions(self.path, self.cases)
        with self.assertRaisesRegex(BenchmarkValidationError, "missing predictions"):
            evaluate_predictions(self.cases, predictions)


if __name__ == "__main__":
    unittest.main()

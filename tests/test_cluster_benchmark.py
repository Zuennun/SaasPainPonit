import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import BenchmarkValidationError
from problem_intelligence.cluster_benchmark import (
    evaluate_exact_clustering,
    load_clustering_benchmark,
)

FIXTURE = Path(__file__).parents[1] / "benchmarks" / "clustering_v1.jsonl"


class ClusteringBenchmarkTests(unittest.TestCase):
    def test_exact_baseline_scores_perfectly_on_normalization_cases(self) -> None:
        cases = load_clustering_benchmark(FIXTURE)
        result = evaluate_exact_clustering(cases)

        self.assertEqual(result["cases"], 6)
        self.assertEqual(result["pairs"], 15)
        self.assertEqual(result["pairwise_precision"], 1.0)
        self.assertEqual(result["pairwise_recall"], 1.0)
        self.assertEqual(result["pairwise_f1"], 1.0)

    def test_requires_at_least_two_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.jsonl"
            path.write_text(
                '{"id":"one","problem_type":"WORKFLOW_GAP",'
                '"problem":"one","expected_cluster":"one",'
                '"provenance":{"origin":"SYNTHETIC",'
                '"rights_status":"NOT_APPLICABLE","source_url":null,'
                '"label_method":"HUMAN","reviewed_by":"test-reviewer",'
                '"reviewed_at":"2026-09-18"}}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchmarkValidationError, "at least two"):
                load_clustering_benchmark(path)


if __name__ == "__main__":
    unittest.main()

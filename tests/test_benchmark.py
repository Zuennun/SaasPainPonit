import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.benchmark import (
    BenchmarkValidationError,
    benchmark_summary,
    load_benchmark,
)
from problem_intelligence.domain import EvidenceScope, ProblemFamily, ProblemType

FIXTURE = Path(__file__).parents[1] / "benchmarks" / "problem_detection_v1.jsonl"
SYNTHETIC_PROVENANCE = {
    "origin": "SYNTHETIC",
    "rights_status": "NOT_APPLICABLE",
    "source_url": None,
    "label_method": "HUMAN",
    "reviewed_by": "test-reviewer",
    "reviewed_at": "2026-09-18",
}


class BenchmarkTests(unittest.TestCase):
    def test_repository_fixture_is_valid_and_balanced(self) -> None:
        cases = load_benchmark(FIXTURE)
        self.assertEqual(
            benchmark_summary(cases),
            {
                "cases": 7,
                "positive_cases": 4,
                "negative_cases": 3,
                "evidence_spans": 4,
                "permissioned_cases": 1,
                "human_reviewed_cases": 7,
                "manually_labeled_cases": 7,
                "permissioned_human_reviewed_cases": 1,
            },
        )
        self.assertEqual(cases[0].problem_type, ProblemType.WORKFLOW_GAP)
        self.assertEqual(cases[0].problem_family, ProblemFamily.MANUAL_DATA_ENTRY)
        self.assertEqual(cases[0].evidence_scope, EvidenceScope.DACH)
        self.assertTrue(cases[-1].provenance.permissioned)

    def test_rejects_evidence_that_does_not_match_source_text(self) -> None:
        record = {
            "id": "bad-span",
            "text": "manual copying",
            "is_problem": True,
            "problem_type": "WORKFLOW_GAP",
            "problem_family": "MANUAL_DATA_ENTRY",
            "evidence_scope": "GLOBAL",
            "problem": "Manual copying.",
            "fields": {},
            "evidence": [{"start": 0, "end": 6, "excerpt": "wrong!"}],
            "provenance": SYNTHETIC_PROVENANCE,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "does not match"):
                load_benchmark(path)

    def test_rejects_labels_on_negative_case(self) -> None:
        record = {
            "id": "not-a-problem",
            "text": "Where is the export button?",
            "is_problem": False,
            "fields": {"actor": "user"},
            "provenance": SYNTHETIC_PROVENANCE,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "negative case"):
                load_benchmark(path)

    def test_positive_case_requires_problem_family(self) -> None:
        record = {
            "id": "missing-family",
            "text": "We copy every invoice manually.",
            "is_problem": True,
            "problem_type": "WORKFLOW_GAP",
            "evidence_scope": "GLOBAL",
            "problem": "Invoices are copied manually.",
            "fields": {},
            "evidence": [{"start": 3, "end": 30, "excerpt": "copy every invoice manually"}],
            "provenance": SYNTHETIC_PROVENANCE,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "problem_family"):
                load_benchmark(path)

    def test_rejects_duplicate_case_ids(self) -> None:
        record = {
            "id": "duplicate",
            "text": "A question",
            "is_problem": False,
            "provenance": SYNTHETIC_PROVENANCE,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jsonl"
            path.write_text("\n".join((json.dumps(record), json.dumps(record))), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "duplicate id"):
                load_benchmark(path)

    def test_provenance_is_required_and_synthetic_cannot_claim_source_rights(self) -> None:
        missing = {"id": "missing", "text": "A question", "is_problem": False}
        invalid = {
            **missing,
            "id": "invalid",
            "provenance": {
                **SYNTHETIC_PROVENANCE,
                "rights_status": "APPROVED",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.jsonl"
            missing_path.write_text(json.dumps(missing) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "provenance"):
                load_benchmark(missing_path)
            invalid_path = Path(directory) / "invalid.jsonl"
            invalid_path.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkValidationError, "SYNTHETIC"):
                load_benchmark(invalid_path)


if __name__ == "__main__":
    unittest.main()

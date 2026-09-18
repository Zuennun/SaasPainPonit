import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from problem_intelligence.cli import main


class CliWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "workflow.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_json(self, *arguments: str) -> dict[str, Any]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([*arguments, "--database", str(self.database)])
        self.assertEqual(result, 0)
        parsed = json.loads(output.getvalue())
        self.assertIsInstance(parsed, dict)
        return parsed

    def test_manual_evidence_workflow_is_operable_from_cli(self) -> None:
        text = (
            "We manually reconcile every invoice for two hours each Friday "
            "and pay 20 EUR weekly."
        )
        ingested = self.run_json(
            "ingest-item",
            "--source-type",
            "interview",
            "--source-name",
            "manual research",
            "--external-id",
            "interview-1",
            "--text",
            text,
            "--country",
            "DE",
        )
        source_item_id = int(ingested["source_item_id"])
        observation = self.run_json(
            "add-observation",
            "--source-item-id",
            str(source_item_id),
            "--problem-type",
            "WORKFLOW_GAP",
            "--problem-family",
            "RECONCILIATION",
            "--evidence-scope",
            "DACH",
            "--problem",
            "Invoices are reconciled manually.",
            "--fields-json",
            '{"frequency":"weekly","country_code":"DE"}',
        )
        excerpt = "manually reconcile every invoice for two hours"
        start = text.index(excerpt)
        evidence = self.run_json(
            "add-evidence",
            "--source-item-id",
            str(source_item_id),
            "--observation-id",
            str(observation["observation_id"]),
            "--start",
            str(start),
            "--end",
            str(start + len(excerpt)),
            "--evidence-scope",
            "DACH",
        )
        payment_excerpt = "pay 20 EUR weekly"
        payment_start = text.index(payment_excerpt)
        payment_evidence = self.run_json(
            "add-evidence",
            "--source-item-id",
            str(source_item_id),
            "--observation-id",
            str(observation["observation_id"]),
            "--start",
            str(payment_start),
            "--end",
            str(payment_start + len(payment_excerpt)),
            "--evidence-scope",
            "DACH",
        )
        self.run_json(
            "add-workaround",
            "--observation-id",
            str(observation["observation_id"]),
            "--evidence-id",
            str(evidence["evidence_id"]),
            "--type",
            "MANUAL_ENTRY",
            "--description",
            "manual invoice reconciliation",
        )
        self.run_json(
            "add-impact",
            "--observation-id",
            str(observation["observation_id"]),
            "--evidence-id",
            str(evidence["evidence_id"]),
            "--type",
            "TIME",
            "--quantified",
            "--value",
            "2",
            "--unit",
            "hours",
            "--frequency",
            "weekly",
        )
        self.run_json(
            "add-payment",
            "--observation-id",
            str(observation["observation_id"]),
            "--evidence-id",
            str(payment_evidence["evidence_id"]),
            "--type",
            "EXPLICIT_BUDGET",
            "--amount",
            "20",
            "--currency",
            "EUR",
            "--frequency",
            "weekly",
        )
        claim = self.run_json(
            "create-claim",
            "--claim-kind",
            "FACT",
            "--observation-id",
            str(observation["observation_id"]),
            "--evidence-id",
            str(evidence["evidence_id"]),
            "--text",
            "The source reports manual invoice reconciliation.",
        )

        self.assertGreater(int(claim["claim_id"]), 0)
        stats = self.run_json("stats")
        self.assertEqual(stats["source_items"], 1)
        self.assertEqual(stats["problem_observations"], 1)
        self.assertEqual(stats["evidence_spans"], 2)
        self.assertEqual(stats["claims"], 1)
        self.assertEqual(stats["workarounds"], 1)
        self.assertEqual(stats["impact_signals"], 1)
        self.assertEqual(stats["payment_signals"], 1)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["export-items", "--database", str(self.database)])
        self.assertEqual(result, 0)
        exported = json.loads(output.getvalue())
        self.assertEqual(exported["source_item_id"], source_item_id)
        self.assertEqual(exported["external_id"], "interview-1")
        self.assertEqual(exported["text"], text)

    def test_source_policy_audit_flags_approved_source_missing_rights_fields(self) -> None:
        jsonl_path = Path(self.temporary_directory.name) / "items.jsonl"
        jsonl_path.write_text(
            json.dumps({"external_id": "p1", "text": "We reconcile invoices manually."}) + "\n",
            encoding="utf-8",
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "ingest-jsonl",
                    "--database",
                    str(self.database),
                    "--file",
                    str(jsonl_path),
                    "--source-type",
                    "forum",
                    "--source-name",
                    "rights-incomplete",
                    "--commercial-use-status",
                    "APPROVED",
                ]
            )
        self.assertEqual(result, 0)

        audit = self.run_json("source-policy-audit")
        self.assertFalse(audit["clean"])
        self.assertEqual(audit["violation_count"], 1)
        violation = audit["violations"][0]
        self.assertTrue(violation["approved_status_without_complete_policy"])
        self.assertIn("retention_rules", violation["missing_fields"])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "source-policy-audit",
                    "--database",
                    str(self.database),
                    "--fail-on-violation",
                ]
            )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.connectors import ConnectorDataError, ResearchJsonlCapture
from problem_intelligence.ingestion import ingest_research_capture
from problem_intelligence.repository import Repository


class ResearchCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "research.jsonl"

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def source(self, name: str) -> dict[str, str]:
        return {
            "source_type": "official-documentation",
            "name": name,
            "access_method": "operator-reviewed-public-page",
            "commercial_use_status": "UNKNOWN_REQUIRES_REVIEW",
            "retention_rules": "retain excerpt and URL while research case is active",
            "attribution_requirements": "display publisher and source URL",
            "quoting_rules": "short attributed excerpt only",
            "deletion_requirements": "recheck or remove when source is withdrawn",
            "rate_limit_notes": "not applicable to captured operator review",
            "rights_reviewed_at": "2026-09-18",
        }

    def test_heterogeneous_capture_is_fully_policy_annotated_and_idempotent(self) -> None:
        records = [
            {
                "source": self.source("Publisher A"),
                "item": {
                    "external_id": "page-a",
                    "text": "A connector can automate report data collection.",
                    "url": "https://example.test/a",
                    "language_code": "en",
                },
            },
            {
                "source": self.source("Publisher B"),
                "item": {
                    "external_id": "page-b",
                    "text": "Berichtsdaten werden teilweise manuell zusammenkopiert.",
                    "url": "https://example.test/b",
                    "country_code": "DE",
                    "language_code": "de",
                },
            },
        ]
        self.path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

        first = ingest_research_capture(self.repository, ResearchJsonlCapture(self.path))
        second = ingest_research_capture(self.repository, self.path)

        self.assertEqual(first.source_ids, second.source_ids)
        self.assertEqual(first.source_item_ids, second.source_item_ids)
        self.assertEqual(first.processed_sources, 2)
        self.assertEqual(first.processed_items, 2)
        self.assertEqual(self.repository.stats()["sources"], 2)
        source = self.repository.connection.execute(
            """SELECT commercial_use_status, quoting_rules, deletion_requirements,
                      rate_limit_notes, rights_reviewed_at
               FROM sources WHERE id = ?""",
            (first.source_ids[0],),
        ).fetchone()
        self.assertEqual(source["commercial_use_status"], "UNKNOWN_REQUIRES_REVIEW")
        self.assertEqual(source["quoting_rules"], "short attributed excerpt only")
        self.assertEqual(source["rights_reviewed_at"], "2026-09-18")

    def test_missing_policy_is_rejected_before_any_write(self) -> None:
        source = self.source("Incomplete Publisher")
        del source["quoting_rules"]
        records = [
            {
                "source": self.source("Valid Publisher"),
                "item": {"external_id": "valid", "text": "Valid text."},
            },
            {
                "source": source,
                "item": {"external_id": "invalid", "text": "Invalid policy."},
            },
        ]
        self.path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ConnectorDataError, "missing policy fields: quoting_rules"):
            ingest_research_capture(self.repository, self.path)
        self.assertEqual(self.repository.stats()["sources"], 0)
        self.assertEqual(self.repository.stats()["source_items"], 0)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.connectors import (
    ConnectorDataError,
    JsonlFileConnector,
    SourceDescriptor,
)
from problem_intelligence.ingestion import ingest
from problem_intelligence.repository import Repository


class JsonlIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "items.jsonl"
        self.source = SourceDescriptor(
            source_type="operator export",
            name="research sample",
            access_method="operator-supplied-local-jsonl",
            commercial_use_status="operator-confirmed",
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def test_ingests_jsonl_idempotently_through_provider_boundary(self) -> None:
        records = [
            {
                "external_id": "thread-1",
                "text": "We copy every invoice manually.",
                "url": "https://example.test/thread-1#reply",
                "country_code": "DE",
                "metadata": {"votes": 7},
            },
            {"external_id": "thread-2", "text": "Imports lose our custom fields."},
        ]
        self.path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )
        connector = JsonlFileConnector(self.path, source=self.source)

        first = ingest(self.repository, connector)
        second = ingest(self.repository, connector)

        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(first.source_item_ids, second.source_item_ids)
        self.assertEqual(first.processed_items, 2)
        self.assertEqual(self.repository.stats()["source_items"], 2)
        source = self.repository.connection.execute(
            "SELECT access_method, commercial_use_status FROM sources WHERE id = ?",
            (first.source_id,),
        ).fetchone()
        self.assertEqual(source["access_method"], "operator-supplied-local-jsonl")
        self.assertEqual(source["commercial_use_status"], "operator-confirmed")

    def test_rejects_unknown_fields_instead_of_silently_dropping_them(self) -> None:
        self.path.write_text(
            json.dumps({"external_id": "one", "text": "Text", "surprise": True}),
            encoding="utf-8",
        )
        connector = JsonlFileConnector(self.path, source=self.source)

        with self.assertRaisesRegex(ConnectorDataError, "unknown fields"):
            list(connector.iter_items())

    def test_reports_line_number_for_invalid_json(self) -> None:
        self.path.write_text('{"external_id":"one","text":"ok"}\nnot-json\n', encoding="utf-8")
        connector = JsonlFileConnector(self.path, source=self.source)

        with self.assertRaisesRegex(ConnectorDataError, r"items.jsonl:2: invalid JSON"):
            ingest(self.repository, connector)
        self.assertEqual(self.repository.stats()["sources"], 0)
        self.assertEqual(self.repository.stats()["source_items"], 0)


if __name__ == "__main__":
    unittest.main()

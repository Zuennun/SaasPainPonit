from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from problem_intelligence.repository import IntegrityError, Repository
from problem_intelligence.source_health import (
    AccessResult,
    HealthCapture,
    HealthStatus,
    JsonlHealthProvider,
    classify_health,
    run_health_checks,
    select_health_sources,
)


def capture(source: str = "r/Accounting") -> HealthCapture:
    return HealthCapture(
        source=source,
        provider="public-search",
        checked_at="2026-09-19T12:00:00Z",
        access_result=AccessResult.PUBLIC_CONTENT,
        http_status=200,
        latest_visible_item_at="2026-09-14T00:00:00Z",
        visible_item_count=1,
        sample_window_start="2026-08-20T00:00:00Z",
        sample_window_end="2026-09-19T12:00:00Z",
        coverage_complete=False,
        reason="One recent public post is visible in a search result.",
        evidence_urls=("https://www.reddit.com/r/Accounting/comments/1wfy7n6/",),
        latency_ms=None,
        cost_usd=None,
    )


class SourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = Repository(self.root / "health.db")
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(source_type="reddit", name="r/Accounting")

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def _provider(self, *values: HealthCapture) -> JsonlHealthProvider:
        path = self.root / "capture.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(
                    {
                        **{key: getattr(value, key) for key in value.__dataclass_fields__},
                        "access_result": value.access_result.value,
                    }
                )
                for value in values
            )
            + "\n",
            encoding="utf-8",
        )
        return JsonlHealthProvider(path)

    def test_health_states_do_not_confuse_empty_results_with_failed_retrieval(self) -> None:
        base = capture()
        self.assertEqual(classify_health(base).status, HealthStatus.ACTIVE)
        self.assertEqual(
            classify_health(replace(base, access_result=AccessResult.ACCESS_RESTRICTED)).status,
            HealthStatus.ACCESS_RESTRICTED,
        )
        self.assertEqual(
            classify_health(replace(base, access_result=AccessResult.SOURCE_NOT_FOUND)).status,
            HealthStatus.SOURCE_UNAVAILABLE,
        )
        self.assertEqual(
            classify_health(replace(base, access_result=AccessResult.PROVIDER_FAILED)).status,
            HealthStatus.UNKNOWN,
        )
        no_recent = replace(
            base,
            access_result=AccessResult.PUBLIC_NO_RECENT,
            latest_visible_item_at=None,
            visible_item_count=0,
            evidence_urls=(),
            coverage_complete=True,
        )
        self.assertEqual(classify_health(no_recent).status, HealthStatus.INACTIVE_OR_LOW_ACTIVITY)
        self.assertEqual(
            classify_health(replace(no_recent, coverage_complete=False)).status,
            HealthStatus.UNKNOWN,
        )

    def test_health_history_is_persistent_and_exact_replay_is_idempotent(self) -> None:
        selected = select_health_sources(self.repository, source="Accounting")
        self.assertEqual(selected, ((self.source_id, "r/Accounting"),))
        first = run_health_checks(self.repository, self._provider(capture()), selected)
        replay = run_health_checks(self.repository, self._provider(capture()), selected)
        self.assertEqual(first, replay)
        self.assertEqual(self.repository.stats()["source_health_checks"], 1)
        second_capture = replace(
            capture(),
            checked_at="2026-09-20T12:00:00Z",
            access_result=AccessResult.ACCESS_RESTRICTED,
            reason="Provider explicitly reports restricted access.",
        )
        run_health_checks(self.repository, self._provider(second_capture), selected)
        statuses = [
            row[0]
            for row in self.repository.connection.execute(
                "SELECT health_status FROM source_health_checks ORDER BY checked_at"
            )
        ]
        self.assertEqual(statuses, ["ACTIVE", "ACCESS_RESTRICTED"])
        with self.assertRaisesRegex(IntegrityError, "different evidence"):
            run_health_checks(
                self.repository,
                self._provider(replace(capture(), reason="A conflicting replay.")),
                selected,
            )

    def test_manifest_selection_and_missing_capture_prevalidate_all_writes(self) -> None:
        second = self.repository.upsert_source(source_type="reddit", name="r/HVAC")
        manifest = self.root / "manifest.csv"
        manifest.write_text("source,target_items\nr/Accounting,120\nr/HVAC,120\n", encoding="utf-8")
        selected = select_health_sources(self.repository, manifest=manifest)
        self.assertEqual(selected, ((self.source_id, "r/Accounting"), (second, "r/HVAC")))
        with self.assertRaisesRegex(ValueError, "lacks source"):
            run_health_checks(self.repository, self._provider(capture()), selected)
        self.assertEqual(self.repository.stats()["source_health_checks"], 0)
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            self._provider(capture(), capture())

    def test_schema_21_registry_without_strict_reason_is_repaired(self) -> None:
        self.repository.connection.execute(
            "ALTER TABLE source_registry_profiles DROP COLUMN strict_reason"
        )
        self.repository.connection.execute("PRAGMA user_version = 21")
        self.repository.initialize()
        columns = {
            row["name"]
            for row in self.repository.connection.execute(
                "PRAGMA table_info(source_registry_profiles)"
            )
        }
        self.assertIn("strict_reason", columns)
        self.assertEqual(
            self.repository.connection.execute("PRAGMA user_version").fetchone()[0], 23
        )


if __name__ == "__main__":
    unittest.main()

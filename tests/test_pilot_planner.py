from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.cli import main
from problem_intelligence.pilot_planner import build_pilot_plan
from problem_intelligence.repository import Repository
from problem_intelligence.source_import import import_subreddit_csv

_HEADER = (
    "subreddit,kategorie,zielgruppe,strict_relevance,strict_reason,recommended_action,"
    "aktivitaet,scan_now,pilot_posts,strict_pilot_posts,source_url\n"
)


def _row(
    name: str,
    *,
    kategorie: str = "Ops",
    zielgruppe: str = "Owners",
    strict_relevance: str,
    reason: str = "Because reasons.",
    recommended_action: str,
    aktivitaet: str = "ACTIVE_VERIFIED_2026-09",
    scan_now: str = "JA",
    pilot_posts: str = "150",
    strict_pilot_posts: str = "0",
) -> str:
    return (
        f"{name},{kategorie},{zielgruppe},{strict_relevance},{reason},{recommended_action},"
        f"{aktivitaet},{scan_now},{pilot_posts},{strict_pilot_posts},"
        f"https://www.reddit.com/{name}/\n"
    )


class PilotPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def _write_registry(self, name: str, rows: list[str]) -> Path:
        path = self.directory / name
        path.write_text(_HEADER + "".join(rows), encoding="utf-8")
        return path

    def _mixed_registry(self) -> Path:
        return self._write_registry(
            "mixed.csv",
            [
                _row(
                    "r/Core",
                    strict_relevance="CORE",
                    recommended_action="SCAN_PILOT_NOW",
                    strict_pilot_posts="300",
                    reason="Strong operator pain signal.",
                ),
                _row(
                    "r/CoreUnverified",
                    strict_relevance="CORE",
                    recommended_action="VERIFY_ACTIVITY_THEN_SCAN",
                    aktivitaet="PRUEFEN",
                ),
                _row(
                    "r/Pilot",
                    strict_relevance="PILOT",
                    recommended_action="SCAN_SMALL_PILOT",
                    strict_pilot_posts="150",
                ),
                _row(
                    "r/Secondary",
                    strict_relevance="SECONDARY",
                    recommended_action="DO_NOT_CONTINUOUSLY_SCAN",
                ),
                _row(
                    "r/Dropped",
                    strict_relevance="DROP",
                    recommended_action="EXCLUDE",
                ),
                _row(
                    "r/Recheck",
                    strict_relevance="RECHECK_ACCESS",
                    recommended_action="VERIFY_ACCESS",
                    strict_pilot_posts="0",
                    reason="Access appears restricted.",
                ),
            ],
        )

    def test_clean_import_and_plan(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        names = [entry.source_name for entry in plan.entries]
        self.assertIn("r/Core", names)
        self.assertIn("r/CoreUnverified", names)
        self.assertIn("r/Pilot", names)

    def test_drop_sources_are_excluded_from_the_plan(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        self.assertNotIn("r/Dropped", [entry.source_name for entry in plan.entries])

    def test_recheck_access_sources_are_excluded_from_the_plan(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        self.assertNotIn("r/Recheck", [entry.source_name for entry in plan.entries])

    def test_secondary_sources_are_excluded_from_the_primary_pilot(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        self.assertNotIn("r/Secondary", [entry.source_name for entry in plan.entries])
        self.assertNotIn("r/Secondary", [entry.source_name for entry in plan.manifest])

    def test_core_sources_are_ordered_before_pilot_sources(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        relevance_sequence = [entry.relevance_status for entry in plan.entries]
        first_pilot_index = relevance_sequence.index("PILOT")
        self.assertTrue(
            all(state == "CORE" for state in relevance_sequence[:first_pilot_index])
        )

    def test_ready_core_sources_are_ordered_before_unverified_core_sources(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        core_entries = [entry for entry in plan.entries if entry.relevance_status == "CORE"]
        ready_flags = [entry.ready for entry in core_entries]
        self.assertEqual(ready_flags, sorted(ready_flags, reverse=True))

    def test_manifest_excludes_sources_not_yet_ready(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        manifest_names = [entry.source_name for entry in plan.manifest]
        self.assertIn("r/Core", manifest_names)
        self.assertIn("r/Pilot", manifest_names)
        self.assertNotIn("r/CoreUnverified", manifest_names)

    def test_manifest_pilot_sizes_come_from_the_strict_audit(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        sizes = {entry.source_name: entry.pilot_size for entry in plan.manifest}
        self.assertEqual(sizes["r/Core"], 300)
        self.assertEqual(sizes["r/Pilot"], 150)

    def test_access_status_flags_recheck_access_recommendation(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        core_unverified = next(
            entry for entry in plan.entries if entry.source_name == "r/CoreUnverified"
        )
        self.assertEqual(core_unverified.access_status, "NOT_FLAGGED")
        ready_core = next(entry for entry in plan.entries if entry.source_name == "r/Core")
        self.assertEqual(ready_core.access_status, "NOT_FLAGGED")

    def test_reason_prefers_strict_reason_over_rationale(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        entry = next(entry for entry in plan.entries if entry.source_name == "r/Core")
        self.assertEqual(entry.reason, "Strong operator pain signal.")

    def test_ordering_is_deterministic_across_repeated_builds(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        first = build_pilot_plan(self.repository)
        second = build_pilot_plan(self.repository)

        self.assertEqual(
            [entry.source_name for entry in first.entries],
            [entry.source_name for entry in second.entries],
        )
        self.assertEqual(
            [entry.ordering for entry in first.entries],
            [entry.ordering for entry in second.entries],
        )

    def test_repeated_import_is_idempotent_and_does_not_duplicate_sources(self) -> None:
        path = self._mixed_registry()
        first_ids = import_subreddit_csv(self.repository, path)
        second_ids = import_subreddit_csv(self.repository, path)

        self.assertEqual(first_ids, second_ids)
        self.assertEqual(self.repository.stats()["sources"], 6)

        plan_after_first = build_pilot_plan(self.repository)
        plan_after_second = build_pilot_plan(self.repository)
        self.assertEqual(plan_after_first.to_dict(), plan_after_second.to_dict())

    def test_duplicate_subreddit_spellings_canonicalize_to_one_source(self) -> None:
        path = self._write_registry(
            "dupes.csv",
            [
                _row("r/Core", strict_relevance="CORE", recommended_action="SCAN_PILOT_NOW"),
                _row("R/CORE", strict_relevance="CORE", recommended_action="SCAN_PILOT_NOW"),
            ],
        )
        import_subreddit_csv(self.repository, path)

        self.assertEqual(self.repository.stats()["sources"], 1)

    def test_curated_status_updates_on_reimport(self) -> None:
        first_path = self._write_registry(
            "first.csv",
            [_row("r/Shifting", strict_relevance="PILOT", recommended_action="SCAN_SMALL_PILOT")],
        )
        import_subreddit_csv(self.repository, first_path)

        second_path = self._write_registry(
            "second.csv",
            [
                _row(
                    "r/Shifting",
                    strict_relevance="CORE",
                    recommended_action="SCAN_PILOT_NOW",
                    strict_pilot_posts="300",
                )
            ],
        )
        import_subreddit_csv(self.repository, second_path)

        plan = build_pilot_plan(self.repository)
        entry = next(entry for entry in plan.entries if entry.source_name == "r/Shifting")
        self.assertEqual(entry.relevance_status, "CORE")
        self.assertEqual(entry.pilot_size, 300)

    def test_ready_source_with_conflicting_zero_pilot_size_is_flagged_and_excluded(self) -> None:
        path = self._write_registry(
            "conflict.csv",
            [
                _row(
                    "r/Conflicted",
                    strict_relevance="CORE",
                    recommended_action="SCAN_PILOT_NOW",
                    strict_pilot_posts="0",
                )
            ],
        )
        import_subreddit_csv(self.repository, path)

        plan = build_pilot_plan(self.repository)

        self.assertEqual(len(plan.conflicts), 1)
        self.assertIsNotNone(plan.conflicts[0].conflict)
        self.assertNotIn("r/Conflicted", [entry.source_name for entry in plan.manifest])

    def test_reimport_preserves_manually_set_lifecycle_and_compliance_metadata(self) -> None:
        path = self._mixed_registry()
        import_subreddit_csv(self.repository, path)
        source_id = self.repository.connection.execute(
            "SELECT id FROM sources WHERE name = 'r/Core'"
        ).fetchone()["id"]
        self.repository.connection.execute(
            "UPDATE sources SET commercial_use_status = 'APPROVED' WHERE id = ?",
            (source_id,),
        )
        self.repository.connection.commit()

        import_subreddit_csv(self.repository, path)

        row = self.repository.connection.execute(
            "SELECT commercial_use_status FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        self.assertEqual(row["commercial_use_status"], "APPROVED")

    def test_reimport_preserves_measured_source_metrics(self) -> None:
        path = self._mixed_registry()
        import_subreddit_csv(self.repository, path)
        source_id = self.repository.connection.execute(
            "SELECT id FROM sources WHERE name = 'r/Core'"
        ).fetchone()["id"]
        self.repository.connection.execute(
            """INSERT INTO source_metrics (
                   source_id, measurement_key, metric_version, items_scanned,
                   pain_observations, strong_single_signals, active_search_signals,
                   payment_signals, problem_clusters_contributed, cross_source_confirmations,
                   temporary_incidents, support_questions, processing_cost_complete
               ) VALUES (?, 'cumulative', 'test-v1', 1000, 40, 12, 5, 2, 3, 1, 0, 0, 1)""",
            (source_id,),
        )
        self.repository.connection.commit()

        import_subreddit_csv(self.repository, path)

        row = self.repository.connection.execute(
            "SELECT items_scanned, strong_single_signals FROM source_metrics WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        self.assertEqual(row["items_scanned"], 1000)
        self.assertEqual(row["strong_single_signals"], 12)

    def test_unsupported_strict_relevance_value_is_rejected_before_any_write(self) -> None:
        path = self._write_registry(
            "invalid.csv",
            [_row("r/Bad", strict_relevance="MAYBE", recommended_action="SCAN_PILOT_NOW")],
        )
        with self.assertRaisesRegex(ValueError, "strict_relevance has unsupported value"):
            import_subreddit_csv(self.repository, path)
        self.assertEqual(self.repository.stats()["sources"], 0)

    def test_plan_output_formats_render_without_error(self) -> None:
        import_subreddit_csv(self.repository, self._mixed_registry())
        plan = build_pilot_plan(self.repository)

        self.assertIn("r/Core", plan.to_json())
        self.assertIn("r/Core", plan.to_csv())
        self.assertIn("r/Core", plan.to_markdown())


class PilotPlanCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "pilot.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_import_then_pilot_plan_round_trips_through_the_cli(self) -> None:
        registry_path = self.directory / "registry.csv"
        registry_path.write_text(
            _HEADER
            + _row(
                "r/Core",
                strict_relevance="CORE",
                recommended_action="SCAN_PILOT_NOW",
                strict_pilot_posts="300",
            )
            + _row("r/Dropped", strict_relevance="DROP", recommended_action="EXCLUDE"),
            encoding="utf-8",
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "sources-import",
                    "--database",
                    str(self.database),
                    "--file",
                    str(registry_path),
                ]
            )
        self.assertEqual(result, 0)
        imported = json.loads(output.getvalue())
        self.assertEqual(imported["imported_rows"], 2)
        self.assertEqual(imported["created_sources"], 2)

        json_output = self.directory / "plan.json"
        csv_output = self.directory / "plan.csv"
        markdown_output = self.directory / "plan.md"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "sources-pilot-plan",
                    "--database",
                    str(self.database),
                    "--json-output",
                    str(json_output),
                    "--csv-output",
                    str(csv_output),
                    "--markdown-output",
                    str(markdown_output),
                ]
            )
        self.assertEqual(result, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["manifest_count"], 1)

        plan_json = json.loads(json_output.read_text(encoding="utf-8"))
        self.assertEqual([entry["source"] for entry in plan_json["entries"]], ["r/Core"])
        self.assertIn("r/Core", csv_output.read_text(encoding="utf-8"))
        self.assertIn("r/Core", markdown_output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from problem_intelligence.domain import (
    EvidenceRange,
    EvidenceScope,
    PipelineStage,
    ProblemFamily,
    ProblemType,
    SourceLifecycle,
)
from problem_intelligence.reddit import (
    JsonlAcquisitionProvider,
    JsonlSearchProvider,
    acquire_discoveries,
    build_reddit_query,
    build_reddit_query_for_vocabulary,
    canonicalize_reddit_url,
    discover_subreddits,
)
from problem_intelligence.reddit_reporting import build_reddit_report
from problem_intelligence.repository import Repository
from problem_intelligence.source_import import import_subreddit_csv

CAPABILITIES = {
    "supports_search": True,
    "supports_full_content": False,
    "supports_comments": False,
    "supports_date_filter": False,
    "supports_subreddit_filter": True,
    "supports_pagination": False,
    "supports_historical_search": True,
}


class RedditIdentityTests(unittest.TestCase):
    def test_canonicalizes_host_slug_tracking_and_comment_variants(self) -> None:
        variants = (
            "https://old.reddit.com/r/Accounting/comments/AbC123/a_slug/?utm_source=x#frag",
            "https://www.reddit.com/r/accounting/comments/abc123/another_slug/",
            "https://new.reddit.com/r/ACCOUNTING/comments/abc123/",
        )
        identities = [canonicalize_reddit_url(url) for url in variants]
        self.assertTrue(all(identity is not None for identity in identities))
        self.assertEqual(
            {identity.canonical_url for identity in identities if identity},
            {"https://www.reddit.com/r/accounting/comments/abc123/"},
        )
        comment = canonicalize_reddit_url(
            "https://www.reddit.com/r/Accounting/comments/abc123/slug/Def456/?context=3"
        )
        assert comment is not None
        self.assertEqual(
            comment.canonical_url,
            "https://www.reddit.com/r/accounting/comments/abc123/_/def456/",
        )
        self.assertEqual(comment.external_id, "reddit:comment:abc123:def456")

    def test_canonicalizes_short_link_and_rejects_non_reddit(self) -> None:
        short = canonicalize_reddit_url("https://redd.it/XYZ789?share_id=1")
        assert short is not None
        self.assertEqual(short.canonical_url, "https://www.reddit.com/comments/xyz789/")
        self.assertIsNone(canonicalize_reddit_url("https://example.com/comments/xyz789"))

    def test_query_generation_is_deterministic(self) -> None:
        self.assertEqual(
            build_reddit_query("Accounting", "manual_work"),
            'site:reddit.com/r/Accounting ("manual" OR "manually" OR "spreadsheet" OR '
            '"excel" OR "copy" OR "paste" OR "export" OR "import" OR "csv")',
        )
        self.assertTrue(
            build_reddit_query("Accounting", "manual_work", time_context="past   year").endswith(
                ' "past year"'
            )
        )
        self.assertEqual(
            build_reddit_query_for_vocabulary(
                "SEO", ("manual report", "manual report", "data   entry")
            ),
            'site:reddit.com/r/SEO ("manual report" OR "data entry")',
        )


class RedditPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def _jsonl(self, name: str, rows: list[dict[str, object]]) -> Path:
        path = self.directory / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_discovery_requires_verified_subreddit_identity(self) -> None:
        query = build_reddit_query("Accounting", "manual_work")
        search = self._jsonl(
            "identity-search.jsonl",
            [{
                "provider": "test-search",
                "capabilities": CAPABILITIES,
                "query": query,
                "availability": "RESULTS",
                "results": [
                    {"url": "https://www.reddit.com/r/Accounting/comments/abc123/"},
                    {"url": "https://www.reddit.com/r/HVAC/comments/def456/"},
                    {"url": "https://redd.it/ghi789"},
                ],
            }],
        )
        discover_subreddits(
            self.repository, JsonlSearchProvider(search),
            subreddits=("Accounting",), query_groups=("manual_work",),
        )
        self.assertEqual(self.repository.stats()["discovery_records"], 1)
        count = self.repository.connection.execute(
            "SELECT reddit_urls_discovered FROM discovery_runs"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_discovery_acquisition_dedupe_and_completeness(self) -> None:
        query = build_reddit_query("Accounting", "manual_work")
        search = self._jsonl(
            "search.jsonl",
            [
                {
                    "provider": "test-search",
                    "capabilities": CAPABILITIES,
                    "query": query,
                    "availability": "RESULTS",
                    "results": [
                        {
                            "url": "https://old.reddit.com/r/Accounting/comments/abc123/first/?x=1",
                            "title": "Manual work",
                        },
                        {
                            "url": "https://www.reddit.com/r/accounting/comments/abc123/second/",
                            "title": "Duplicate provider result",
                        },
                    ],
                }
            ],
        )
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(search),
            subreddits=("Accounting",),
            query_groups=("manual_work",),
        )
        policy_status = self.repository.connection.execute(
            "SELECT commercial_use_status FROM sources"
        ).fetchone()[0]
        self.assertEqual(policy_status, "REVIEW_REQUIRED")
        # A duplicate canonical URL within one provider response is retained only once.
        self.assertEqual(self.repository.stats()["discovery_records"], 1)
        second_search = self._jsonl(
            "second-search.jsonl",
            [
                {
                    "provider": "second-search-provider",
                    "capabilities": CAPABILITIES,
                    "query": query,
                    "availability": "RESULTS",
                    "results": [
                        {
                            "url": "https://www.reddit.com/r/accounting/comments/abc123/",
                            "title": "Same submission from a second provider",
                        }
                    ],
                }
            ],
        )
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(second_search),
            subreddits=("Accounting",),
            query_groups=("manual_work",),
        )
        self.assertEqual(self.repository.stats()["discovery_records"], 2)
        source_id = int(
            self.repository.connection.execute("SELECT id FROM sources").fetchone()[0]
        )
        self.repository.set_source_lifecycle(source_id, SourceLifecycle.EXPLORATION)
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(second_search),
            subreddits=("Accounting",),
            query_groups=("manual_work",),
        )
        lifecycle = self.repository.connection.execute(
            "SELECT lifecycle FROM sources WHERE id = ?", (source_id,)
        ).fetchone()[0]
        self.assertEqual(lifecycle, SourceLifecycle.EXPLORATION.value)

        acquisition = self._jsonl(
            "acquisition.jsonl",
            [
                {
                    "provider": "test-content",
                    "capabilities": CAPABILITIES,
                    "url": "https://www.reddit.com/r/accounting/comments/abc123/",
                    "state": "CONTENT_PARTIAL",
                    "completeness": "PARTIAL",
                    "text": "We manually reconcile every invoice in a spreadsheet each Friday.",
                }
            ],
        )
        class CountingProvider(JsonlAcquisitionProvider):
            def __init__(self, path: Path) -> None:
                super().__init__(path)
                self.calls = 0

            def acquire(self, canonical_url: str):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().acquire(canonical_url)

        provider = CountingProvider(acquisition)
        acquire_discoveries(self.repository, provider)
        self.assertEqual(acquire_discoveries(self.repository, provider), ())
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.repository.stats()["source_items"], 1)
        self.assertEqual(len(self.repository.extraction_eligible_source_item_ids()), 1)
        self.assertEqual(self.repository.full_reddit_source_item_ids(), ())
        provenance = self.repository.connection.execute(
            """SELECT DISTINCT d.provider AS discovery_provider, a.provider AS acquisition_provider
               FROM acquisition_records AS a
               JOIN discovery_records AS d ON d.id = a.discovery_id"""
        ).fetchall()
        self.assertEqual(
            {row["discovery_provider"] for row in provenance},
            {"test-search", "second-search-provider"},
        )
        self.assertEqual(
            {row["acquisition_provider"] for row in provenance}, {"test-content"}
        )
        report = build_reddit_report(self.repository).data
        self.assertEqual(report["summary"]["unique_canonical_urls"], 1)
        self.assertEqual(report["summary"]["duplicate_discoveries_removed"], 3)
        self.assertEqual(report["communities"][0]["partial"], 1)
        self.assertEqual(report["communities"][0]["sample_size_items"], 1)
        self.assertIn("tiny sample", report["communities"][0]["sample_warning"])
        acquisition_provider = next(
            row for row in report["providers"] if row["role"] == "acquisition"
        )
        self.assertEqual(acquisition_provider["success_rate"], 1.0)
        self.assertEqual(acquisition_provider["partial_content_rate"], 1.0)
        self.assertIsNone(acquisition_provider["latency_ms"])
        self.assertEqual(acquisition_provider["unknown_cost_records"], 1)
        invocation_flags = [
            json.loads(row[0])["provider_invocation"]
            for row in self.repository.connection.execute(
                "SELECT metadata_json FROM acquisition_records ORDER BY id"
            )
        ]
        self.assertEqual(invocation_flags, [True, False, False])

    def test_failed_acquisition_is_preserved_without_source_item(self) -> None:
        query = build_reddit_query("SEO", "manual_work")
        search = self._jsonl(
            "failed-search.jsonl",
            [
                {
                    "provider": "test-search",
                    "capabilities": CAPABILITIES,
                    "query": query,
                    "availability": "RESULTS",
                    "results": [
                        {"url": "https://www.reddit.com/r/SEO/comments/missing1/title/"}
                    ],
                }
            ],
        )
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(search),
            subreddits=("SEO",),
            query_groups=("manual_work",),
        )
        acquisition = self._jsonl(
            "unrelated-acquisition.jsonl",
            [
                {
                    "provider": "test-content",
                    "capabilities": CAPABILITIES,
                    "url": "https://www.reddit.com/r/SEO/comments/another1/title/",
                    "state": "ACQUISITION_FAILED",
                    "error": "public content unavailable",
                }
            ],
        )
        acquire_discoveries(self.repository, JsonlAcquisitionProvider(acquisition))
        row = self.repository.connection.execute(
            "SELECT state, completeness, source_item_id, error FROM acquisition_records"
        ).fetchone()
        assert row is not None
        self.assertEqual(row["state"], "ACQUISITION_FAILED")
        self.assertIsNone(row["completeness"])
        self.assertIsNone(row["source_item_id"])
        self.assertIn("absent", row["error"])
        self.assertEqual(self.repository.stats()["source_items"], 0)
        report = build_reddit_report(self.repository).data
        self.assertEqual(report["communities"][0]["failed_or_blocked"], 1)
        self.assertEqual(report["providers"][1]["failure_rate"], 1.0)
        self.assertTrue(report["errors"])

    def test_metadata_only_acquisition_is_not_extractable(self) -> None:
        query = build_reddit_query("SEO", "manual_work")
        search = self._jsonl(
            "metadata-search.jsonl",
            [
                {
                    "provider": "test-search",
                    "capabilities": CAPABILITIES,
                    "query": query,
                    "availability": "RESULTS",
                    "results": [
                        {
                            "url": "https://www.reddit.com/r/SEO/comments/meta123/title/",
                            "title": "Indexed title only",
                        }
                    ],
                }
            ],
        )
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(search),
            subreddits=("SEO",),
            query_groups=("manual_work",),
        )
        acquisition = self._jsonl(
            "metadata-acquisition.jsonl",
            [
                {
                    "provider": "test-content",
                    "capabilities": CAPABILITIES,
                    "url": "https://www.reddit.com/r/SEO/comments/meta123/title/",
                    "state": "CONTENT_PARTIAL",
                    "completeness": "METADATA_ONLY",
                    "title": "Indexed title only",
                }
            ],
        )
        acquire_discoveries(self.repository, JsonlAcquisitionProvider(acquisition))
        self.assertEqual(self.repository.stats()["source_items"], 0)
        self.assertEqual(self.repository.extraction_eligible_source_item_ids(), ())
        community = build_reddit_report(self.repository).data["communities"][0]
        self.assertEqual(community["metadata_only"], 1)
        self.assertEqual(community["eligible_items"], 0)

    def test_full_content_requires_capability_and_is_wave_extraction_eligible(self) -> None:
        query = build_reddit_query("Accounting", "manual_work")
        search = self._jsonl("full-search.jsonl", [{
            "provider": "test-search",
            "capabilities": CAPABILITIES,
            "query": query,
            "availability": "RESULTS",
            "results": [{"url": "https://www.reddit.com/r/Accounting/comments/full123/"}],
        }])
        discover_subreddits(
            self.repository, JsonlSearchProvider(search),
            subreddits=("Accounting",), query_groups=("manual_work",),
        )
        full_capture = {
            "provider": "test-content",
            "capabilities": CAPABILITIES,
            "url": "https://www.reddit.com/r/Accounting/comments/full123/",
            "state": "CONTENT_COMPLETE",
            "completeness": "FULL",
            "text": "We manually reconcile invoices in spreadsheets every Friday morning.",
        }
        malformed = {**full_capture, "capabilities": {
            **CAPABILITIES, "supports_full_content": "false",
        }}
        malformed_capture = self._jsonl("malformed-content.jsonl", [malformed])
        with self.assertRaisesRegex(ValueError, "exact boolean"):
            JsonlAcquisitionProvider(malformed_capture)
        capture = self._jsonl("full-content.jsonl", [full_capture])
        with self.assertRaisesRegex(ValueError, "full-content provider"):
            acquire_discoveries(self.repository, JsonlAcquisitionProvider(capture))
        self.assertEqual(self.repository.stats()["acquisition_records"], 0)
        full_capture["capabilities"] = {**CAPABILITIES, "supports_full_content": True}
        capture = self._jsonl("full-content.jsonl", [full_capture])
        with self.assertRaisesRegex(ValueError, "body-complete attestation"):
            acquire_discoveries(self.repository, JsonlAcquisitionProvider(capture))
        full_capture["metadata"] = {
            "body_complete": True,
            "retrieved_at": "2026-09-19T12:00:00Z",
        }
        capture = self._jsonl("full-content.jsonl", [full_capture])
        acquire_discoveries(self.repository, JsonlAcquisitionProvider(capture))
        full_ids = self.repository.full_reddit_source_item_ids()
        self.assertEqual(len(full_ids), 1)
        self.assertEqual(full_ids, self.repository.extraction_eligible_source_item_ids())

    def test_no_results_and_unavailable_are_distinct(self) -> None:
        manual = build_reddit_query("SEO", "manual_work")
        capture = self._jsonl(
            "search.jsonl",
            [
                {
                    "provider": "test-search",
                    "capabilities": CAPABILITIES,
                    "query": manual,
                    "availability": "NO_RESULTS",
                    "results": [],
                }
            ],
        )
        discover_subreddits(
            self.repository,
            JsonlSearchProvider(capture),
            subreddits=("SEO",),
            query_groups=("manual_work", "active_search"),
        )
        report = build_reddit_report(self.repository).data
        availability = report["communities"][0]["availability"]
        self.assertEqual(availability["NO_RESULTS"], 1)
        self.assertEqual(availability["SOURCE_UNAVAILABLE"], 1)

    def test_report_omits_registry_sources_that_were_never_scanned(self) -> None:
        self.repository.upsert_source(source_type="reddit", name="r/NeverScanned")
        report = build_reddit_report(self.repository).data
        self.assertEqual(report["communities"], [])

    def test_legacy_csv_scores_are_metadata_not_lifecycle(self) -> None:
        path = self.directory / "subreddits.csv"
        path.write_text("subreddit,old_score\nr/Accounting,99\n", encoding="utf-8")
        source_ids = import_subreddit_csv(self.repository, path)
        row = self.repository.connection.execute(
            """SELECT s.lifecycle, m.metadata_json FROM sources AS s
               JOIN source_registry_metadata AS m ON m.source_id = s.id
               WHERE s.id = ?""",
            (source_ids[0],),
        ).fetchone()
        assert row is not None
        self.assertEqual(row["lifecycle"], "CANDIDATE")
        self.assertEqual(json.loads(row["metadata_json"])["old_score"], "99")

    def test_strict_registry_fields_are_structured_and_idempotent(self) -> None:
        path = self.directory / "strict.csv"
        path.write_text(
            "subreddit,kategorie,zielgruppe,audience_type,entscheidung,prioritaet,"
            "research_role,scan_now,aktivitaet,aktivitaet_confidence,source_url,"
            "verified_at,strict_relevance,recommended_action,pilot_posts,"
            "strict_pilot_posts,legacy_prio_score\n"
            "r/Accounting,Accounting_Tax_Finance,"
            '"Buchhalter, Steuerprofis und Auditoren",'
            "PRACTITIONER / OWNER / BUYER,BRAUCHEN_CORE,A,PRIMARY_DISCOVERY,JA,"
            "ACTIVE_VERIFIED_2026-09,HIGH,https://www.reddit.com/r/Accounting/,"
            "2026-09-18,CORE,SCAN_PILOT_NOW,500,300,4.9\n",
            encoding="utf-8",
        )
        first = import_subreddit_csv(self.repository, path)
        second = import_subreddit_csv(self.repository, path)
        self.assertEqual(first, second)
        self.assertEqual(self.repository.stats()["sources"], 1)
        self.assertEqual(self.repository.stats()["source_registry_profiles"], 1)
        row = self.repository.connection.execute(
            """SELECT s.lifecycle, s.access_method, s.commercial_use_status,
                      p.platform, p.canonical_url, p.primary_industry,
                      p.professions_json, p.audience_type, p.audience_segments_json,
                      p.curation_priority, p.scan_directive, p.scan_now, p.strict_pilot_posts,
                      p.registry_verified_at
               FROM sources AS s
               JOIN source_registry_profiles AS p ON p.source_id = s.id"""
        ).fetchone()
        assert row is not None
        self.assertEqual(row["lifecycle"], "CANDIDATE")
        self.assertEqual(row["access_method"], "PUBLIC_WEB")
        self.assertEqual(row["commercial_use_status"], "REVIEW_REQUIRED")
        self.assertEqual(row["platform"], "REDDIT")
        self.assertEqual(row["canonical_url"], "https://www.reddit.com/r/Accounting/")
        self.assertEqual(row["primary_industry"], "Accounting_Tax_Finance")
        self.assertEqual(
            json.loads(row["professions_json"]),
            ["Buchhalter", "Steuerprofis", "Auditoren"],
        )
        self.assertEqual(row["audience_type"], "MIXED")
        self.assertEqual(
            json.loads(row["audience_segments_json"]),
            ["PRACTITIONER", "OWNER", "BUYER"],
        )
        self.assertEqual(row["curation_priority"], "A")
        self.assertEqual(row["scan_directive"], "JA")
        self.assertEqual(row["scan_now"], 1)
        self.assertEqual(row["strict_pilot_posts"], 300)
        self.assertEqual(row["registry_verified_at"], "2026-09-18")

    def test_reimport_with_fewer_columns_preserves_prior_curation(self) -> None:
        first_path = self.directory / "full.csv"
        first_path.write_text(
            "subreddit,kategorie,research_angle,entscheidung,warum,notes,scan_now,"
            "strict_pilot_posts,pilot_posts,source_url\n"
            "r/Accounting,Accounting_Tax_Finance,Manual bookkeeping pain,"
            "BRAUCHEN_CORE,High signal community,Reviewed by ops,JA,0,50,"
            "https://www.reddit.com/r/Accounting/\n",
            encoding="utf-8",
        )
        import_subreddit_csv(self.repository, first_path)

        second_path = self.directory / "sparse.csv"
        second_path.write_text(
            "subreddit,recommended_action,aktivitaet\n"
            "r/Accounting,,ACTIVE_VERIFIED_2026-09\n",
            encoding="utf-8",
        )
        import_subreddit_csv(self.repository, second_path)

        row = self.repository.connection.execute(
            """SELECT p.research_angle, p.curation_decision, p.rationale, p.notes,
                      p.strict_pilot_posts, p.pilot_posts, p.canonical_url,
                      p.activity_status
               FROM source_registry_profiles AS p
               JOIN sources AS s ON s.id = p.source_id
               WHERE s.name = 'r/Accounting'"""
        ).fetchone()
        assert row is not None
        self.assertEqual(row["research_angle"], "Manual bookkeeping pain")
        self.assertEqual(row["curation_decision"], "BRAUCHEN_CORE")
        self.assertEqual(row["rationale"], "High signal community")
        self.assertEqual(row["notes"], "Reviewed by ops")
        self.assertEqual(row["canonical_url"], "https://www.reddit.com/r/Accounting/")
        # An explicit strict_pilot_posts=0 must not fall back to pilot_posts.
        self.assertEqual(row["strict_pilot_posts"], 0)
        candidate = self.repository.source_scan_candidates()
        self.assertEqual(candidate[0].pilot_posts, 0)
        self.assertEqual(row["activity_status"], "ACTIVE_VERIFIED_2026-09")

    def test_registry_validation_happens_before_writes(self) -> None:
        path = self.directory / "invalid.csv"
        path.write_text(
            "subreddit,scan_now\nr/Accounting,JA\nr/SEO,MAYBE\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "scan_now has unsupported value"):
            import_subreddit_csv(self.repository, path)
        self.assertEqual(self.repository.stats()["sources"], 0)

    def test_scan_plan_separates_curation_from_policy_readiness(self) -> None:
        path = self.directory / "plan.csv"
        path.write_text(
            "subreddit,kategorie,audience_type,prioritaet,research_role,scan_now,"
            "recommended_action,pilot_posts,strict_pilot_posts,source_url\n"
            "r/Secondary,Ops,MIXED,S,SECONDARY_ONLY,NUR_SEKUNDAER,"
            "DO_NOT_CONTINUOUSLY_SCAN,100,0,https://reddit.com/r/Secondary/\n"
            "r/Light,Ops,PRACTITIONER,B,EXPLORATION,JA_LIGHT,"
            "SCAN_SMALL_PILOT,250,50,https://reddit.com/r/Light/\n"
            "r/Core,Finance,PRACTITIONER / OWNER,A,PRIMARY_DISCOVERY,JA,"
            "SCAN_PILOT_NOW,500,300,https://reddit.com/r/Core/\n",
            encoding="utf-8",
        )
        import_subreddit_csv(self.repository, path)
        candidates = self.repository.source_scan_candidates()
        self.assertEqual([candidate.name for candidate in candidates], ["r/Core", "r/Light"])
        self.assertEqual([candidate.pilot_posts for candidate in candidates], [300, 50])
        self.assertTrue(all(not candidate.production_ready for candidate in candidates))
        filtered = self.repository.source_scan_candidates(priorities=("b",))
        self.assertEqual(
            [candidate.name for candidate in filtered],
            ["r/Light"],
        )

    def test_registry_import_does_not_downgrade_approved_source_policy(self) -> None:
        source_id = self.repository.upsert_source(
            source_type="reddit",
            name="r/Accounting",
            access_method="LICENSED_API",
            commercial_use_status="APPROVED",
        )
        path = self.directory / "approved.csv"
        path.write_text(
            "subreddit,kategorie,audience_type,scan_now,source_url\n"
            "r/Accounting,Finance,PRACTITIONER,JA,"
            "https://www.reddit.com/r/Accounting/\n",
            encoding="utf-8",
        )
        self.assertEqual(import_subreddit_csv(self.repository, path), (source_id,))
        source = self.repository.connection.execute(
            "SELECT access_method, commercial_use_status FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        assert source is not None
        self.assertEqual(source["access_method"], "LICENSED_API")
        self.assertEqual(source["commercial_use_status"], "APPROVED")
        candidate = self.repository.source_scan_candidates()[0]
        self.assertTrue(candidate.production_ready)

    def test_report_excludes_observations_from_a_failed_pipeline_run(self) -> None:
        source_id = self.repository.upsert_source(source_type="reddit", name="r/accounting")
        self.repository.connection.execute(
            """INSERT INTO discovery_runs (
                   id, source_id, provider, query, availability,
                   provider_capabilities_json
               ) VALUES ('run-1', ?, 'test-search', 'manual work', 'RESULTS', '{}')""",
            (source_id,),
        )
        self.repository.connection.commit()
        text = "We manually reconcile every invoice in a spreadsheet each Friday."
        item_id = self.repository.upsert_source_item(
            source_id=source_id, external_id="abc123", raw_text=text
        )
        run_id = self.repository.start_pipeline_run(
            stage=PipelineStage.EXTRACTION, version="v1", input_count=2
        )
        self.repository.create_observation_with_evidence(
            source_item_id=item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Manual reconciliation",
            extraction_version="v1",
            evidence_ranges=(EvidenceRange(0, len(text)),),
            fields={
                "actor": "finance team",
                "job_to_be_done": "reconcile invoices",
                "context": "weekly close",
                "existing_spend": "an hour every Friday",
                "active_solution_search": True,
            },
            pipeline_run_id=run_id,
        )
        self.repository.fail_pipeline_run(run_id, output_count=1, error="provider timeout")

        community = build_reddit_report(self.repository).data["communities"][0]
        self.assertEqual(community["observations"], 0)
        self.assertEqual(community["active_solution_searches"], 0)
        self.assertEqual(community["strong_single_signals"], 0)

    def test_report_does_not_leak_observations_from_non_reddit_sources(self) -> None:
        # The Reddit report's top-level summary and excerpt samples must describe the
        # Reddit acquisition path only; a research-capture observation from an unrelated
        # source type (e.g. vendor marketing ingested for a DACH assessment) must not
        # appear in a report titled and scoped as Reddit-specific.
        reddit_source_id = self.repository.upsert_source(
            source_type="reddit", name="r/accounting"
        )
        self.repository.connection.execute(
            """INSERT INTO discovery_runs (
                   id, source_id, provider, query, availability,
                   provider_capabilities_json
               ) VALUES ('run-1', ?, 'test-search', 'manual work', 'RESULTS', '{}')""",
            (reddit_source_id,),
        )
        self.repository.connection.commit()
        reddit_text = "We manually reconcile every invoice in a spreadsheet each Friday."
        reddit_item_id = self.repository.upsert_source_item(
            source_id=reddit_source_id, external_id="abc123", raw_text=reddit_text
        )
        self.repository.create_observation_with_evidence(
            source_item_id=reddit_item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.RECONCILIATION,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Manual reconciliation",
            extraction_version="v1",
            evidence_ranges=(EvidenceRange(0, len(reddit_text)),),
            fields={"actor": "finance team", "job_to_be_done": "reconcile invoices"},
        )

        vendor_source_id = self.repository.upsert_source(
            source_type="vendor-marketing", name="Unrelated Vendor"
        )
        vendor_text = "Automate your tedious SEO reports today."
        vendor_item_id = self.repository.upsert_source_item(
            source_id=vendor_source_id, external_id="vendor-1", raw_text=vendor_text
        )
        self.repository.create_observation_with_evidence(
            source_item_id=vendor_item_id,
            problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.REPORTING,
            ontology_version="problem-ontology-v1",
            evidence_scope=EvidenceScope.DACH,
            problem="A vendor markets automation of a tedious report.",
            extraction_version="v1",
            evidence_ranges=(EvidenceRange(0, len(vendor_text)),),
            fields={},
        )

        report = build_reddit_report(self.repository).data
        self.assertEqual(report["summary"]["observations"], 1)
        self.assertEqual(len(report["communities"]), 1)
        self.assertEqual(report["communities"][0]["community"], "r/accounting")
        self.assertTrue(
            all(sample["community"] != "Unrelated Vendor" for sample in report["samples"])
        )


if __name__ == "__main__":
    unittest.main()

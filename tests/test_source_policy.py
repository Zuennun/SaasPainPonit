from __future__ import annotations

import unittest

from problem_intelligence.repository import Repository
from problem_intelligence.source_policy import (
    POLICY_TEXT_FIELDS,
    audit_source_policies,
    source_policy_decision,
)


class SourcePolicyDecisionTests(unittest.TestCase):
    def test_complete_approved_policy_is_production_and_display_ready(self) -> None:
        values = {field: "documented" for field in POLICY_TEXT_FIELDS}
        values["commercial_use_status"] = "APPROVED_CC_BY_4_0"
        values["rights_reviewed_at"] = "2026-09-18"

        decision = source_policy_decision(values)

        self.assertTrue(decision.complete)
        self.assertTrue(decision.commercial_use_approved)
        self.assertTrue(decision.production_ready)
        self.assertTrue(decision.display_ready)
        self.assertEqual(decision.missing_fields, ())
        self.assertEqual(decision.invalid_fields, ())

    def test_approved_status_with_missing_rights_fields_is_not_production_ready(self) -> None:
        decision = source_policy_decision(
            {"commercial_use_status": "APPROVED", "access_method": "operator-reviewed"}
        )

        self.assertTrue(decision.commercial_use_approved)
        self.assertFalse(decision.complete)
        self.assertFalse(decision.production_ready)
        self.assertIn("retention_rules", decision.missing_fields)
        self.assertIn("rights_reviewed_at", decision.missing_fields)

    def test_unparseable_reviewed_at_is_reported_as_invalid(self) -> None:
        values = {field: "documented" for field in POLICY_TEXT_FIELDS}
        values["rights_reviewed_at"] = "not-a-date"

        decision = source_policy_decision(values)

        self.assertFalse(decision.complete)
        self.assertIn("rights_reviewed_at", decision.invalid_fields)

    def test_unapproved_status_is_never_production_ready_even_if_complete(self) -> None:
        values = {field: "documented" for field in POLICY_TEXT_FIELDS}
        values["commercial_use_status"] = "UNKNOWN_REQUIRES_REVIEW"
        values["rights_reviewed_at"] = "2026-09-18"

        decision = source_policy_decision(values)

        self.assertTrue(decision.complete)
        self.assertFalse(decision.commercial_use_approved)
        self.assertFalse(decision.production_ready)


class AuditSourcePoliciesTests(unittest.TestCase):
    def test_audit_accepts_live_sqlite_rows_without_crashing(self) -> None:
        # audit_source_policies feeds sqlite3.Row objects into source_policy_decision;
        # Row has no .get(), so this exercises the exact shape write-time code hits.
        repository = Repository()
        repository.initialize()
        try:
            repository.upsert_source(
                source_type="forum",
                name="rights-incomplete",
                access_method="operator-reviewed-public-page",
                commercial_use_status="APPROVED",
            )

            audit = audit_source_policies(repository, include_unused=True)

            self.assertEqual(audit.source_count, 1)
            self.assertFalse(audit.clean)
        finally:
            repository.close()

    def test_audit_flags_approved_status_without_complete_policy(self) -> None:
        repository = Repository()
        repository.initialize()
        try:
            repository.upsert_source(
                source_type="forum",
                name="rights-incomplete",
                access_method="operator-reviewed-public-page",
                commercial_use_status="APPROVED",
            )

            audit = audit_source_policies(repository, include_unused=True)

            self.assertEqual(len(audit.violations), 1)
            violation = audit.violations[0]
            self.assertTrue(violation.approved_status_without_complete_policy)
            self.assertIn("retention_rules", violation.missing_fields)
            self.assertEqual(audit.production_ready_count, 0)

        finally:
            repository.close()

    def test_audit_is_clean_for_a_fully_documented_approved_source(self) -> None:
        repository = Repository()
        repository.initialize()
        try:
            repository.upsert_source(
                source_type="official-documentation",
                name="fully-documented",
                access_method="operator-reviewed-public-page",
                commercial_use_status="APPROVED_CC_BY_4_0",
                retention_rules="Retain while the research case is active.",
                attribution_requirements="Attribute the source and retain its URL.",
                quoting_rules="Short attributed excerpt under documented terms.",
                deletion_requirements="Remove if the source is withdrawn.",
                rate_limit_notes="Single operator-reviewed capture.",
                rights_reviewed_at="2026-09-18",
            )

            audit = audit_source_policies(repository, include_unused=True)

            self.assertTrue(audit.clean)
            self.assertEqual(audit.complete_policy_count, 1)
            self.assertEqual(audit.production_ready_count, 1)

        finally:
            repository.close()

    def test_unused_sources_excluded_by_default(self) -> None:
        repository = Repository()
        repository.initialize()
        try:
            repository.upsert_source(source_type="forum", name="unused")

            audit = audit_source_policies(repository)

            self.assertEqual(audit.source_count, 0)
            self.assertEqual(audit.violations, ())

            audit_with_unused = audit_source_policies(repository, include_unused=True)
            self.assertEqual(audit_with_unused.source_count, 1)
        finally:
            repository.close()


if __name__ == "__main__":
    unittest.main()

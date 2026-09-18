from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from problem_intelligence.domain import (
    EvidenceRange,
    EvidenceScope,
    EvidenceState,
    OpportunityStatus,
    OpportunityType,
    ProblemFamily,
    ProblemType,
)
from problem_intelligence.integrity_audit import audit_evidence_integrity
from problem_intelligence.repository import Repository
from scripts.rebuild_seo_reporting_case import rebuild


class SeoReportingReferenceCaseTests(unittest.TestCase):
    def test_rebuild_is_idempotent_and_produces_a_report_ready_case(self) -> None:
        project_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "reference.db"
            report = root / "report.md"
            repository = Repository(database)
            repository.initialize()
            source_id = repository.upsert_source(
                source_type="reddit",
                name="r/SEO",
                commercial_use_status="REVIEW_REQUIRED",
            )
            text = (
                "I feel many things I do manually could be automated. I hate reporting "
                "and it involves so much manual data entry."
            )
            item_id = repository.upsert_source_item(
                source_id=source_id,
                external_id="reddit:submission:hp9l64",
                raw_text=text,
                url="https://www.reddit.com/r/seo/comments/hp9l64/",
                language_code="en",
            )
            repository.create_observation_with_evidence(
                source_item_id=item_id,
                problem_type=ProblemType.WORKFLOW_GAP,
                problem_family=ProblemFamily.REPORTING,
                ontology_version="problem-ontology-v1",
                evidence_scope=EvidenceScope.GLOBAL,
                problem="Recurring SEO reporting still requires manual data entry.",
                extraction_version="manual-reviewed-reddit-real-v1",
                evidence_ranges=(EvidenceRange(0, len(text)),),
                fields={
                    "actor": "SEO practitioner",
                    "job_to_be_done": "produce recurring SEO reports",
                    "current_workaround": "manual data entry",
                    "active_solution_search": True,
                    "language_code": "en",
                },
            )
            repository.close()

            capture = project_root / "data/research/seo_reporting_research_v1.jsonl"
            first = rebuild(database, capture, report)
            first_report = report.read_text(encoding="utf-8")
            second = rebuild(database, capture, report)

            self.assertEqual(first, second)
            self.assertEqual(first_report, report.read_text(encoding="utf-8"))
            self.assertIn("## Originalbelege", first_report)
            self.assertIn("## Lokale Lösungen", first_report)
            self.assertIn("Performance Suite", first_report)
            self.assertIn(
                "keine evidenzgestützte Lösungslücke erfasst", first_report
            )
            repository = Repository(database)
            case = repository.research_case_summary(first[0])
            opportunity = repository.opportunity(first[1])
            self.assertEqual(case.status.value, "COMPLETE")
            self.assertEqual(opportunity.status.value, "REPORT_READY")
            self.assertEqual(case.unknown_count, 5)
            self.assertEqual(case.validation_question_count, 5)
            audit = audit_evidence_integrity(repository)
            self.assertTrue(audit.clean)
            self.assertEqual(audit.unsupported_factual_claim_rate, 0.0)
            self.assertEqual(audit.complete_research_cases, 1)
            self.assertEqual(audit.report_ready_opportunities, 1)
            stakeholders = repository.case_stakeholders(first[0])
            self.assertEqual(len(stakeholders), 5)
            self.assertEqual(stakeholders[0].role.value, "END_USER")
            self.assertEqual(stakeholders[0].knowledge.value, "KNOWN")
            self.assertTrue(
                all(item.knowledge.value == "UNKNOWN" for item in stakeholders[1:])
            )
            first_save = repository.save_opportunity(
                first[1], note="Interview German SEO agencies next."
            )
            repeated_save = repository.save_opportunity(
                first[1], note="Interview German SEO agencies next."
            )
            self.assertEqual(first_save, repeated_save)
            self.assertEqual(repository.saved_opportunities(), (first_save,))
            updated_save = repository.save_opportunity(
                first[1], note="Validate manual work before discussing a product."
            )
            self.assertEqual(
                updated_save.note,
                "Validate manual work before discussing a product.",
            )
            repository.connection.execute(
                "UPDATE opportunities SET title = 'Mühsame SEO-Berichte' WHERE id = ?",
                (first[1],),
            )
            search_result = repository.search_opportunities(
                query="MÜHSAME",
                status=OpportunityStatus.REPORT_READY,
                evidence_state=EvidenceState.SINGLE_SIGNAL,
                opportunity_type=OpportunityType.WORKFLOW_GAP,
                saved_only=True,
            )
            self.assertEqual(len(search_result), 1)
            self.assertEqual(search_result[0].opportunity_id, first[1])
            self.assertEqual(
                repository.search_opportunities(query="100% manual"), ()
            )
            with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
                repository.search_opportunities(limit=0)
            self.assertTrue(repository.unsave_opportunity(first[1]))
            self.assertFalse(repository.unsave_opportunity(first[1]))
            self.assertEqual(repository.saved_opportunities(), ())
            repository.close()


if __name__ == "__main__":
    unittest.main()

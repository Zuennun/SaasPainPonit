import unittest

from problem_intelligence.clustering import cluster_exact, normalize_fingerprint_text
from problem_intelligence.domain import EvidenceScope, ProblemType
from problem_intelligence.repository import Repository


class ClusteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        source_id = self.repository.upsert_source(source_type="fixture", name="clustering")
        self.item_ids = [
            self.repository.upsert_source_item(
                source_id=source_id,
                external_id=str(index),
                raw_text=text,
            )
            for index, text in enumerate(("First source", "Second source", "Third source"), 1)
        ]

    def tearDown(self) -> None:
        self.repository.close()

    def add_observation(self, item_index, problem, scope):
        return self.repository.create_observation(
            source_item_id=self.item_ids[item_index],
            problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=scope,
            problem=problem,
            extraction_version="manual-v1",
            fields={"current_workaround": "Spreadsheet"},
        )

    def test_normalization_is_unicode_case_and_punctuation_stable(self) -> None:
        self.assertEqual(
            normalize_fingerprint_text("  MÄNUAL—Copying! "),
            normalize_fingerprint_text("mänual copying"),
        )

    def test_exact_clusters_are_idempotent_and_ignore_evidence_scope(self) -> None:
        first_id = self.add_observation(0, "Manual invoice copying.", EvidenceScope.GLOBAL)
        second_id = self.add_observation(1, "manual invoice COPYING", EvidenceScope.DACH)
        self.add_observation(2, "Approval emails are delayed", EvidenceScope.DACH)

        first = cluster_exact(self.repository)
        second = cluster_exact(self.repository)

        self.assertEqual(first.observation_count, 3)
        self.assertEqual(first.cluster_count, 2)
        self.assertEqual(first.cluster_ids, second.cluster_ids)
        shared_cluster_count = self.repository.connection.execute(
            """SELECT COUNT(DISTINCT cluster_id) FROM cluster_members
               WHERE observation_id IN (?, ?)""",
            (first_id, second_id),
        ).fetchone()[0]
        self.assertEqual(shared_cluster_count, 1)
        self.assertEqual(self.repository.stats()["problem_clusters"], 2)


if __name__ == "__main__":
    unittest.main()

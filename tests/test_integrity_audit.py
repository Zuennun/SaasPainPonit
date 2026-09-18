from __future__ import annotations

import unittest

from problem_intelligence.integrity_audit import audit_evidence_integrity
from problem_intelligence.repository import Repository


class EvidenceIntegrityAuditTests(unittest.TestCase):
    def test_audit_detects_legacy_unsupported_fact_even_if_guards_were_bypassed(self) -> None:
        repository = Repository()
        repository.initialize()
        try:
            repository.connection.execute(
                "DROP TRIGGER fact_requires_evidence_on_claim_insert"
            )
            repository.connection.execute(
                "INSERT INTO claims (claim_kind, text) VALUES ('FACT', 'Legacy bad fact')"
            )

            audit = audit_evidence_integrity(repository)

            self.assertFalse(audit.clean)
            self.assertEqual(audit.factual_claims, 1)
            self.assertEqual(audit.unsupported_factual_claims, 1)
            self.assertEqual(audit.unsupported_factual_claim_rate, 1.0)
        finally:
            repository.close()


if __name__ == "__main__":
    unittest.main()

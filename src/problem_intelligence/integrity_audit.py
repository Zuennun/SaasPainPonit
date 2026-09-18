"""Read-only evidence and completed-research integrity measurements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .repository import Repository


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityAudit:
    factual_claims: int
    unsupported_factual_claims: int
    factual_claim_evidence_links: int
    mismatched_observation_claim_links: int
    invalid_evidence_spans: int
    mismatched_structured_signal_links: int
    complete_research_cases: int
    invalid_complete_research_cases: int
    report_ready_opportunities: int
    invalid_report_ready_opportunities: int

    @property
    def unsupported_factual_claim_rate(self) -> float:
        if self.factual_claims == 0:
            return 0.0
        return self.unsupported_factual_claims / self.factual_claims

    @property
    def clean(self) -> bool:
        return not any(
            (
                self.unsupported_factual_claims,
                self.mismatched_observation_claim_links,
                self.invalid_evidence_spans,
                self.mismatched_structured_signal_links,
                self.invalid_complete_research_cases,
                self.invalid_report_ready_opportunities,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "unsupported_factual_claim_rate": self.unsupported_factual_claim_rate,
            "clean": self.clean,
        }


def audit_evidence_integrity(repository: Repository) -> EvidenceIntegrityAudit:
    """Measure violations independently of write-time database guards."""

    row = repository.connection.execute(
        """SELECT
             (SELECT COUNT(*) FROM claims WHERE claim_kind = 'FACT') AS facts,
             (SELECT COUNT(*) FROM claims c
                WHERE c.claim_kind = 'FACT' AND NOT EXISTS (
                    SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id
                )) AS unsupported_facts,
             (SELECT COUNT(*) FROM claim_evidence ce
                JOIN claims c ON c.id = ce.claim_id
                WHERE c.claim_kind = 'FACT') AS fact_links,
             (SELECT COUNT(*) FROM claim_evidence ce
                JOIN claims c ON c.id = ce.claim_id
                JOIN evidence_spans es ON es.id = ce.evidence_span_id
                WHERE c.observation_id IS NOT NULL
                  AND es.observation_id IS NOT c.observation_id) AS mismatched_claim_links,
             (SELECT COUNT(*) FROM evidence_spans es
                JOIN source_items si ON si.id = es.source_item_id
                LEFT JOIN problem_observations po ON po.id = es.observation_id
                WHERE es.start_offset < 0 OR es.end_offset <= es.start_offset
                   OR es.end_offset > length(si.raw_text)
                   OR es.excerpt <> substr(
                       si.raw_text, es.start_offset + 1,
                       es.end_offset - es.start_offset
                   )
                   OR (es.observation_id IS NOT NULL AND (
                       po.id IS NULL OR po.source_item_id <> es.source_item_id
                       OR po.evidence_scope <> es.evidence_scope
                   ))) AS invalid_spans,
             (SELECT COUNT(*) FROM (
                SELECT w.id FROM workarounds w
                LEFT JOIN evidence_spans es ON es.id = w.evidence_span_id
                WHERE es.observation_id IS NOT w.observation_id
                UNION ALL
                SELECT i.id FROM impact_signals i
                LEFT JOIN evidence_spans es ON es.id = i.evidence_span_id
                WHERE es.observation_id IS NOT i.observation_id
                UNION ALL
                SELECT p.id FROM payment_signals p
                LEFT JOIN evidence_spans es ON es.id = p.evidence_span_id
                WHERE es.observation_id IS NOT p.observation_id
                UNION ALL
                SELECT r.id FROM observation_revisions r
                LEFT JOIN evidence_spans es ON es.id = r.evidence_span_id
                WHERE es.observation_id IS NOT r.observation_id
             )) AS mismatched_signal_links,
             (SELECT COUNT(*) FROM research_cases WHERE status = 'COMPLETE')
                AS complete_cases,
             (SELECT COUNT(*) FROM research_cases rc
                WHERE rc.status = 'COMPLETE' AND (
                    (SELECT COUNT(*) FROM research_passes rp
                     WHERE rp.case_id = rc.id AND rp.status = 'SATISFIED') <> 4
                    OR NOT EXISTS (
                        SELECT 1 FROM research_unknowns ru WHERE ru.case_id = rc.id
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM validation_questions vq WHERE vq.case_id = rc.id
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM dach_assessments da WHERE da.case_id = rc.id
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM cluster_members cm
                        JOIN problem_observations po ON po.id = cm.observation_id
                        JOIN evidence_spans es ON es.observation_id = po.id
                        WHERE cm.cluster_id = rc.cluster_id
                          AND length(trim(COALESCE(po.actor, ''))) > 0
                          AND length(trim(COALESCE(po.job_to_be_done, ''))) > 0
                          AND length(trim(COALESCE(po.context, ''))) > 0
                    )
                    OR EXISTS (
                        SELECT 1 FROM research_passes rp
                        LEFT JOIN claims c ON c.id = rp.summary_claim_id
                        WHERE rp.case_id = rc.id AND rp.status = 'SATISFIED'
                          AND rp.outcome = 'EVIDENCE_FOUND'
                          AND (c.claim_kind IS NULL OR c.claim_kind <> 'FACT'
                               OR NOT EXISTS (
                                   SELECT 1 FROM claim_evidence ce
                                   WHERE ce.claim_id = c.id
                               ))
                    )
                    OR (EXISTS (
                        SELECT 1 FROM research_passes rp WHERE rp.case_id = rc.id
                          AND rp.pass_type = 'COMPETITION'
                          AND rp.outcome = 'EVIDENCE_FOUND'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM competitors co WHERE co.case_id = rc.id
                    ))
                    OR (EXISTS (
                        SELECT 1 FROM research_passes rp WHERE rp.case_id = rc.id
                          AND rp.pass_type = 'COUNTER_EVIDENCE'
                          AND rp.outcome = 'EVIDENCE_FOUND'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM counter_evidence ce WHERE ce.case_id = rc.id
                    ))
                )) AS invalid_complete_cases,
             (SELECT COUNT(*) FROM opportunities WHERE status = 'REPORT_READY')
                AS ready_opportunities,
             (SELECT COUNT(*) FROM opportunities o
                LEFT JOIN research_cases rc ON rc.id = o.case_id
                WHERE o.status = 'REPORT_READY' AND (
                    rc.status IS NULL OR rc.status <> 'COMPLETE'
                    OR NOT EXISTS (
                        SELECT 1 FROM opportunity_types ot WHERE ot.opportunity_id = o.id
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM opportunity_claims oc
                        JOIN claims c ON c.id = oc.claim_id
                        WHERE oc.opportunity_id = o.id AND oc.claim_role = 'PROBLEM'
                          AND c.claim_kind = 'FACT' AND EXISTS (
                              SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id
                          )
                    )
                )) AS invalid_ready_opportunities"""
    ).fetchone()
    assert row is not None
    return EvidenceIntegrityAudit(
        factual_claims=int(row["facts"]),
        unsupported_factual_claims=int(row["unsupported_facts"]),
        factual_claim_evidence_links=int(row["fact_links"]),
        mismatched_observation_claim_links=int(row["mismatched_claim_links"]),
        invalid_evidence_spans=int(row["invalid_spans"]),
        mismatched_structured_signal_links=int(row["mismatched_signal_links"]),
        complete_research_cases=int(row["complete_cases"]),
        invalid_complete_research_cases=int(row["invalid_complete_cases"]),
        report_ready_opportunities=int(row["ready_opportunities"]),
        invalid_report_ready_opportunities=int(row["invalid_ready_opportunities"]),
    )

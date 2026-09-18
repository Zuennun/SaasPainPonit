"""Central source-policy readiness and independent coverage audit."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .repository import Repository

POLICY_TEXT_FIELDS = (
    "access_method",
    "commercial_use_status",
    "retention_rules",
    "attribution_requirements",
    "quoting_rules",
    "deletion_requirements",
    "rate_limit_notes",
    "rights_reviewed_at",
)


@dataclass(frozen=True, slots=True)
class SourcePolicyDecision:
    complete: bool
    commercial_use_approved: bool
    production_ready: bool
    display_ready: bool
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourcePolicyViolation:
    source_id: int
    source_name: str
    source_type: str
    item_count: int
    evidence_span_count: int
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]
    approved_status_without_complete_policy: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["missing_fields"] = list(self.missing_fields)
        result["invalid_fields"] = list(self.invalid_fields)
        return result


@dataclass(frozen=True, slots=True)
class SourcePolicyAudit:
    include_unused: bool
    source_count: int
    complete_policy_count: int
    production_ready_count: int
    evidence_source_count: int
    display_ready_evidence_source_count: int
    violations: tuple[SourcePolicyViolation, ...]

    @property
    def clean(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "include_unused": self.include_unused,
            "source_count": self.source_count,
            "complete_policy_count": self.complete_policy_count,
            "production_ready_count": self.production_ready_count,
            "evidence_source_count": self.evidence_source_count,
            "display_ready_evidence_source_count": (
                self.display_ready_evidence_source_count
            ),
            "violation_count": len(self.violations),
            "violations": [item.to_dict() for item in self.violations],
        }


def source_policy_decision(values: Mapping[str, object]) -> SourcePolicyDecision:
    missing = tuple(
        field
        for field in POLICY_TEXT_FIELDS
        if not isinstance(values.get(field), str) or not str(values[field]).strip()
    )
    invalid: list[str] = []
    reviewed_at = values.get("rights_reviewed_at")
    if isinstance(reviewed_at, str) and reviewed_at.strip():
        try:
            date.fromisoformat(reviewed_at.strip())
        except ValueError:
            invalid.append("rights_reviewed_at")
    approved = _approved_status(values.get("commercial_use_status"))
    complete = not missing and not invalid
    ready = approved and complete
    return SourcePolicyDecision(
        complete=complete,
        commercial_use_approved=approved,
        production_ready=ready,
        display_ready=ready,
        missing_fields=missing,
        invalid_fields=tuple(invalid),
    )


def audit_source_policies(
    repository: Repository, *, include_unused: bool = False
) -> SourcePolicyAudit:
    active_condition = "" if include_unused else "HAVING item_count > 0 OR discovery_count > 0"
    rows = repository.connection.execute(
        f"""SELECT s.*,
                   COUNT(DISTINCT si.id) AS item_count,
                   COUNT(DISTINCT dr.id) AS discovery_count,
                   COUNT(DISTINCT es.id) AS evidence_span_count
            FROM sources s
            LEFT JOIN source_items si ON si.source_id = s.id
            LEFT JOIN discovery_runs dr ON dr.source_id = s.id
            LEFT JOIN evidence_spans es ON es.source_item_id = si.id
            GROUP BY s.id
            {active_condition}
            ORDER BY s.name COLLATE NOCASE, s.id"""
    ).fetchall()
    decisions = [(row, source_policy_decision(dict(row))) for row in rows]
    violations = tuple(
        SourcePolicyViolation(
            source_id=int(row["id"]),
            source_name=str(row["name"]),
            source_type=str(row["source_type"]),
            item_count=int(row["item_count"]),
            evidence_span_count=int(row["evidence_span_count"]),
            missing_fields=decision.missing_fields,
            invalid_fields=decision.invalid_fields,
            approved_status_without_complete_policy=(
                decision.commercial_use_approved and not decision.complete
            ),
        )
        for row, decision in decisions
        if not decision.complete
    )
    evidence_decisions = [
        decision
        for row, decision in decisions
        if int(row["evidence_span_count"]) > 0
    ]
    return SourcePolicyAudit(
        include_unused=include_unused,
        source_count=len(rows),
        complete_policy_count=sum(decision.complete for _, decision in decisions),
        production_ready_count=sum(
            decision.production_ready for _, decision in decisions
        ),
        evidence_source_count=len(evidence_decisions),
        display_ready_evidence_source_count=sum(
            decision.display_ready for decision in evidence_decisions
        ),
        violations=violations,
    )


def _approved_status(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().upper().replace("-", "_")
    return normalized == "APPROVED" or normalized.startswith("APPROVED_")

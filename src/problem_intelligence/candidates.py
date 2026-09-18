"""Transparent research-case candidate selection without opportunity scores."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from .domain import EvidenceScope, EvidenceState, ProblemFamily, ProblemType
from .repository import Repository
from .signal_policy import is_strong_individual_signal

CandidateSort = Literal[
    "strongest-evidence",
    "newest",
    "active-search",
    "payment-evidence",
    "manual-workarounds",
    "dach-evidence",
]

_EXCLUDED_TYPES = {
    ProblemType.TEMPORARY_INCIDENT,
    ProblemType.SUPPORT_QUESTION,
    ProblemType.USER_ERROR,
}

_STATE_STRENGTH = {
    EvidenceState.SINGLE_SIGNAL: 0,
    EvidenceState.EMERGING: 1,
    EvidenceState.RECURRING: 2,
    EvidenceState.MULTI_SOURCE: 3,
    EvidenceState.CROSS_MARKET: 4,
}


@dataclass(frozen=True, slots=True)
class ResearchCaseCandidate:
    cluster_id: int
    algorithm_version: str
    representative_problem: str
    problem_family: ProblemFamily | None
    evidence_state: EvidenceState
    observation_count: int
    source_count: int
    country_count: int
    global_observation_count: int
    dach_observation_count: int
    active_search_count: int
    switching_intent_count: int
    quantified_impact_count: int
    payment_evidence_count: int
    workaround_count: int
    strong_individual_signal_count: int
    research_ready: bool
    exclusion_reason: str | None
    minimum_problem_evidence_complete: bool
    missing_for_completion: tuple[str, ...]
    existing_case_id: int | None
    latest_observation_at: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["problem_family"] = (
            self.problem_family.value if self.problem_family is not None else None
        )
        result["evidence_state"] = self.evidence_state.value
        return result


@dataclass(frozen=True, slots=True)
class _ObservationSignal:
    observation_id: int
    source_item_id: int
    source_id: int
    problem_type: ProblemType
    problem_family: ProblemFamily | None
    problem: str
    scope: EvidenceScope
    country_code: str | None
    created_at: str
    active_search: bool
    switching_intent: bool
    has_actor: bool
    has_job: bool
    has_context: bool
    has_workaround: bool
    has_impact: bool
    has_quantified_impact: bool
    has_payment: bool
    has_evidence: bool

    @property
    def strength_dimensions(self) -> int:
        return sum(
            (
                self.has_actor,
                self.has_job,
                self.has_context,
                self.has_workaround,
                self.has_impact,
                self.has_payment,
                self.active_search or self.switching_intent,
            )
        )


def research_case_candidates(
    repository: Repository,
    *,
    sort_by: CandidateSort = "strongest-evidence",
    include_opened: bool = False,
    algorithm_version: str = "exact-fingerprint-v1",
) -> tuple[ResearchCaseCandidate, ...]:
    """Return explainable clusters that may justify an additional research pass.

    `research_ready` is deliberately narrow: it means recurrence is present or at
    least one observation meets the shared strong-signal policy. It is not a
    statement about market quality, commercial viability, or whether anything
    should be built.
    """

    valid_sorts = {
        "strongest-evidence",
        "newest",
        "active-search",
        "payment-evidence",
        "manual-workarounds",
        "dach-evidence",
    }
    if sort_by not in valid_sorts:
        raise ValueError(f"unknown candidate sort: {sort_by}")
    if not algorithm_version.strip():
        raise ValueError("algorithm version must not be empty")

    rows = repository.connection.execute(
        """SELECT pc.id AS cluster_id, pc.algorithm_version,
                  po.id AS observation_id, po.source_item_id, si.source_id,
                  po.problem_type, po.problem_family, po.problem,
                  po.evidence_scope,
                  COALESCE(po.country_code, si.country_code) AS country_code,
                  po.created_at,
                  COALESCE(po.active_solution_search, 0) AS active_search,
                  COALESCE(po.switching_intent, 0) AS switching_intent,
                  (po.actor IS NOT NULL OR po.actor_role IS NOT NULL) AS has_actor,
                  (po.job_to_be_done IS NOT NULL) AS has_job,
                  (po.context IS NOT NULL) AS has_context,
                  (po.current_workaround IS NOT NULL OR EXISTS (
                      SELECT 1 FROM workarounds w WHERE w.observation_id = po.id
                  )) AS has_workaround,
                  (po.time_impact IS NOT NULL OR po.financial_impact IS NOT NULL
                   OR po.revenue_impact IS NOT NULL OR po.error_impact IS NOT NULL
                   OR po.delay_impact IS NOT NULL OR po.risk_impact IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM impact_signals i WHERE i.observation_id = po.id
                   )) AS has_impact,
                  EXISTS (
                      SELECT 1 FROM impact_signals i
                      WHERE i.observation_id = po.id AND i.quantified = 1
                  ) AS has_quantified_impact,
                  (po.existing_spend IS NOT NULL OR po.paid_workaround IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM payment_signals p WHERE p.observation_id = po.id
                   )) AS has_payment,
                  EXISTS (
                      SELECT 1 FROM evidence_spans es WHERE es.observation_id = po.id
                  ) AS has_evidence,
                  (SELECT MIN(rc.id) FROM research_cases rc
                   WHERE rc.cluster_id = pc.id) AS existing_case_id
           FROM problem_clusters pc
           JOIN cluster_members cm ON cm.cluster_id = pc.id
           JOIN problem_observations po ON po.id = cm.observation_id
           JOIN source_items si ON si.id = po.source_item_id
           LEFT JOIN pipeline_runs pr ON pr.id = po.pipeline_run_id
           WHERE pc.algorithm_version = ?
             AND (po.pipeline_run_id IS NULL OR pr.status = 'COMPLETED')
           ORDER BY pc.id, po.id""",
        (algorithm_version,),
    ).fetchall()
    by_cluster: dict[int, list[_ObservationSignal]] = {}
    cluster_meta: dict[int, tuple[str, int | None]] = {}
    for row in rows:
        cluster_id = int(row["cluster_id"])
        cluster_meta[cluster_id] = (
            str(row["algorithm_version"]),
            int(row["existing_case_id"]) if row["existing_case_id"] is not None else None,
        )
        by_cluster.setdefault(cluster_id, []).append(
            _ObservationSignal(
                observation_id=int(row["observation_id"]),
                source_item_id=int(row["source_item_id"]),
                source_id=int(row["source_id"]),
                problem_type=ProblemType(row["problem_type"]),
                problem_family=(
                    ProblemFamily(row["problem_family"])
                    if row["problem_family"] is not None
                    else None
                ),
                problem=str(row["problem"]),
                scope=EvidenceScope(row["evidence_scope"]),
                country_code=row["country_code"],
                created_at=str(row["created_at"]),
                active_search=bool(row["active_search"]),
                switching_intent=bool(row["switching_intent"]),
                has_actor=bool(row["has_actor"]),
                has_job=bool(row["has_job"]),
                has_context=bool(row["has_context"]),
                has_workaround=bool(row["has_workaround"]),
                has_impact=bool(row["has_impact"]),
                has_quantified_impact=bool(row["has_quantified_impact"]),
                has_payment=bool(row["has_payment"]),
                has_evidence=bool(row["has_evidence"]),
            )
        )

    candidates = tuple(
        _candidate(cluster_id, cluster_meta[cluster_id], observations)
        for cluster_id, observations in by_cluster.items()
        if include_opened or cluster_meta[cluster_id][1] is None
    )
    return tuple(sorted(candidates, key=lambda item: _sort_key(item, sort_by), reverse=True))


def _candidate(
    cluster_id: int,
    meta: tuple[str, int | None],
    observations: list[_ObservationSignal],
) -> ResearchCaseCandidate:
    source_count = len({item.source_id for item in observations})
    item_count = len({item.source_item_id for item in observations})
    scopes = {item.scope for item in observations}
    if EvidenceScope.GLOBAL in scopes and EvidenceScope.DACH in scopes:
        state = EvidenceState.CROSS_MARKET
    elif source_count >= 2:
        state = EvidenceState.MULTI_SOURCE
    elif item_count >= 3:
        state = EvidenceState.RECURRING
    elif item_count >= 2:
        state = EvidenceState.EMERGING
    else:
        state = EvidenceState.SINGLE_SIGNAL

    active = sum(item.active_search for item in observations)
    switching = sum(item.switching_intent for item in observations)
    quantified = sum(item.has_quantified_impact for item in observations)
    payment = sum(item.has_payment for item in observations)
    workaround = sum(item.has_workaround for item in observations)
    strong = sum(
        is_strong_individual_signal(
            allowed_problem_type=item.problem_type not in _EXCLUDED_TYPES,
            has_actor=item.has_actor,
            has_job=item.has_job,
            has_context=item.has_context,
            has_workaround=item.has_workaround,
            has_quantified_impact=item.has_quantified_impact,
            has_payment=item.has_payment,
            active_search=item.active_search,
            switching_intent=item.switching_intent,
        )
        for item in observations
    )
    excluded_only = all(item.problem_type in _EXCLUDED_TYPES for item in observations)
    recurring = item_count >= 2
    research_ready = not excluded_only and (recurring or strong > 0)
    exclusion_reason: str | None = None
    if excluded_only:
        exclusion_reason = "cluster contains only incidents, support questions, or user errors"
    elif not research_ready:
        exclusion_reason = "no recurrence or strong individual signal established"

    reasons: list[str] = []
    if state is EvidenceState.CROSS_MARKET:
        reasons.append("global and DACH evidence are both present")
    if source_count >= 2:
        reasons.append(f"confirmed across {source_count} sources")
    if item_count >= 2:
        reasons.append(f"observed in {item_count} source items")
    if strong:
        reasons.append(f"{strong} strong individual signal(s)")
    if active:
        reasons.append(f"{active} active solution search signal(s)")
    if switching:
        reasons.append(f"{switching} switching intent signal(s)")
    if quantified:
        reasons.append(f"{quantified} quantified impact signal(s)")
    if payment:
        reasons.append(f"{payment} payment evidence signal(s)")
    if workaround:
        reasons.append(f"{workaround} documented workaround(s)")

    completion_observation = max(
        observations,
        key=lambda item: (
            sum((item.has_actor, item.has_job, item.has_context, item.has_evidence)),
            item.strength_dimensions,
            item.created_at,
            -item.observation_id,
        ),
    )
    missing_for_completion = tuple(
        name
        for name, present in (
            ("actor", completion_observation.has_actor),
            ("job_to_be_done", completion_observation.has_job),
            ("context", completion_observation.has_context),
            ("exact_evidence_span", completion_observation.has_evidence),
        )
        if not present
    )
    minimum_complete = not missing_for_completion
    if minimum_complete:
        reasons.append("minimum problem evidence is complete")

    representative = max(
        observations,
        key=lambda item: (item.strength_dimensions, item.created_at, -item.observation_id),
    )
    families = {item.problem_family for item in observations if item.problem_family is not None}
    return ResearchCaseCandidate(
        cluster_id=cluster_id,
        algorithm_version=meta[0],
        representative_problem=representative.problem,
        problem_family=next(iter(families)) if len(families) == 1 else None,
        evidence_state=state,
        observation_count=len(observations),
        source_count=source_count,
        country_count=len(
            {item.country_code for item in observations if item.country_code is not None}
        ),
        global_observation_count=sum(
            item.scope is EvidenceScope.GLOBAL for item in observations
        ),
        dach_observation_count=sum(item.scope is EvidenceScope.DACH for item in observations),
        active_search_count=active,
        switching_intent_count=switching,
        quantified_impact_count=quantified,
        payment_evidence_count=payment,
        workaround_count=workaround,
        strong_individual_signal_count=strong,
        research_ready=research_ready,
        exclusion_reason=exclusion_reason,
        minimum_problem_evidence_complete=minimum_complete,
        missing_for_completion=missing_for_completion,
        existing_case_id=meta[1],
        latest_observation_at=max(item.created_at for item in observations),
        reasons=tuple(reasons),
    )


def _sort_key(candidate: ResearchCaseCandidate, sort_by: CandidateSort) -> tuple[Any, ...]:
    common = (
        candidate.research_ready,
        _STATE_STRENGTH[candidate.evidence_state],
        candidate.observation_count,
        candidate.cluster_id,
    )
    if sort_by == "newest":
        return candidate.latest_observation_at, *common
    if sort_by == "active-search":
        return candidate.active_search_count + candidate.switching_intent_count, *common
    if sort_by == "payment-evidence":
        return candidate.payment_evidence_count, *common
    if sort_by == "manual-workarounds":
        return candidate.workaround_count, *common
    if sort_by == "dach-evidence":
        return candidate.dach_observation_count, *common
    return (
        candidate.research_ready,
        _STATE_STRENGTH[candidate.evidence_state],
        candidate.payment_evidence_count,
        candidate.quantified_impact_count,
        candidate.active_search_count + candidate.switching_intent_count,
        candidate.workaround_count,
        candidate.strong_individual_signal_count,
        candidate.observation_count,
        candidate.latest_observation_at,
        candidate.cluster_id,
    )

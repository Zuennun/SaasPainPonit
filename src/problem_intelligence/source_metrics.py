"""Versioned empirical source-performance snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from typing import Any

from .domain import SourceLifecycle
from .repository import Repository
from .signal_policy import strong_individual_signal_sql

METRIC_VERSION = "source-metrics-v1+exact-fingerprint-v1"


@dataclass(frozen=True, slots=True)
class ProblemFamilyPerformance:
    source_id: int
    source_name: str
    problem_family: str
    observation_count: int
    strong_signal_count: int
    active_search_count: int
    payment_signal_count: int
    cluster_count: int
    first_seen: str | None
    last_seen: str | None
    items_scanned: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(
            {
                "observation_yield_per_1000": _yield(
                    self.observation_count, self.items_scanned
                ),
                "strong_signal_yield_per_1000": _yield(
                    self.strong_signal_count, self.items_scanned
                ),
                "active_search_yield_per_1000": _yield(
                    self.active_search_count, self.items_scanned
                ),
                "payment_signal_yield_per_1000": _yield(
                    self.payment_signal_count, self.items_scanned
                ),
                "cluster_yield_per_1000": _yield(self.cluster_count, self.items_scanned),
            }
        )
        return result


@dataclass(frozen=True, slots=True)
class SourceMetricSnapshot:
    source_id: int
    source_name: str
    measurement_key: str
    metric_version: str
    measurement_start: str | None
    measurement_end: str | None
    items_scanned: int
    items_after_prefilter: int | None
    pain_observations: int
    strong_single_signals: int
    active_search_signals: int
    quantified_impact_signals: int | None
    payment_signals: int
    problem_clusters_contributed: int
    cross_source_confirmations: int
    promo_items: int | None
    duplicate_items: int | None
    temporary_incidents: int
    support_questions: int
    known_processing_cost_usd: float | None
    processing_cost_complete: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(
            {
                "pain_yield_per_1000": _yield(self.pain_observations, self.items_scanned),
                "strong_signal_yield_per_1000": _yield(
                    self.strong_single_signals, self.items_scanned
                ),
                "active_search_yield_per_1000": _yield(
                    self.active_search_signals, self.items_scanned
                ),
                "payment_evidence_yield_per_1000": _yield(
                    self.payment_signals, self.items_scanned
                ),
                "cluster_contribution_yield_per_1000": _yield(
                    self.problem_clusters_contributed, self.items_scanned
                ),
                "cross_source_confirmation_yield_per_1000": _yield(
                    self.cross_source_confirmations, self.items_scanned
                ),
                "research_cost_per_strong_signal_usd": _cost_per_strong_signal(self),
                "sample_warning": (
                    "tiny sample; rates are descriptive only"
                    if self.items_scanned < 100
                    else None
                ),
            }
        )
        return result


@dataclass(frozen=True, slots=True)
class SourcePerformanceView:
    snapshot: SourceMetricSnapshot
    source_type: str
    access_method: str | None
    lifecycle: SourceLifecycle
    commercial_use_status: str | None
    production_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.snapshot.to_dict(),
            "source_type": self.source_type,
            "access_method": self.access_method,
            "lifecycle": self.lifecycle.value,
            "commercial_use_status": self.commercial_use_status,
            "production_ready": self.production_ready,
        }


@dataclass(frozen=True, slots=True)
class SourceBudgetAllocation:
    source_id: int
    source_name: str
    source_type: str
    access_method: str | None
    lifecycle: SourceLifecycle
    lane: str
    allocated_items: int
    per_source_cap: int
    previous_items_scanned: int
    rank_dimension: str
    rank_value: float | str | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["lifecycle"] = self.lifecycle.value
        return result


@dataclass(frozen=True, slots=True)
class SourceBudgetPlan:
    measurement_key: str
    performance_sort: str
    total_item_budget: int
    performance_item_budget: int
    exploration_item_budget: int
    minimum_performance_items: int
    per_source_cap: int
    allocations: tuple[SourceBudgetAllocation, ...]

    @property
    def allocated_performance_items(self) -> int:
        return sum(
            item.allocated_items for item in self.allocations if item.lane == "PERFORMANCE"
        )

    @property
    def allocated_exploration_items(self) -> int:
        return sum(
            item.allocated_items for item in self.allocations if item.lane == "EXPLORATION"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement_key": self.measurement_key,
            "performance_sort": self.performance_sort,
            "total_item_budget": self.total_item_budget,
            "performance_item_budget": self.performance_item_budget,
            "exploration_item_budget": self.exploration_item_budget,
            "minimum_performance_items": self.minimum_performance_items,
            "per_source_cap": self.per_source_cap,
            "allocated_performance_items": self.allocated_performance_items,
            "allocated_exploration_items": self.allocated_exploration_items,
            "unallocated_performance_items": (
                self.performance_item_budget - self.allocated_performance_items
            ),
            "unallocated_exploration_items": (
                self.exploration_item_budget - self.allocated_exploration_items
            ),
            "allocations": [item.to_dict() for item in self.allocations],
            "policy": {
                "production_ready_only": True,
                "automatic_lifecycle_changes": False,
                "unused_lane_budget_reallocated": False,
                "composite_score_used": False,
            },
        }


def _yield(count: int, items_scanned: int) -> float | None:
    if items_scanned == 0:
        return None
    return count * 1000.0 / items_scanned


def ranked_source_performance(
    repository: Repository,
    *,
    measurement_key: str = "cumulative",
    sort_by: str = "strong-signal-yield",
    lifecycles: tuple[SourceLifecycle, ...] = (),
    minimum_items: int = 0,
    production_ready_only: bool = False,
    limit: int | None = None,
) -> tuple[SourcePerformanceView, ...]:
    """Return one explicitly sorted source dimension without a composite score."""

    sort_dimensions = {
        "strong-signal-yield",
        "payment-yield",
        "active-search-yield",
        "cluster-yield",
        "cross-source-yield",
        "cost-per-strong-signal",
        "newest-evidence",
    }
    if sort_by not in sort_dimensions:
        raise ValueError(f"unsupported source performance sort: {sort_by}")
    if minimum_items < 0:
        raise ValueError("minimum items must not be negative")
    if limit is not None and limit < 1:
        raise ValueError("source performance limit must be positive")
    rows = repository.connection.execute(
        """SELECT sm.*, s.name, s.source_type, s.access_method,
                  s.lifecycle, s.commercial_use_status
           FROM source_metrics sm
           JOIN sources s ON s.id = sm.source_id
           WHERE sm.measurement_key = ?""",
        (measurement_key,),
    ).fetchall()
    lifecycle_filter = set(lifecycles)
    views = [
        SourcePerformanceView(
            snapshot=_stored_snapshot(row),
            source_type=str(row["source_type"]),
            access_method=row["access_method"],
            lifecycle=SourceLifecycle(row["lifecycle"]),
            commercial_use_status=row["commercial_use_status"],
            production_ready=_production_ready(row["commercial_use_status"]),
        )
        for row in rows
        if int(row["items_scanned"]) >= minimum_items
        and (
            not lifecycle_filter
            or SourceLifecycle(row["lifecycle"]) in lifecycle_filter
        )
        and (
            not production_ready_only
            or _production_ready(row["commercial_use_status"])
        )
    ]
    views.sort(key=lambda item: (item.snapshot.source_name.casefold(), item.snapshot.source_id))

    def descending_value(item: SourcePerformanceView) -> float | str:
        snapshot = item.snapshot
        if sort_by == "strong-signal-yield":
            return _yield(snapshot.strong_single_signals, snapshot.items_scanned) or 0.0
        if sort_by == "payment-yield":
            return _yield(snapshot.payment_signals, snapshot.items_scanned) or 0.0
        if sort_by == "active-search-yield":
            return _yield(snapshot.active_search_signals, snapshot.items_scanned) or 0.0
        if sort_by == "cluster-yield":
            return _yield(
                snapshot.problem_clusters_contributed, snapshot.items_scanned
            ) or 0.0
        if sort_by == "cross-source-yield":
            return _yield(
                snapshot.cross_source_confirmations, snapshot.items_scanned
            ) or 0.0
        assert sort_by == "newest-evidence"
        return snapshot.measurement_end or ""

    if sort_by == "cost-per-strong-signal":
        def cost_sort_value(item: SourcePerformanceView) -> float:
            value = _cost_per_strong_signal(item.snapshot)
            return value if value is not None else inf

        views.sort(key=cost_sort_value)
    else:
        views.sort(key=descending_value, reverse=True)
    if limit is not None:
        views = views[:limit]
    return tuple(views)


def plan_source_budget(
    repository: Repository,
    *,
    total_item_budget: int,
    exploration_item_budget: int,
    per_source_cap: int,
    minimum_performance_items: int,
    measurement_key: str = "cumulative",
    performance_sort: str = "strong-signal-yield",
) -> SourceBudgetPlan:
    """Allocate explicit performance and exploration lanes without a hidden score."""

    if total_item_budget < 1:
        raise ValueError("total item budget must be positive")
    if not 0 <= exploration_item_budget <= total_item_budget:
        raise ValueError("exploration item budget must be between zero and total budget")
    if per_source_cap < 1:
        raise ValueError("per-source cap must be positive")
    if minimum_performance_items < 1:
        raise ValueError("minimum performance items must be positive")
    if not measurement_key.strip():
        raise ValueError("measurement key must not be empty")

    performance_budget = total_item_budget - exploration_item_budget
    ranked = ranked_source_performance(
        repository,
        measurement_key=measurement_key,
        sort_by=performance_sort,
        lifecycles=(SourceLifecycle.CORE, SourceLifecycle.EXPLORATION),
        minimum_items=minimum_performance_items,
        production_ready_only=True,
    )
    ranked = tuple(
        item for item in ranked if _performance_value(item, performance_sort) is not None
    )
    performance_allocations = _allocate_performance_lane(
        ranked,
        budget=performance_budget,
        per_source_cap=per_source_cap,
        performance_sort=performance_sort,
    )
    exploration_allocations = _allocate_exploration_lane(
        repository,
        measurement_key=measurement_key,
        excluded_source_ids={item.snapshot.source_id for item in ranked},
        budget=exploration_item_budget,
        per_source_cap=per_source_cap,
    )
    return SourceBudgetPlan(
        measurement_key=measurement_key,
        performance_sort=performance_sort,
        total_item_budget=total_item_budget,
        performance_item_budget=performance_budget,
        exploration_item_budget=exploration_item_budget,
        minimum_performance_items=minimum_performance_items,
        per_source_cap=per_source_cap,
        allocations=performance_allocations + exploration_allocations,
    )


def _allocate_performance_lane(
    ranked: tuple[SourcePerformanceView, ...],
    *,
    budget: int,
    per_source_cap: int,
    performance_sort: str,
) -> tuple[SourceBudgetAllocation, ...]:
    remaining = budget
    allocations: list[SourceBudgetAllocation] = []
    for item in ranked:
        if remaining == 0:
            break
        allocated = min(per_source_cap, remaining)
        allocations.append(
            SourceBudgetAllocation(
                source_id=item.snapshot.source_id,
                source_name=item.snapshot.source_name,
                source_type=item.source_type,
                access_method=item.access_method,
                lifecycle=item.lifecycle,
                lane="PERFORMANCE",
                allocated_items=allocated,
                per_source_cap=per_source_cap,
                previous_items_scanned=item.snapshot.items_scanned,
                rank_dimension=performance_sort,
                rank_value=_performance_value(item, performance_sort),
            )
        )
        remaining -= allocated
    return tuple(allocations)


def _allocate_exploration_lane(
    repository: Repository,
    *,
    measurement_key: str,
    excluded_source_ids: set[int],
    budget: int,
    per_source_cap: int,
) -> tuple[SourceBudgetAllocation, ...]:
    rows = repository.connection.execute(
        """SELECT s.id, s.name, s.source_type, s.access_method,
                  s.lifecycle, s.commercial_use_status,
                  COALESCE(sm.items_scanned, 0) AS items_scanned,
                  COALESCE(srp.strict_pilot_posts, srp.pilot_posts) AS pilot_posts
           FROM sources s
           LEFT JOIN source_metrics sm
             ON sm.source_id = s.id AND sm.measurement_key = ?
           LEFT JOIN source_registry_profiles srp ON srp.source_id = s.id
           WHERE s.lifecycle IN ('CANDIDATE', 'EXPLORATION')
           ORDER BY items_scanned, s.name COLLATE NOCASE, s.id""",
        (measurement_key,),
    ).fetchall()
    remaining = budget
    allocations: list[SourceBudgetAllocation] = []
    for row in rows:
        source_id = int(row["id"])
        if (
            remaining == 0
            or source_id in excluded_source_ids
            or not _production_ready(row["commercial_use_status"])
        ):
            continue
        profile_cap = int(row["pilot_posts"]) if row["pilot_posts"] is not None else None
        effective_cap = (
            min(per_source_cap, profile_cap)
            if profile_cap is not None
            else per_source_cap
        )
        if effective_cap == 0:
            continue
        allocated = min(effective_cap, remaining)
        items_scanned = int(row["items_scanned"])
        allocations.append(
            SourceBudgetAllocation(
                source_id=source_id,
                source_name=str(row["name"]),
                source_type=str(row["source_type"]),
                access_method=row["access_method"],
                lifecycle=SourceLifecycle(row["lifecycle"]),
                lane="EXPLORATION",
                allocated_items=allocated,
                per_source_cap=effective_cap,
                previous_items_scanned=items_scanned,
                rank_dimension="least-observed-first",
                rank_value=float(items_scanned),
            )
        )
        remaining -= allocated
    return tuple(allocations)


def _performance_value(
    item: SourcePerformanceView, sort_by: str
) -> float | str | None:
    snapshot = item.snapshot
    if sort_by == "strong-signal-yield":
        return _yield(snapshot.strong_single_signals, snapshot.items_scanned)
    if sort_by == "payment-yield":
        return _yield(snapshot.payment_signals, snapshot.items_scanned)
    if sort_by == "active-search-yield":
        return _yield(snapshot.active_search_signals, snapshot.items_scanned)
    if sort_by == "cluster-yield":
        return _yield(snapshot.problem_clusters_contributed, snapshot.items_scanned)
    if sort_by == "cross-source-yield":
        return _yield(snapshot.cross_source_confirmations, snapshot.items_scanned)
    if sort_by == "cost-per-strong-signal":
        return _cost_per_strong_signal(snapshot)
    if sort_by == "newest-evidence":
        return snapshot.measurement_end
    raise ValueError(f"unsupported source performance sort: {sort_by}")


def _production_ready(status: object) -> bool:
    if not isinstance(status, str):
        return False
    normalized = status.strip().upper().replace("-", "_")
    return normalized == "APPROVED" or normalized.startswith("APPROVED_")


def _cost_per_strong_signal(snapshot: SourceMetricSnapshot) -> float | None:
    if (
        not snapshot.processing_cost_complete
        or snapshot.known_processing_cost_usd is None
        or snapshot.strong_single_signals == 0
    ):
        return None
    return snapshot.known_processing_cost_usd / snapshot.strong_single_signals


def _stored_snapshot(row: Any) -> SourceMetricSnapshot:
    return SourceMetricSnapshot(
        source_id=int(row["source_id"]),
        source_name=str(row["name"]),
        measurement_key=str(row["measurement_key"]),
        metric_version=str(row["metric_version"]),
        measurement_start=row["measurement_start"],
        measurement_end=row["measurement_end"],
        items_scanned=int(row["items_scanned"]),
        items_after_prefilter=(
            int(row["items_after_prefilter"])
            if row["items_after_prefilter"] is not None
            else None
        ),
        pain_observations=int(row["pain_observations"]),
        strong_single_signals=int(row["strong_single_signals"]),
        active_search_signals=int(row["active_search_signals"]),
        quantified_impact_signals=(
            int(row["quantified_impact_signals"])
            if row["quantified_impact_signals"] is not None
            else None
        ),
        payment_signals=int(row["payment_signals"]),
        problem_clusters_contributed=int(row["problem_clusters_contributed"]),
        cross_source_confirmations=int(row["cross_source_confirmations"]),
        promo_items=int(row["promo_items"]) if row["promo_items"] is not None else None,
        duplicate_items=(
            int(row["duplicate_items"])
            if row["duplicate_items"] is not None
            else None
        ),
        temporary_incidents=int(row["temporary_incidents"]),
        support_questions=int(row["support_questions"]),
        known_processing_cost_usd=(
            float(row["known_processing_cost_usd"])
            if row["known_processing_cost_usd"] is not None
            else None
        ),
        processing_cost_complete=bool(row["processing_cost_complete"]),
    )


def refresh_source_metrics(
    repository: Repository,
    *,
    measurement_key: str = "cumulative",
) -> tuple[SourceMetricSnapshot, ...]:
    """Persist current cumulative measurements without inventing missing counters."""

    if not measurement_key.strip():
        raise ValueError("measurement key must not be empty")
    sources = repository.connection.execute(
        """SELECT s.id, s.name,
                  EXISTS(SELECT 1 FROM discovery_records d WHERE d.source_id = s.id)
                      AS has_discovery,
                  EXISTS(SELECT 1 FROM source_items si WHERE si.source_id = s.id)
                      AS has_items
           FROM sources s
           WHERE EXISTS(SELECT 1 FROM discovery_records d WHERE d.source_id = s.id)
              OR EXISTS(SELECT 1 FROM source_items si WHERE si.source_id = s.id)
           ORDER BY s.id"""
    ).fetchall()
    snapshots = tuple(
        _measure_source(
            repository,
            source_id=int(source["id"]),
            source_name=str(source["name"]),
            measurement_key=measurement_key,
            has_discovery=bool(source["has_discovery"]),
        )
        for source in sources
    )
    strong_family_signal = strong_individual_signal_sql("po")
    with repository.transaction() as connection:
        for snapshot in snapshots:
            connection.execute(
                """INSERT INTO source_metrics (
                       source_id, measurement_key, metric_version,
                       measurement_start, measurement_end, items_scanned,
                       items_after_prefilter, pain_observations, strong_single_signals,
                       active_search_signals, quantified_impact_signals, payment_signals,
                       problem_clusters_contributed, cross_source_confirmations,
                       promo_items, duplicate_items, temporary_incidents,
                       support_questions, known_processing_cost_usd,
                       processing_cost_complete
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, measurement_key) DO UPDATE SET
                       metric_version = excluded.metric_version,
                       measurement_start = excluded.measurement_start,
                       measurement_end = excluded.measurement_end,
                       items_scanned = excluded.items_scanned,
                       items_after_prefilter = excluded.items_after_prefilter,
                       pain_observations = excluded.pain_observations,
                       strong_single_signals = excluded.strong_single_signals,
                       active_search_signals = excluded.active_search_signals,
                       quantified_impact_signals = excluded.quantified_impact_signals,
                       payment_signals = excluded.payment_signals,
                       problem_clusters_contributed = excluded.problem_clusters_contributed,
                       cross_source_confirmations = excluded.cross_source_confirmations,
                       promo_items = excluded.promo_items,
                       duplicate_items = excluded.duplicate_items,
                       temporary_incidents = excluded.temporary_incidents,
                       support_questions = excluded.support_questions,
                       known_processing_cost_usd = excluded.known_processing_cost_usd,
                       processing_cost_complete = excluded.processing_cost_complete,
                       measured_at = CURRENT_TIMESTAMP""",
                _snapshot_values(snapshot),
            )
        connection.execute(
            "DELETE FROM source_problem_family_metrics WHERE measurement_key = ?",
            (measurement_key,),
        )
        connection.execute(
            f"""INSERT INTO source_problem_family_metrics (
                   source_id, measurement_key, problem_family, metric_version,
                   observation_count, strong_signal_count, active_search_count,
                   payment_signal_count, cluster_count, first_seen, last_seen
               )
               SELECT si.source_id, :measurement_key, po.problem_family, :metric_version,
                      COUNT(*) AS observation_count,
                      SUM(CASE WHEN {strong_family_signal}
                          THEN 1 ELSE 0 END) AS strong_signal_count,
                      SUM(CASE WHEN po.active_solution_search = 1 THEN 1 ELSE 0 END),
                      (SELECT COUNT(*) FROM payment_signals p
                       JOIN problem_observations ppo ON ppo.id = p.observation_id
                       JOIN source_items psi ON psi.id = ppo.source_item_id
                       LEFT JOIN pipeline_runs ppr ON ppr.id = ppo.pipeline_run_id
                       WHERE psi.source_id = si.source_id
                         AND ppo.problem_family = po.problem_family
                         AND (ppo.pipeline_run_id IS NULL OR ppr.status = 'COMPLETED')),
                      COUNT(DISTINCT cm.cluster_id),
                      MIN(si.first_seen_at), MAX(si.last_seen_at)
               FROM problem_observations po
               JOIN source_items si ON si.id = po.source_item_id
               LEFT JOIN pipeline_runs pr ON pr.id = po.pipeline_run_id
               LEFT JOIN cluster_members cm
                 ON cm.observation_id = po.id
                AND cm.cluster_id IN (
                    SELECT id FROM problem_clusters
                    WHERE algorithm_version = 'exact-fingerprint-v1'
                )
               WHERE po.problem_family IS NOT NULL
                 AND (po.pipeline_run_id IS NULL OR pr.status = 'COMPLETED')
               GROUP BY si.source_id, po.problem_family""",
            {"measurement_key": measurement_key, "metric_version": METRIC_VERSION},
        )
    return snapshots


def source_problem_family_performance(
    repository: Repository,
    *,
    measurement_key: str = "cumulative",
) -> tuple[ProblemFamilyPerformance, ...]:
    rows = repository.connection.execute(
        """SELECT pf.*, s.name, sm.items_scanned
           FROM source_problem_family_metrics pf
           JOIN sources s ON s.id = pf.source_id
           JOIN source_metrics sm
             ON sm.source_id = pf.source_id
            AND sm.measurement_key = pf.measurement_key
           WHERE pf.measurement_key = ?
           ORDER BY pf.problem_family, pf.observation_count DESC,
                    s.name COLLATE NOCASE""",
        (measurement_key,),
    ).fetchall()
    return tuple(
        ProblemFamilyPerformance(
            source_id=int(row["source_id"]),
            source_name=str(row["name"]),
            problem_family=str(row["problem_family"]),
            observation_count=int(row["observation_count"]),
            strong_signal_count=int(row["strong_signal_count"]),
            active_search_count=int(row["active_search_count"]),
            payment_signal_count=int(row["payment_signal_count"]),
            cluster_count=int(row["cluster_count"]),
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            items_scanned=int(row["items_scanned"]),
        )
        for row in rows
    )


def _measure_source(
    repository: Repository,
    *,
    source_id: int,
    source_name: str,
    measurement_key: str,
    has_discovery: bool,
) -> SourceMetricSnapshot:
    strong_source_signal = strong_individual_signal_sql("o")
    row = repository.connection.execute(
        f"""WITH source_observations AS (
               SELECT po.* FROM problem_observations po
               JOIN source_items si ON si.id = po.source_item_id
               LEFT JOIN pipeline_runs pr ON pr.id = po.pipeline_run_id
               WHERE si.source_id = :source_id
                 AND (po.pipeline_run_id IS NULL OR pr.status = 'COMPLETED')
           ), source_clusters AS (
               SELECT DISTINCT cm.cluster_id
               FROM cluster_members cm
               JOIN problem_clusters pc ON pc.id = cm.cluster_id
               JOIN problem_observations po ON po.id = cm.observation_id
               JOIN source_items si ON si.id = po.source_item_id
               WHERE si.source_id = :source_id
                 AND pc.algorithm_version = 'exact-fingerprint-v1'
           )
           SELECT
             (SELECT COUNT(*) FROM source_items WHERE source_id = :source_id) AS item_count,
             (SELECT COUNT(DISTINCT canonical_url) FROM discovery_records
                WHERE source_id = :source_id) AS discovered_unique,
             (SELECT COALESCE(SUM(reddit_urls_discovered), 0) FROM discovery_runs
                WHERE source_id = :source_id) AS discovered_total,
             (SELECT MIN(value) FROM (
                 SELECT MIN(discovered_at) AS value FROM discovery_records
                    WHERE source_id = :source_id
                 UNION ALL
                 SELECT MIN(first_seen_at) AS value FROM source_items
                    WHERE source_id = :source_id
             )) AS measurement_start,
             (SELECT MAX(value) FROM (
                 SELECT MAX(discovered_at) AS value FROM discovery_records
                    WHERE source_id = :source_id
                 UNION ALL
                 SELECT MAX(last_seen_at) AS value FROM source_items
                    WHERE source_id = :source_id
             )) AS measurement_end,
             (SELECT COUNT(DISTINCT a.source_item_id) FROM acquisition_records a
                JOIN discovery_records d ON d.id = a.discovery_id
                JOIN source_items si ON si.id = a.source_item_id
                WHERE d.source_id = :source_id
                  AND a.completeness IN ('FULL','PARTIAL')
                  AND length(si.raw_text) >= 40) AS after_prefilter,
             (SELECT COUNT(*) FROM source_observations) AS observations,
             (SELECT COUNT(*) FROM source_observations o
                WHERE {strong_source_signal}) AS strong_signals,
             (SELECT COUNT(*) FROM source_observations
                WHERE active_solution_search = 1) AS active_searches,
             (SELECT COUNT(*) FROM payment_signals p
                JOIN source_observations o ON o.id = p.observation_id)
                AS payment_signals,
             (SELECT COUNT(*) FROM impact_signals i
                JOIN source_observations o ON o.id = i.observation_id
                WHERE i.quantified = 1) AS quantified_impacts,
             (SELECT COUNT(*) FROM source_clusters) AS clusters_contributed,
             (SELECT COUNT(*) FROM source_clusters sc WHERE EXISTS (
                 SELECT 1 FROM cluster_members cm
                 JOIN problem_observations po ON po.id = cm.observation_id
                 JOIN source_items si ON si.id = po.source_item_id
                 WHERE cm.cluster_id = sc.cluster_id AND si.source_id <> :source_id
             )) AS cross_source_confirmations,
             (SELECT COUNT(*) FROM source_observations
                WHERE problem_type = 'TEMPORARY_INCIDENT') AS temporary_incidents,
             (SELECT COUNT(*) FROM source_observations
                WHERE problem_type = 'SUPPORT_QUESTION') AS support_questions,
             (SELECT COALESCE(SUM(cost_usd), 0) FROM discovery_runs
                WHERE source_id = :source_id)
               + (SELECT COALESCE(SUM(a.cost_usd), 0) FROM acquisition_records a
                  JOIN discovery_records d ON d.id = a.discovery_id
                  WHERE d.source_id = :source_id) AS known_cost,
             (SELECT COUNT(*) FROM discovery_runs WHERE source_id = :source_id)
               + (SELECT COUNT(*) FROM acquisition_records a
                  JOIN discovery_records d ON d.id = a.discovery_id
                  WHERE d.source_id = :source_id) AS cost_records,
             (SELECT COUNT(*) FROM discovery_runs
                WHERE source_id = :source_id AND cost_usd IS NULL)
               + (SELECT COUNT(*) FROM acquisition_records a
                  JOIN discovery_records d ON d.id = a.discovery_id
                  WHERE d.source_id = :source_id AND a.cost_usd IS NULL)
                AS unknown_cost_records""",
        {"source_id": source_id},
    ).fetchone()
    assert row is not None
    cost_complete = int(row["cost_records"]) > 0 and int(row["unknown_cost_records"]) == 0
    items_scanned = int(row["discovered_unique"] if has_discovery else row["item_count"])
    return SourceMetricSnapshot(
        source_id=source_id,
        source_name=source_name,
        measurement_key=measurement_key,
        metric_version=METRIC_VERSION,
        measurement_start=row["measurement_start"],
        measurement_end=row["measurement_end"],
        items_scanned=items_scanned,
        items_after_prefilter=int(row["after_prefilter"]) if has_discovery else None,
        pain_observations=int(row["observations"]),
        strong_single_signals=int(row["strong_signals"]),
        active_search_signals=int(row["active_searches"]),
        quantified_impact_signals=int(row["quantified_impacts"]),
        payment_signals=int(row["payment_signals"]),
        problem_clusters_contributed=int(row["clusters_contributed"]),
        cross_source_confirmations=int(row["cross_source_confirmations"]),
        # Promotion has no classifier/storage field yet and therefore remains unknown.
        promo_items=None,
        duplicate_items=(
            max(0, int(row["discovered_total"]) - int(row["discovered_unique"]))
            if has_discovery
            else None
        ),
        temporary_incidents=int(row["temporary_incidents"]),
        support_questions=int(row["support_questions"]),
        known_processing_cost_usd=(float(row["known_cost"]) if cost_complete else None),
        processing_cost_complete=cost_complete,
    )


def _snapshot_values(snapshot: SourceMetricSnapshot) -> tuple[Any, ...]:
    return (
        snapshot.source_id,
        snapshot.measurement_key,
        snapshot.metric_version,
        snapshot.measurement_start,
        snapshot.measurement_end,
        snapshot.items_scanned,
        snapshot.items_after_prefilter,
        snapshot.pain_observations,
        snapshot.strong_single_signals,
        snapshot.active_search_signals,
        snapshot.quantified_impact_signals,
        snapshot.payment_signals,
        snapshot.problem_clusters_contributed,
        snapshot.cross_source_confirmations,
        snapshot.promo_items,
        snapshot.duplicate_items,
        snapshot.temporary_incidents,
        snapshot.support_questions,
        snapshot.known_processing_cost_usd,
        int(snapshot.processing_cost_complete),
    )

"""Measured cost coverage and unit economics without estimated attribution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .repository import Repository
from .signal_policy import strong_individual_signal_sql


@dataclass(frozen=True, slots=True)
class MeasuredUnitCost:
    status: str
    amount_decimal: str | None
    currency: str | None
    denominator: int
    unavailable_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["unavailable_reasons"] = list(self.unavailable_reasons)
        return result


@dataclass(frozen=True, slots=True)
class ModelCostSummary:
    run_count: int
    completed_run_count: int
    failed_run_count: int
    costed_run_count: int
    missing_cost_run_count: int
    pipeline_linked_run_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    items_processed: int
    strong_signal_observations: int
    linked_complete_research_cases: int
    known_cost_by_currency: dict[str, str]
    cost_per_processed_item: MeasuredUnitCost
    cost_per_useful_observation: MeasuredUnitCost
    cost_per_linked_complete_research_case: MeasuredUnitCost

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "completed_run_count": self.completed_run_count,
            "failed_run_count": self.failed_run_count,
            "costed_run_count": self.costed_run_count,
            "missing_cost_run_count": self.missing_cost_run_count,
            "cost_coverage_rate": _ratio_or_none(
                self.costed_run_count, self.run_count
            ),
            "pipeline_linked_run_count": self.pipeline_linked_run_count,
            "pipeline_attribution_rate": _ratio_or_none(
                self.pipeline_linked_run_count, self.run_count
            ),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "items_processed": self.items_processed,
            "strong_signal_observations": self.strong_signal_observations,
            "linked_complete_research_cases": self.linked_complete_research_cases,
            "known_cost_by_currency": self.known_cost_by_currency,
            "cost_per_processed_item": self.cost_per_processed_item.to_dict(),
            "cost_per_useful_observation": self.cost_per_useful_observation.to_dict(),
            "cost_per_linked_complete_research_case": (
                self.cost_per_linked_complete_research_case.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class AcquisitionCostSummary:
    operation_count: int
    discovery_run_count: int
    acquisition_attempt_count: int
    costed_operation_count: int
    missing_cost_operation_count: int
    acquired_source_items: int
    known_cost_usd: str
    cost_per_acquired_source_item: MeasuredUnitCost

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "cost_coverage_rate": _ratio_or_none(
                self.costed_operation_count, self.operation_count
            ),
            "cost_per_acquired_source_item": self.cost_per_acquired_source_item.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CostEfficiencyReport:
    provider_filter: str | None
    pipeline_stage_filter: str | None
    acquisition: AcquisitionCostSummary
    model: ModelCostSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_filter": self.provider_filter,
            "pipeline_stage_filter": self.pipeline_stage_filter,
            "acquisition": self.acquisition.to_dict(),
            "model": self.model.to_dict(),
            "end_to_end_cost_per_research_case": {
                "status": "UNKNOWN",
                "amount_decimal": None,
                "currency": None,
                "reason": (
                    "Not calculated: source acquisition, model operations, and human "
                    "research do not share complete exact case-level cost attribution."
                ),
            },
            "interpretation": (
                "Amounts are measured provider costs only; they exclude unrecorded human "
                "labour and are never converted or combined across currencies."
            ),
        }


def build_cost_efficiency_report(
    repository: Repository,
    *,
    provider: str | None = None,
    pipeline_stage: str | None = None,
) -> CostEfficiencyReport:
    clean_provider = provider.strip() if provider and provider.strip() else None
    clean_stage = pipeline_stage.strip() if pipeline_stage and pipeline_stage.strip() else None
    return CostEfficiencyReport(
        provider_filter=clean_provider,
        pipeline_stage_filter=clean_stage,
        acquisition=_acquisition_costs(repository, clean_provider),
        model=_model_costs(repository, clean_provider, clean_stage),
    )


def _acquisition_costs(
    repository: Repository, provider: str | None
) -> AcquisitionCostSummary:
    discovery_where = "WHERE provider = ?" if provider else ""
    acquisition_where = "WHERE provider = ?" if provider else ""
    parameters = (provider,) if provider else ()
    discovery_rows = repository.connection.execute(
        f"SELECT cost_usd FROM discovery_runs {discovery_where}",
        parameters,
    ).fetchall()
    acquisition_rows = repository.connection.execute(
        f"SELECT cost_usd FROM acquisition_records {acquisition_where}",
        parameters,
    ).fetchall()
    item_row = repository.connection.execute(
        f"""SELECT COUNT(DISTINCT source_item_id) AS items
            FROM acquisition_records {acquisition_where}""",
        parameters,
    ).fetchone()
    assert item_row is not None
    discovery_count = len(discovery_rows)
    acquisition_count = len(acquisition_rows)
    operation_count = discovery_count + acquisition_count
    cost_values = [
        Decimal(str(row["cost_usd"]))
        for row in (*discovery_rows, *acquisition_rows)
        if row["cost_usd"] is not None
    ]
    costed = len(cost_values)
    known_cost = sum(cost_values, Decimal("0"))
    items = int(item_row["items"])
    return AcquisitionCostSummary(
        operation_count=operation_count,
        discovery_run_count=discovery_count,
        acquisition_attempt_count=acquisition_count,
        costed_operation_count=costed,
        missing_cost_operation_count=operation_count - costed,
        acquired_source_items=items,
        known_cost_usd=_decimal_text(known_cost),
        cost_per_acquired_source_item=_unit_cost(
            totals={"USD": known_cost},
            operation_count=operation_count,
            costed_operation_count=costed,
            denominator=items,
            denominator_name="acquired source items",
        ),
    )


def _model_costs(
    repository: Repository, provider: str | None, pipeline_stage: str | None
) -> ModelCostSummary:
    clauses: list[str] = []
    parameters: list[str] = []
    if provider:
        clauses.append("mr.provider = ?")
        parameters.append(provider)
    if pipeline_stage:
        clauses.append("mr.pipeline_stage = ?")
        parameters.append(pipeline_stage)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = repository.connection.execute(
        f"""SELECT mr.*, ce.amount_decimal, ce.currency
            FROM model_runs mr
            LEFT JOIN cost_events ce ON ce.model_run_id = mr.id
            {where}
            ORDER BY mr.recorded_at, mr.id""",
        tuple(parameters),
    ).fetchall()
    run_ids = tuple(str(row["pipeline_run_id"]) for row in rows if row["pipeline_run_id"])
    strong_count, case_count = _linked_useful_outputs(repository, run_ids)
    totals: dict[str, Decimal] = {}
    for row in rows:
        if row["amount_decimal"] is None:
            continue
        currency = str(row["currency"])
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(
            str(row["amount_decimal"])
        )
    run_count = len(rows)
    costed = sum(row["amount_decimal"] is not None for row in rows)
    linked = sum(row["pipeline_run_id"] is not None for row in rows)
    output_attribution_reasons = (
        (_missing_pipeline_link_reason(run_count - linked),)
        if run_count != linked
        else ()
    )
    return ModelCostSummary(
        run_count=run_count,
        completed_run_count=sum(row["status"] == "COMPLETED" for row in rows),
        failed_run_count=sum(row["status"] == "FAILED" for row in rows),
        costed_run_count=costed,
        missing_cost_run_count=run_count - costed,
        pipeline_linked_run_count=linked,
        input_tokens=sum(int(row["input_tokens"]) for row in rows),
        output_tokens=sum(int(row["output_tokens"]) for row in rows),
        latency_ms=sum(int(row["latency_ms"]) for row in rows),
        items_processed=sum(int(row["items_processed"]) for row in rows),
        strong_signal_observations=strong_count,
        linked_complete_research_cases=case_count,
        known_cost_by_currency={
            currency: _decimal_text(amount) for currency, amount in sorted(totals.items())
        },
        cost_per_processed_item=_unit_cost(
            totals=totals,
            operation_count=run_count,
            costed_operation_count=costed,
            denominator=sum(int(row["items_processed"]) for row in rows),
            denominator_name="processed items",
        ),
        cost_per_useful_observation=_unit_cost(
            totals=totals,
            operation_count=run_count,
            costed_operation_count=costed,
            denominator=strong_count,
            denominator_name="strong-signal observations",
            additional_reasons=output_attribution_reasons,
        ),
        cost_per_linked_complete_research_case=_unit_cost(
            totals=totals,
            operation_count=run_count,
            costed_operation_count=costed,
            denominator=case_count,
            denominator_name="linked complete research cases",
            additional_reasons=output_attribution_reasons,
        ),
    )


def _linked_useful_outputs(
    repository: Repository, pipeline_run_ids: tuple[str, ...]
) -> tuple[int, int]:
    if not pipeline_run_ids:
        return 0, 0
    placeholders = ", ".join("?" for _ in pipeline_run_ids)
    strong_predicate = strong_individual_signal_sql("po")
    strong = repository.connection.execute(
        f"""SELECT COUNT(*) FROM problem_observations po
            JOIN pipeline_runs pr ON pr.id = po.pipeline_run_id
            WHERE po.pipeline_run_id IN ({placeholders})
              AND pr.status = 'COMPLETED'
              AND {strong_predicate}""",
        pipeline_run_ids,
    ).fetchone()
    cases = repository.connection.execute(
        f"""SELECT COUNT(DISTINCT rc.id)
            FROM research_cases rc
            JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
            JOIN problem_observations po ON po.id = cm.observation_id
            WHERE rc.status = 'COMPLETE'
              AND po.pipeline_run_id IN ({placeholders})""",
        pipeline_run_ids,
    ).fetchone()
    assert strong is not None and cases is not None
    return int(strong[0]), int(cases[0])


def _unit_cost(
    *,
    totals: dict[str, Decimal],
    operation_count: int,
    costed_operation_count: int,
    denominator: int,
    denominator_name: str,
    additional_reasons: tuple[str, ...] = (),
) -> MeasuredUnitCost:
    reasons = list(additional_reasons)
    if operation_count == 0:
        reasons.append("no operations recorded")
    missing = operation_count - costed_operation_count
    if missing:
        reasons.append(
            "1 operation has unknown cost"
            if missing == 1
            else f"{missing} operations have unknown cost"
        )
    if len(totals) > 1:
        reasons.append("measured costs use multiple currencies")
    if denominator == 0:
        reasons.append(f"no {denominator_name} recorded")
    if reasons:
        return MeasuredUnitCost("UNKNOWN", None, None, denominator, tuple(reasons))
    assert len(totals) == 1
    currency, amount = next(iter(totals.items()))
    return MeasuredUnitCost(
        "AVAILABLE",
        _decimal_text(amount / denominator),
        currency,
        denominator,
        (),
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return "0" if rendered == "-0" else rendered


def _ratio_or_none(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _missing_pipeline_link_reason(count: int) -> str:
    if count == 1:
        return "1 model run lacks a pipeline_run_id"
    return f"{count} model runs lack a pipeline_run_id"

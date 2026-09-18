"""Strict benchmarks for competition recall and DACH-transfer classification."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .benchmark import (
    BenchmarkProvenance,
    BenchmarkValidationError,
    parse_benchmark_provenance,
)
from .domain import (
    ActorEquivalence,
    DachTransferType,
    LocalEvidenceState,
    SolutionType,
    WorkflowEquivalence,
)
from .normalization import normalize_identifier, normalize_url


@dataclass(frozen=True, slots=True)
class CompetitionSolutionLabel:
    name: str
    solution_type: SolutionType
    url: str | None


@dataclass(frozen=True, slots=True)
class CompetitionBenchmarkCase:
    case_id: str
    evidence_urls: tuple[str, ...]
    solutions: tuple[CompetitionSolutionLabel, ...]
    provenance: BenchmarkProvenance | None


@dataclass(frozen=True, slots=True)
class DachBenchmarkCase:
    case_id: str
    evidence_urls: tuple[str, ...]
    actor_equivalence: ActorEquivalence
    workflow_equivalence: WorkflowEquivalence
    transfer_type: DachTransferType
    local_evidence_state: LocalEvidenceState
    provenance: BenchmarkProvenance | None


ResearchBenchmarkCase = CompetitionBenchmarkCase | DachBenchmarkCase


def _jsonl(path: str | Path) -> tuple[tuple[dict[str, Any], str], ...]:
    fixture_path = Path(path)
    records: list[tuple[dict[str, Any], str]] = []
    with fixture_path.open(encoding="utf-8") as fixture:
        for line_number, line in enumerate(fixture, start=1):
            if not line.strip():
                continue
            location = f"{fixture_path}:{line_number}"
            try:
                value: object = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkValidationError(
                    f"{location}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise BenchmarkValidationError(f"{location}: line must be a JSON object")
            records.append((cast(dict[str, Any], value), location))
    if not records:
        raise BenchmarkValidationError(f"{fixture_path}: benchmark must not be empty")
    return tuple(records)


def _string(record: dict[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: {key} must be a non-empty string")
    return value.strip()


def _evidence_urls(record: dict[str, Any], location: str) -> tuple[str, ...]:
    value: object = record.get("evidence_urls")
    if not isinstance(value, list) or not value:
        raise BenchmarkValidationError(
            f"{location}: evidence_urls must be a non-empty array"
        )
    urls: list[str] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, str):
            raise BenchmarkValidationError(
                f"{location}.evidence_urls[{index}]: URL must be a string"
            )
        try:
            normalized = normalize_url(item)
        except ValueError as exc:
            raise BenchmarkValidationError(
                f"{location}.evidence_urls[{index}]: {exc}"
            ) from exc
        if normalized is None:
            raise BenchmarkValidationError(
                f"{location}.evidence_urls[{index}]: URL must not be empty"
            )
        urls.append(normalized)
    return tuple(dict.fromkeys(urls))


def _unique_case_ids(cases: Iterable[ResearchBenchmarkCase]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise BenchmarkValidationError(f"duplicate benchmark id {case.case_id!r}")
        seen.add(case.case_id)


def load_competition_benchmark(
    path: str | Path,
    *,
    require_evidence: bool = True,
    require_provenance: bool | None = None,
) -> tuple[CompetitionBenchmarkCase, ...]:
    if require_provenance is None:
        require_provenance = require_evidence
    cases: list[CompetitionBenchmarkCase] = []
    for record, location in _jsonl(path):
        raw_solutions: object = record.get("solutions")
        if not isinstance(raw_solutions, list):
            raise BenchmarkValidationError(f"{location}: solutions must be an array")
        solutions: list[CompetitionSolutionLabel] = []
        identities: set[str] = set()
        for index, item in enumerate(cast(list[object], raw_solutions)):
            item_location = f"{location}.solutions[{index}]"
            if not isinstance(item, dict):
                raise BenchmarkValidationError(f"{item_location}: solution must be an object")
            item = cast(dict[str, Any], item)
            name = _string(item, "name", item_location)
            try:
                solution_type = SolutionType(item.get("solution_type"))
            except (TypeError, ValueError) as exc:
                raise BenchmarkValidationError(
                    f"{item_location}: invalid solution_type"
                ) from exc
            raw_url = item.get("url")
            if raw_url is not None and not isinstance(raw_url, str):
                raise BenchmarkValidationError(f"{item_location}: url must be a string or null")
            url = normalize_url(raw_url) if raw_url else None
            identity = normalize_identifier(name)
            if identity in identities:
                raise BenchmarkValidationError(
                    f"{item_location}: duplicate solution name {name!r}"
                )
            identities.add(identity)
            solutions.append(CompetitionSolutionLabel(name, solution_type, url))
        evidence_urls = _evidence_urls(record, location) if require_evidence else ()
        cases.append(
            CompetitionBenchmarkCase(
                case_id=_string(record, "id", location),
                evidence_urls=evidence_urls,
                solutions=tuple(solutions),
                provenance=(
                    parse_benchmark_provenance(record, location)
                    if require_provenance
                    else None
                ),
            )
        )
    _unique_case_ids(cases)
    return tuple(cases)


def load_dach_benchmark(
    path: str | Path,
    *,
    require_evidence: bool = True,
    require_provenance: bool | None = None,
) -> tuple[DachBenchmarkCase, ...]:
    if require_provenance is None:
        require_provenance = require_evidence
    cases: list[DachBenchmarkCase] = []
    for record, location in _jsonl(path):
        try:
            actor = ActorEquivalence(record.get("actor_equivalence"))
            workflow = WorkflowEquivalence(record.get("workflow_equivalence"))
            transfer = DachTransferType(record.get("transfer_type"))
            local = LocalEvidenceState(record.get("local_evidence_state"))
        except (TypeError, ValueError) as exc:
            raise BenchmarkValidationError(
                f"{location}: invalid DACH classification value"
            ) from exc
        cases.append(
            DachBenchmarkCase(
                case_id=_string(record, "id", location),
                evidence_urls=(
                    _evidence_urls(record, location) if require_evidence else ()
                ),
                actor_equivalence=actor,
                workflow_equivalence=workflow,
                transfer_type=transfer,
                local_evidence_state=local,
                provenance=(
                    parse_benchmark_provenance(record, location)
                    if require_provenance
                    else None
                ),
            )
        )
    _unique_case_ids(cases)
    return tuple(cases)


def _matched_cases(
    gold: Iterable[ResearchBenchmarkCase],
    predictions: Iterable[ResearchBenchmarkCase],
) -> tuple[
    dict[str, ResearchBenchmarkCase],
    dict[str, ResearchBenchmarkCase],
]:
    gold_by_id = {case.case_id: case for case in gold}
    prediction_by_id = {case.case_id: case for case in predictions}
    missing = sorted(set(gold_by_id) - set(prediction_by_id))
    extra = sorted(set(prediction_by_id) - set(gold_by_id))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing predictions: {', '.join(missing)}")
        if extra:
            details.append(f"unknown predictions: {', '.join(extra)}")
        raise BenchmarkValidationError("; ".join(details))
    return gold_by_id, prediction_by_id


def _solution_key(solution: CompetitionSolutionLabel) -> tuple[str, str]:
    return (
        normalize_identifier(solution.name),
        solution.solution_type.value,
    )


def evaluate_competition(
    gold: Iterable[CompetitionBenchmarkCase],
    predictions: Iterable[CompetitionBenchmarkCase],
) -> dict[str, int | float]:
    gold_by_id, prediction_by_id = _matched_cases(gold, predictions)
    true_positive = false_positive = false_negative = exact_cases = 0
    url_correct = url_compared = 0
    for case_id, untyped_gold_case in gold_by_id.items():
        untyped_prediction = prediction_by_id[case_id]
        assert isinstance(untyped_gold_case, CompetitionBenchmarkCase)
        assert isinstance(untyped_prediction, CompetitionBenchmarkCase)
        gold_solutions = {
            _solution_key(item): item for item in untyped_gold_case.solutions
        }
        predicted_solutions = {
            _solution_key(item): item for item in untyped_prediction.solutions
        }
        gold_keys = set(gold_solutions)
        predicted_keys = set(predicted_solutions)
        true_positive += len(gold_keys & predicted_keys)
        false_positive += len(predicted_keys - gold_keys)
        false_negative += len(gold_keys - predicted_keys)
        exact_cases += gold_keys == predicted_keys
        for key in gold_keys & predicted_keys:
            url_compared += 1
            url_correct += gold_solutions[key].url == predicted_solutions[key].url
    return {
        "cases": len(gold_by_id),
        "true_positive_solutions": true_positive,
        "false_positive_solutions": false_positive,
        "false_negative_solutions": false_negative,
        "competition_precision": _ratio(true_positive, true_positive + false_positive),
        "competition_recall": _ratio(true_positive, true_positive + false_negative),
        "competition_f1": _ratio(
            2 * true_positive,
            2 * true_positive + false_positive + false_negative,
        ),
        "solution_url_exact_accuracy": _ratio(url_correct, url_compared),
        "exact_case_accuracy": _ratio(exact_cases, len(gold_by_id)),
    }


def evaluate_dach_transfer(
    gold: Iterable[DachBenchmarkCase], predictions: Iterable[DachBenchmarkCase]
) -> dict[str, int | float]:
    gold_by_id, prediction_by_id = _matched_cases(gold, predictions)
    actor = workflow = transfer = local = exact = 0
    for case_id, untyped_gold_case in gold_by_id.items():
        untyped_prediction = prediction_by_id[case_id]
        assert isinstance(untyped_gold_case, DachBenchmarkCase)
        assert isinstance(untyped_prediction, DachBenchmarkCase)
        actor_match = (
            untyped_gold_case.actor_equivalence
            is untyped_prediction.actor_equivalence
        )
        workflow_match = (
            untyped_gold_case.workflow_equivalence
            is untyped_prediction.workflow_equivalence
        )
        transfer_match = untyped_gold_case.transfer_type is untyped_prediction.transfer_type
        local_match = (
            untyped_gold_case.local_evidence_state
            is untyped_prediction.local_evidence_state
        )
        actor += actor_match
        workflow += workflow_match
        transfer += transfer_match
        local += local_match
        exact += actor_match and workflow_match and transfer_match and local_match
    total = len(gold_by_id)
    return {
        "cases": total,
        "actor_equivalence_accuracy": _ratio(actor, total),
        "workflow_equivalence_accuracy": _ratio(workflow, total),
        "transfer_type_accuracy": _ratio(transfer, total),
        "local_evidence_state_accuracy": _ratio(local, total),
        "exact_case_accuracy": _ratio(exact, total),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0

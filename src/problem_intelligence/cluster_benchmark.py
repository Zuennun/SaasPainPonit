"""Labelled pairwise evaluation for clustering implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, cast

from .benchmark import (
    BenchmarkProvenance,
    BenchmarkValidationError,
    parse_benchmark_provenance,
)
from .clustering import observation_fingerprint
from .domain import ObservationRecord, ProblemType

_IDENTITY_FIELDS = frozenset({"actor", "job_to_be_done", "context", "root_cause"})


@dataclass(frozen=True, slots=True)
class ClusteringBenchmarkCase:
    case_id: str
    observation: ObservationRecord
    expected_cluster: str
    provenance: BenchmarkProvenance


def load_clustering_benchmark(path: str | Path) -> tuple[ClusteringBenchmarkCase, ...]:
    fixture_path = Path(path)
    cases: list[ClusteringBenchmarkCase] = []
    seen_ids: set[str] = set()
    with fixture_path.open(encoding="utf-8") as fixture:
        for line_number, line in enumerate(fixture, start=1):
            if not line.strip():
                continue
            location = f"{fixture_path}:{line_number}"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkValidationError(f"{location}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise BenchmarkValidationError(f"{location}: case must be a JSON object")
            record = cast(dict[str, Any], record)
            case_id = _required_string(record, "id", location)
            if case_id in seen_ids:
                raise BenchmarkValidationError(f"{location}: duplicate id {case_id!r}")
            seen_ids.add(case_id)
            problem = _required_string(record, "problem", location)
            expected_cluster = _required_string(record, "expected_cluster", location)
            try:
                problem_type = ProblemType(record.get("problem_type"))
            except (TypeError, ValueError) as exc:
                raise BenchmarkValidationError(f"{location}: invalid problem_type") from exc
            raw_fields: object = record.get("fields", {})
            if not isinstance(raw_fields, dict):
                raise BenchmarkValidationError(f"{location}: fields must be an object")
            fields = cast(dict[str, Any], raw_fields)
            unknown = set(fields) - _IDENTITY_FIELDS
            if unknown:
                raise BenchmarkValidationError(
                    f"{location}: unknown identity fields: {', '.join(sorted(unknown))}"
                )
            invalid_fields = [
                name
                for name, value in fields.items()
                if value is not None and not isinstance(value, str)
            ]
            if invalid_fields:
                raise BenchmarkValidationError(
                    f"{location}: identity fields must be strings or null: "
                    f"{', '.join(sorted(invalid_fields))}"
                )
            cases.append(
                ClusteringBenchmarkCase(
                    case_id=case_id,
                    observation=ObservationRecord(
                        id=line_number,
                        problem_type=problem_type,
                        problem_family=None,
                        problem=problem,
                        actor=fields.get("actor"),
                        job_to_be_done=fields.get("job_to_be_done"),
                        context=fields.get("context"),
                        root_cause=fields.get("root_cause"),
                        current_workaround=None,
                        tools_used=None,
                    ),
                    expected_cluster=expected_cluster,
                    provenance=parse_benchmark_provenance(record, location),
                )
            )
    if len(cases) < 2:
        raise BenchmarkValidationError(
            f"{fixture_path}: clustering benchmark requires at least two cases"
        )
    return tuple(cases)


def _required_string(record: dict[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: {key} must be a non-empty string")
    return value


def evaluate_exact_clustering(
    cases: tuple[ClusteringBenchmarkCase, ...],
) -> dict[str, int | float]:
    fingerprints = {
        case.case_id: observation_fingerprint(case.observation) for case in cases
    }
    tp = fp = fn = tn = 0
    for left, right in combinations(cases, 2):
        expected_same = left.expected_cluster == right.expected_cluster
        predicted_same = fingerprints[left.case_id] == fingerprints[right.case_id]
        if expected_same and predicted_same:
            tp += 1
        elif predicted_same:
            fp += 1
        elif expected_same:
            fn += 1
        else:
            tn += 1
    return {
        "cases": len(cases),
        "pairs": tp + fp + fn + tn,
        "true_positive_pairs": tp,
        "false_positive_pairs": fp,
        "false_negative_pairs": fn,
        "true_negative_pairs": tn,
        "pairwise_precision": _ratio(tp, tp + fp),
        "pairwise_recall": _ratio(tp, tp + fn),
        "pairwise_f1": _ratio(2 * tp, 2 * tp + fp + fn),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0

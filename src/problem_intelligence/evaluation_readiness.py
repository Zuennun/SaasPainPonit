"""Explicit coverage and quality gates that must pass before ingestion scales."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from itertools import combinations
from math import isfinite
from pathlib import Path
from typing import Any, cast

from .benchmark import (
    BenchmarkValidationError,
    benchmark_provenance_summary,
    load_benchmark,
)
from .cluster_benchmark import evaluate_exact_clustering, load_clustering_benchmark
from .evaluation import evaluate_predictions, load_predictions
from .research_benchmark import (
    evaluate_competition,
    evaluate_dach_transfer,
    load_competition_benchmark,
    load_dach_benchmark,
)

_KINDS = frozenset({"problem", "clustering", "competition", "dach_transfer"})


@dataclass(frozen=True, slots=True)
class EvaluationGate:
    gate_type: str
    name: str
    required: int | float
    actual: int | float | None
    passed: bool


@dataclass(frozen=True, slots=True)
class EvaluationSuiteReadiness:
    name: str
    kind: str
    fixture: str
    predictions: str | None
    coverage: dict[str, int]
    metrics: dict[str, int | float] | None
    gates: tuple[EvaluationGate, ...]

    @property
    def ready(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "fixture": self.fixture,
            "predictions": self.predictions,
            "predictions_configured": self.predictions is not None,
            "coverage": self.coverage,
            "metrics": self.metrics,
            "ready": self.ready,
            "gates": [asdict(gate) for gate in self.gates],
        }


@dataclass(frozen=True, slots=True)
class EvaluationReadiness:
    policy_version: str
    manifest: str
    suites: tuple[EvaluationSuiteReadiness, ...]

    @property
    def ready_for_scale(self) -> bool:
        return all(suite.ready for suite in self.suites)

    def to_dict(self) -> dict[str, Any]:
        failed = [
            f"{suite.name}:{gate.gate_type}:{gate.name}"
            for suite in self.suites
            for gate in suite.gates
            if not gate.passed
        ]
        return {
            "policy_version": self.policy_version,
            "manifest": self.manifest,
            "ready_for_scale": self.ready_for_scale,
            "suite_count": len(self.suites),
            "failed_gate_count": len(failed),
            "failed_gates": failed,
            "suites": [suite.to_dict() for suite in self.suites],
        }


def evaluate_readiness(manifest_path: str | Path) -> EvaluationReadiness:
    """Load a versioned policy and evaluate every configured benchmark suite."""

    path = Path(manifest_path)
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkValidationError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise BenchmarkValidationError(f"{path}: manifest must be a JSON object")
    manifest = cast(dict[str, object], raw)
    unknown = set(manifest) - {"version", "suites"}
    if unknown:
        raise BenchmarkValidationError(
            f"{path}: unknown manifest fields: {', '.join(sorted(unknown))}"
        )
    version = _string(manifest.get("version"), f"{path}.version")
    raw_suites = manifest.get("suites")
    if not isinstance(raw_suites, list) or not raw_suites:
        raise BenchmarkValidationError(f"{path}.suites: must be a non-empty array")

    suites: list[EvaluationSuiteReadiness] = []
    names: set[str] = set()
    for index, raw_suite in enumerate(cast(list[object], raw_suites)):
        location = f"{path}.suites[{index}]"
        suite = _evaluate_suite(raw_suite, location, path.parent)
        if suite.name in names:
            raise BenchmarkValidationError(f"{location}: duplicate suite name {suite.name!r}")
        names.add(suite.name)
        suites.append(suite)
    return EvaluationReadiness(version, str(path), tuple(suites))


def _evaluate_suite(
    raw: object, location: str, manifest_directory: Path
) -> EvaluationSuiteReadiness:
    if not isinstance(raw, dict):
        raise BenchmarkValidationError(f"{location}: suite must be a JSON object")
    record = cast(dict[str, object], raw)
    expected = {
        "name",
        "kind",
        "fixture",
        "predictions",
        "minimum_coverage",
        "minimum_metrics",
    }
    unknown = set(record) - expected
    missing = expected - set(record)
    if unknown or missing:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise BenchmarkValidationError(f"{location}: {'; '.join(details)}")

    name = _string(record["name"], f"{location}.name")
    kind = _string(record["kind"], f"{location}.kind")
    if kind not in _KINDS:
        raise BenchmarkValidationError(f"{location}.kind: unsupported suite kind {kind!r}")
    fixture = _resolve_path(record["fixture"], f"{location}.fixture", manifest_directory)
    prediction_value = record["predictions"]
    predictions = (
        None
        if prediction_value is None
        else _resolve_path(
            prediction_value, f"{location}.predictions", manifest_directory
        )
    )
    if kind == "clustering" and predictions is not None:
        raise BenchmarkValidationError(
            f"{location}.predictions: clustering evaluates the configured deterministic "
            "baseline and does not accept a prediction file"
        )
    minimum_coverage = _minimums(
        record["minimum_coverage"], f"{location}.minimum_coverage", integers=True
    )
    minimum_metrics = _minimums(
        record["minimum_metrics"], f"{location}.minimum_metrics", integers=False
    )
    if not minimum_coverage:
        raise BenchmarkValidationError(f"{location}: minimum_coverage must not be empty")
    if not minimum_metrics:
        raise BenchmarkValidationError(f"{location}: minimum_metrics must not be empty")

    coverage, metrics = _suite_evidence(kind, fixture, predictions)
    required_provenance_gates = {
        "manually_labeled_cases",
        "permissioned_human_reviewed_cases",
    }
    missing_provenance_gates = required_provenance_gates - set(minimum_coverage)
    if missing_provenance_gates:
        raise BenchmarkValidationError(
            f"{location}: minimum_coverage must include provenance gates: "
            f"{', '.join(sorted(missing_provenance_gates))}"
        )
    unknown_coverage = set(minimum_coverage) - set(coverage)
    if unknown_coverage:
        raise BenchmarkValidationError(
            f"{location}: unsupported coverage gates for {kind}: "
            f"{', '.join(sorted(unknown_coverage))}"
        )
    metric_names = _supported_metric_names(kind)
    unknown_metrics = set(minimum_metrics) - metric_names
    if unknown_metrics:
        raise BenchmarkValidationError(
            f"{location}: unsupported metric gates for {kind}: "
            f"{', '.join(sorted(unknown_metrics))}"
        )
    gates = tuple(
        EvaluationGate("coverage", key, required, coverage[key], coverage[key] >= required)
        for key, required in minimum_coverage.items()
    ) + tuple(
        EvaluationGate(
            "metric",
            key,
            required,
            metrics.get(key) if metrics is not None else None,
            metrics is not None and float(metrics[key]) >= required,
        )
        for key, required in minimum_metrics.items()
    )
    return EvaluationSuiteReadiness(
        name=name,
        kind=kind,
        fixture=str(fixture),
        predictions=str(predictions) if predictions is not None else None,
        coverage=coverage,
        metrics=metrics,
        gates=gates,
    )


def _suite_evidence(
    kind: str, fixture: Path, predictions: Path | None
) -> tuple[dict[str, int], dict[str, int | float] | None]:
    if kind == "problem":
        cases = load_benchmark(fixture)
        positive = [case for case in cases if case.is_problem]
        positive_provenance = benchmark_provenance_summary(
            case.provenance for case in positive
        )
        coverage = {
            "cases": len(cases),
            "positive_cases": len(positive),
            "negative_cases": len(cases) - len(positive),
            "evidence_spans": sum(len(case.evidence) for case in cases),
            "positive_cases_with_structured_fields": sum(bool(case.fields) for case in positive),
            "distinct_problem_types": len({case.problem_type for case in positive}),
            "distinct_problem_families": len({case.problem_family for case in positive}),
            "distinct_evidence_scopes": len({case.evidence_scope for case in positive}),
            **benchmark_provenance_summary(case.provenance for case in cases),
            "manually_labeled_positive_cases": positive_provenance[
                "manually_labeled_cases"
            ],
            "permissioned_human_reviewed_positive_cases": positive_provenance[
                "permissioned_human_reviewed_cases"
            ],
        }
        metrics = (
            evaluate_predictions(cases, load_predictions(predictions, cases))
            if predictions is not None
            else None
        )
        return coverage, metrics
    if kind == "clustering":
        cases = load_clustering_benchmark(fixture)
        positive_pairs = sum(
            left.expected_cluster == right.expected_cluster
            for left, right in combinations(cases, 2)
        )
        total_pairs = len(cases) * (len(cases) - 1) // 2
        return {
            "cases": len(cases),
            "expected_clusters": len({case.expected_cluster for case in cases}),
            "positive_pairs": positive_pairs,
            "negative_pairs": total_pairs - positive_pairs,
            **benchmark_provenance_summary(case.provenance for case in cases),
        }, evaluate_exact_clustering(cases)
    if kind == "competition":
        cases = load_competition_benchmark(fixture)
        solutions = [solution for case in cases for solution in case.solutions]
        coverage = {
            "cases": len(cases),
            "cases_with_solutions": sum(bool(case.solutions) for case in cases),
            "solutions": len(solutions),
            "evidence_urls": sum(len(case.evidence_urls) for case in cases),
            "distinct_solution_types": len({item.solution_type for item in solutions}),
            **benchmark_provenance_summary(
                case.provenance for case in cases if case.provenance is not None
            ),
        }
        metrics = (
            evaluate_competition(
                cases, load_competition_benchmark(predictions, require_evidence=False)
            )
            if predictions is not None
            else None
        )
        return coverage, metrics
    assert kind == "dach_transfer"
    cases = load_dach_benchmark(fixture)
    coverage = {
        "cases": len(cases),
        "evidence_urls": sum(len(case.evidence_urls) for case in cases),
        "distinct_actor_equivalence": len({case.actor_equivalence for case in cases}),
        "distinct_workflow_equivalence": len({case.workflow_equivalence for case in cases}),
        "distinct_transfer_types": len({case.transfer_type for case in cases}),
        "distinct_local_evidence_states": len({case.local_evidence_state for case in cases}),
        **benchmark_provenance_summary(
            case.provenance for case in cases if case.provenance is not None
        ),
    }
    metrics = (
        evaluate_dach_transfer(
            cases, load_dach_benchmark(predictions, require_evidence=False)
        )
        if predictions is not None
        else None
    )
    return coverage, metrics


def _supported_metric_names(kind: str) -> set[str]:
    if kind == "problem":
        return {
            "detection_accuracy",
            "detection_precision",
            "detection_recall",
            "detection_f1",
            "problem_type_accuracy",
            "problem_family_accuracy",
            "evidence_scope_accuracy",
            "problem_text_exact_accuracy",
            "field_exact_accuracy",
            "evidence_precision",
            "evidence_recall",
            "evidence_f1",
        }
    if kind == "clustering":
        return {"pairwise_precision", "pairwise_recall", "pairwise_f1"}
    if kind == "competition":
        return {
            "competition_precision",
            "competition_recall",
            "competition_f1",
            "solution_url_exact_accuracy",
            "exact_case_accuracy",
        }
    return {
        "actor_equivalence_accuracy",
        "workflow_equivalence_accuracy",
        "transfer_type_accuracy",
        "local_evidence_state_accuracy",
        "exact_case_accuracy",
    }


def _minimums(value: object, location: str, *, integers: bool) -> dict[str, int | float]:
    if not isinstance(value, dict):
        raise BenchmarkValidationError(f"{location}: must be a JSON object")
    result: dict[str, int | float] = {}
    for raw_key, raw_value in cast(dict[object, object], value).items():
        if not isinstance(raw_key, str) or not raw_key:
            raise BenchmarkValidationError(f"{location}: gate names must be non-empty strings")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise BenchmarkValidationError(f"{location}.{raw_key}: must be numeric")
        if integers:
            if not isinstance(raw_value, int) or raw_value < 0:
                raise BenchmarkValidationError(
                    f"{location}.{raw_key}: coverage minimum must be a non-negative integer"
                )
        elif not isfinite(raw_value) or not 0 <= raw_value <= 1:
            raise BenchmarkValidationError(
                f"{location}.{raw_key}: metric threshold must be between zero and one"
            )
        result[raw_key] = raw_value
    return result


def _resolve_path(value: object, location: str, directory: Path) -> Path:
    rendered = _string(value, location)
    path = Path(rendered)
    return path if path.is_absolute() else directory / path


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: must be a non-empty string")
    return value.strip()

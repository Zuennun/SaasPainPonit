"""Deterministic scoring of predictions against labelled benchmark cases."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .benchmark import BenchmarkCase, BenchmarkEvidence, BenchmarkValidationError
from .domain import (
    EvidenceRange,
    EvidenceScope,
    ProblemFamily,
    ProblemType,
    validate_observation_fields,
)


@dataclass(frozen=True, slots=True)
class BenchmarkPrediction:
    case_id: str
    is_problem: bool
    problem_type: ProblemType | None
    problem_family: ProblemFamily | None
    evidence_scope: EvidenceScope | None
    problem: str | None
    fields: dict[str, Any]
    evidence: tuple[BenchmarkEvidence, ...]


def load_predictions(
    path: str | Path, cases: Iterable[BenchmarkCase]
) -> tuple[BenchmarkPrediction, ...]:
    """Load predictions and validate evidence coordinates against benchmark text."""

    prediction_path = Path(path)
    case_by_id = {case.case_id: case for case in cases}
    predictions: list[BenchmarkPrediction] = []
    seen_ids: set[str] = set()
    with prediction_path.open(encoding="utf-8") as prediction_file:
        for line_number, line in enumerate(prediction_file, start=1):
            if not line.strip():
                continue
            location = f"{prediction_path}:{line_number}"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkValidationError(f"{location}: invalid JSON: {exc.msg}") from exc
            prediction = _parse_prediction(record, case_by_id, location)
            if prediction.case_id in seen_ids:
                raise BenchmarkValidationError(
                    f"{location}: duplicate id {prediction.case_id!r}"
                )
            seen_ids.add(prediction.case_id)
            predictions.append(prediction)
    return tuple(predictions)


def _parse_prediction(
    record: object, case_by_id: dict[str, BenchmarkCase], location: str
) -> BenchmarkPrediction:
    if not isinstance(record, dict):
        raise BenchmarkValidationError(f"{location}: prediction must be a JSON object")
    record = cast(dict[str, Any], record)
    case_id = record.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise BenchmarkValidationError(f"{location}: id must be a non-empty string")
    case = case_by_id.get(case_id)
    if case is None:
        raise BenchmarkValidationError(f"{location}: unknown benchmark id {case_id!r}")
    is_problem = record.get("is_problem")
    if not isinstance(is_problem, bool):
        raise BenchmarkValidationError(f"{location}: is_problem must be a boolean")

    problem_type = _prediction_enum(
        record.get("problem_type"), ProblemType, "problem_type", location
    )
    problem_family = _prediction_enum(
        record.get("problem_family"), ProblemFamily, "problem_family", location
    )
    evidence_scope = _prediction_enum(
        record.get("evidence_scope"), EvidenceScope, "evidence_scope", location
    )
    problem = record.get("problem")
    if problem is not None and not isinstance(problem, str):
        raise BenchmarkValidationError(f"{location}: problem must be a string or null")
    raw_fields: object = record.get("fields", {})
    if not isinstance(raw_fields, dict) or any(
        not isinstance(key, str) for key in cast(dict[object, object], raw_fields)
    ):
        raise BenchmarkValidationError(f"{location}: fields must be an object")
    fields = cast(dict[str, Any], raw_fields)
    try:
        validate_observation_fields(fields)
    except ValueError as exc:
        raise BenchmarkValidationError(f"{location}: {exc}") from exc
    evidence = _prediction_evidence(record.get("evidence", []), case.text, location)
    if not is_problem and any(
        (
            problem_type is not None,
            problem_family is not None,
            evidence_scope is not None,
            problem is not None,
            fields,
            evidence,
        )
    ):
        raise BenchmarkValidationError(
            f"{location}: negative prediction must not contain extraction output"
        )
    return BenchmarkPrediction(
        case_id=case_id,
        is_problem=is_problem,
        problem_type=problem_type if isinstance(problem_type, ProblemType) else None,
        problem_family=(
            problem_family if isinstance(problem_family, ProblemFamily) else None
        ),
        evidence_scope=evidence_scope if isinstance(evidence_scope, EvidenceScope) else None,
        problem=problem,
        fields=dict(fields),
        evidence=evidence,
    )


def _prediction_enum(
    value: object,
    enum_type: type[ProblemType] | type[ProblemFamily] | type[EvidenceScope],
    name: str,
    location: str,
) -> ProblemType | ProblemFamily | EvidenceScope | None:
    if value is None:
        return None
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(f"{location}: invalid {name}: {value!r}") from exc


def _prediction_evidence(
    value: object, text: str, location: str
) -> tuple[BenchmarkEvidence, ...]:
    if not isinstance(value, list):
        raise BenchmarkValidationError(f"{location}: evidence must be an array")
    evidence: list[BenchmarkEvidence] = []
    for index, raw_span in enumerate(cast(list[object], value)):
        span_location = f"{location}.evidence[{index}]"
        if not isinstance(raw_span, dict):
            raise BenchmarkValidationError(f"{span_location}: span must be an object")
        raw_span = cast(dict[str, Any], raw_span)
        start, end, excerpt = raw_span.get("start"), raw_span.get("end"), raw_span.get("excerpt")
        if not isinstance(start, int) or isinstance(start, bool):
            raise BenchmarkValidationError(f"{span_location}: start must be an integer")
        if not isinstance(end, int) or isinstance(end, bool):
            raise BenchmarkValidationError(f"{span_location}: end must be an integer")
        if not isinstance(excerpt, str) or not excerpt:
            raise BenchmarkValidationError(f"{span_location}: excerpt must be a non-empty string")
        evidence_range = EvidenceRange(start, end)
        try:
            actual = evidence_range.excerpt_from(text)
        except ValueError as exc:
            raise BenchmarkValidationError(f"{span_location}: {exc}") from exc
        if actual != excerpt:
            raise BenchmarkValidationError(
                f"{span_location}: excerpt does not match benchmark text"
            )
        evidence.append(BenchmarkEvidence(evidence_range, excerpt))
    return tuple(evidence)


def evaluate_predictions(
    cases: Iterable[BenchmarkCase], predictions: Iterable[BenchmarkPrediction]
) -> dict[str, int | float]:
    """Return detection and strict extraction metrics without fuzzy matching."""

    case_by_id = {case.case_id: case for case in cases}
    prediction_by_id = {prediction.case_id: prediction for prediction in predictions}
    missing = sorted(set(case_by_id) - set(prediction_by_id))
    extra = sorted(set(prediction_by_id) - set(case_by_id))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing predictions: {', '.join(missing)}")
        if extra:
            details.append(f"unknown predictions: {', '.join(extra)}")
        raise BenchmarkValidationError("; ".join(details))

    tp = fp = fn = tn = 0
    type_correct = family_correct = scope_correct = problem_correct = 0
    positive_cases = sum(case.is_problem for case in case_by_id.values())
    evidence_tp = evidence_fp = evidence_fn = 0
    field_correct = field_total = 0
    for case_id, case in case_by_id.items():
        prediction = prediction_by_id[case_id]
        if case.is_problem and prediction.is_problem:
            tp += 1
        elif case.is_problem:
            fn += 1
        elif prediction.is_problem:
            fp += 1
        else:
            tn += 1

        if case.is_problem:
            type_correct += prediction.problem_type == case.problem_type
            family_correct += prediction.problem_family == case.problem_family
            scope_correct += prediction.evidence_scope == case.evidence_scope
            problem_correct += prediction.problem == case.problem

        gold_spans = {(item.range.start, item.range.end) for item in case.evidence}
        predicted_spans = {(item.range.start, item.range.end) for item in prediction.evidence}
        evidence_tp += len(gold_spans & predicted_spans)
        evidence_fp += len(predicted_spans - gold_spans)
        evidence_fn += len(gold_spans - predicted_spans)

        field_names = set(case.fields) | set(prediction.fields)
        field_total += len(field_names)
        field_correct += sum(
            case.fields.get(name) == prediction.fields.get(name) for name in field_names
        )

    total = len(case_by_id)
    return {
        "cases": total,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "detection_accuracy": _ratio(tp + tn, total),
        "detection_precision": _ratio(tp, tp + fp),
        "detection_recall": _ratio(tp, tp + fn),
        "detection_f1": _f1(tp, fp, fn),
        "problem_type_accuracy": _ratio(type_correct, positive_cases),
        "problem_family_accuracy": _ratio(family_correct, positive_cases),
        "evidence_scope_accuracy": _ratio(scope_correct, positive_cases),
        "problem_text_exact_accuracy": _ratio(problem_correct, positive_cases),
        "field_exact_accuracy": _ratio(field_correct, field_total),
        "evidence_precision": _ratio(evidence_tp, evidence_tp + evidence_fp),
        "evidence_recall": _ratio(evidence_tp, evidence_tp + evidence_fn),
        "evidence_f1": _f1(evidence_tp, evidence_fp, evidence_fn),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    return _ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative)

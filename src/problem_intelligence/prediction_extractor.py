"""Strict offline adapter from provider prediction JSONL to extraction drafts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from .benchmark import BenchmarkValidationError
from .domain import (
    EvidenceRange,
    EvidenceScope,
    ImpactSignalDraft,
    ImpactType,
    PaymentEvidenceType,
    PaymentSignalDraft,
    ProblemFamily,
    ProblemType,
    SourceItemRecord,
    WorkaroundSignalDraft,
    WorkaroundType,
    validate_observation_fields,
)
from .extraction import ObservationDraft


class JsonlPredictionExtractor:
    """Replay provider-neutral structured predictions against stored source text."""

    def __init__(self, path: str | Path, *, version: str) -> None:
        if not version.strip():
            raise ValueError("extractor version must not be empty")
        self.path = Path(path)
        self.version = version
        self._predictions = self._load()

    def extract(self, item: SourceItemRecord) -> tuple[ObservationDraft, ...]:
        prediction = self._predictions.get(item.id)
        if prediction is None:
            raise BenchmarkValidationError(
                f"{self.path}: no prediction for source_item_id {item.id}"
            )
        if prediction.external_id != item.external_id:
            raise BenchmarkValidationError(
                f"{self.path}: external_id mismatch for source_item_id {item.id}"
            )
        if not prediction.is_problem:
            return ()
        evidence_ranges: list[EvidenceRange] = []
        for evidence in prediction.evidence:
            try:
                actual = evidence.evidence_range.excerpt_from(item.raw_text)
            except ValueError as exc:
                raise BenchmarkValidationError(
                    f"{self.path}: evidence for {item.external_id!r} is invalid: {exc}"
                ) from exc
            if actual != evidence.excerpt:
                raise BenchmarkValidationError(
                    f"{self.path}: evidence for {item.external_id!r} does not match source text"
                )
            evidence_ranges.append(evidence.evidence_range)
        assert prediction.problem_type is not None
        assert prediction.problem_family is not None
        assert prediction.evidence_scope is not None
        assert prediction.problem is not None
        return (
            ObservationDraft(
                problem_type=prediction.problem_type,
                problem_family=prediction.problem_family,
                evidence_scope=prediction.evidence_scope,
                problem=prediction.problem,
                evidence_ranges=tuple(evidence_ranges),
                fields=prediction.fields,
                workarounds=prediction.workarounds,
                impact_signals=prediction.impact_signals,
                payment_signals=prediction.payment_signals,
            ),
        )

    def validate_batch(self, items: Sequence[SourceItemRecord]) -> None:
        selected_ids = {item.id for item in items}
        predicted_ids = set(self._predictions)
        missing = sorted(selected_ids - predicted_ids)
        extra = sorted(predicted_ids - selected_ids)
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"missing source_item_ids: {', '.join(map(str, missing))}")
            if extra:
                details.append(f"unexpected source_item_ids: {', '.join(map(str, extra))}")
            raise BenchmarkValidationError(f"{self.path}: {'; '.join(details)}")

    def _load(self) -> dict[int, _Prediction]:
        predictions: dict[int, _Prediction] = {}
        with self.path.open(encoding="utf-8") as prediction_file:
            for line_number, line in enumerate(prediction_file, start=1):
                if not line.strip():
                    continue
                location = f"{self.path}:{line_number}"
                try:
                    decoded: object = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BenchmarkValidationError(
                        f"{location}: invalid JSON: {exc.msg}"
                    ) from exc
                prediction = _parse_prediction(decoded, location)
                if prediction.source_item_id in predictions:
                    raise BenchmarkValidationError(
                        f"{location}: duplicate source_item_id {prediction.source_item_id}"
                    )
                predictions[prediction.source_item_id] = prediction
        if not predictions:
            raise BenchmarkValidationError(f"{self.path}: prediction file must not be empty")
        return predictions


class _PredictionEvidence:
    def __init__(self, evidence_range: EvidenceRange, excerpt: str) -> None:
        self.evidence_range = evidence_range
        self.excerpt = excerpt


class _Prediction:
    def __init__(
        self,
        *,
        source_item_id: int,
        external_id: str,
        is_problem: bool,
        problem_type: ProblemType | None,
        problem_family: ProblemFamily | None,
        evidence_scope: EvidenceScope | None,
        problem: str | None,
        fields: dict[str, Any],
        evidence: tuple[_PredictionEvidence, ...],
        workarounds: tuple[WorkaroundSignalDraft, ...],
        impact_signals: tuple[ImpactSignalDraft, ...],
        payment_signals: tuple[PaymentSignalDraft, ...],
    ) -> None:
        self.source_item_id = source_item_id
        self.external_id = external_id
        self.is_problem = is_problem
        self.problem_type = problem_type
        self.problem_family = problem_family
        self.evidence_scope = evidence_scope
        self.problem = problem
        self.fields = fields
        self.evidence = evidence
        self.workarounds = workarounds
        self.impact_signals = impact_signals
        self.payment_signals = payment_signals


def _parse_prediction(decoded: object, location: str) -> _Prediction:
    if not isinstance(decoded, dict):
        raise BenchmarkValidationError(f"{location}: prediction must be a JSON object")
    record = cast(dict[str, Any], decoded)
    source_item_id = record.get("source_item_id")
    external_id = record.get("external_id")
    is_problem = record.get("is_problem")
    if (
        not isinstance(source_item_id, int)
        or isinstance(source_item_id, bool)
        or source_item_id < 1
    ):
        raise BenchmarkValidationError(
            f"{location}: source_item_id must be a positive integer"
        )
    if not isinstance(external_id, str) or not external_id.strip():
        raise BenchmarkValidationError(f"{location}: external_id must be a non-empty string")
    if not isinstance(is_problem, bool):
        raise BenchmarkValidationError(f"{location}: is_problem must be a boolean")
    problem_type = _enum_value(record.get("problem_type"), ProblemType, "problem_type", location)
    problem_family = _enum_value(
        record.get("problem_family"), ProblemFamily, "problem_family", location
    )
    evidence_scope = _enum_value(
        record.get("evidence_scope"), EvidenceScope, "evidence_scope", location
    )
    problem = record.get("problem")
    if problem is not None and (not isinstance(problem, str) or not problem.strip()):
        raise BenchmarkValidationError(f"{location}: problem must be null or a non-empty string")
    fields = _fields(record.get("fields", {}), location)
    evidence = _evidence(record.get("evidence", []), location)
    workarounds = _workarounds(record.get("workarounds", []), len(evidence), location)
    impact_signals = _impact_signals(
        record.get("impact_signals", []), len(evidence), location
    )
    payment_signals = _payment_signals(
        record.get("payment_signals", []), len(evidence), location
    )
    if is_problem:
        if (
            problem_type is None
            or problem_family is None
            or evidence_scope is None
            or problem is None
            or not evidence
        ):
            raise BenchmarkValidationError(
                f"{location}: positive prediction requires type, family, scope, problem, "
                "and evidence"
            )
    elif any(
        (
            problem_type is not None,
            problem_family is not None,
            evidence_scope is not None,
            problem is not None,
            fields,
            evidence,
            workarounds,
            impact_signals,
            payment_signals,
        )
    ):
        raise BenchmarkValidationError(
            f"{location}: negative prediction must not contain extraction output"
        )
    return _Prediction(
        source_item_id=source_item_id,
        external_id=external_id,
        is_problem=is_problem,
        problem_type=problem_type if isinstance(problem_type, ProblemType) else None,
        problem_family=(
            problem_family if isinstance(problem_family, ProblemFamily) else None
        ),
        evidence_scope=evidence_scope if isinstance(evidence_scope, EvidenceScope) else None,
        problem=problem,
        fields=fields,
        evidence=evidence,
        workarounds=workarounds,
        impact_signals=impact_signals,
        payment_signals=payment_signals,
    )


def _signal_rows(value: object, name: str, location: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise BenchmarkValidationError(f"{location}: {name} must be an array")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(cast(list[object], value)):
        if not isinstance(raw, dict) or any(
            not isinstance(key, str) for key in cast(dict[object, object], raw)
        ):
            raise BenchmarkValidationError(
                f"{location}.{name}[{index}]: signal must be an object"
            )
        rows.append(cast(dict[str, Any], raw))
    return rows


def _evidence_index(
    row: dict[str, Any], evidence_count: int, location: str
) -> int:
    value = row.get("evidence_index")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value >= evidence_count
    ):
        raise BenchmarkValidationError(
            f"{location}: evidence_index must reference an evidence span"
        )
    return value


def _optional_signal_text(row: dict[str, Any], key: str, location: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: {key} must be a non-empty string or null")
    return value


def _workarounds(
    value: object, evidence_count: int, location: str
) -> tuple[WorkaroundSignalDraft, ...]:
    result: list[WorkaroundSignalDraft] = []
    for index, row in enumerate(_signal_rows(value, "workarounds", location)):
        item_location = f"{location}.workarounds[{index}]"
        try:
            workaround_type = WorkaroundType(row.get("type"))
        except (TypeError, ValueError) as exc:
            raise BenchmarkValidationError(
                f"{item_location}: invalid workaround type"
            ) from exc
        description = _optional_signal_text(row, "description", item_location)
        if description is None:
            raise BenchmarkValidationError(
                f"{item_location}: description must be a non-empty string"
            )
        result.append(
            WorkaroundSignalDraft(
                workaround_type,
                description,
                _evidence_index(row, evidence_count, item_location),
            )
        )
    return tuple(result)


def _impact_signals(
    value: object, evidence_count: int, location: str
) -> tuple[ImpactSignalDraft, ...]:
    result: list[ImpactSignalDraft] = []
    for index, row in enumerate(_signal_rows(value, "impact_signals", location)):
        item_location = f"{location}.impact_signals[{index}]"
        try:
            impact_type = ImpactType(row.get("type"))
        except (TypeError, ValueError) as exc:
            raise BenchmarkValidationError(f"{item_location}: invalid impact type") from exc
        quantified = row.get("quantified")
        if not isinstance(quantified, bool):
            raise BenchmarkValidationError(f"{item_location}: quantified must be a boolean")
        value_text = _optional_signal_text(row, "value", item_location)
        unit = _optional_signal_text(row, "unit", item_location)
        if quantified and (value_text is None or unit is None):
            raise BenchmarkValidationError(
                f"{item_location}: quantified impact requires value and unit"
            )
        if not quantified and (value_text is not None or unit is not None):
            raise BenchmarkValidationError(
                f"{item_location}: qualitative impact must not contain value or unit"
            )
        result.append(
            ImpactSignalDraft(
                impact_type,
                quantified,
                value_text,
                unit,
                _optional_signal_text(row, "frequency", item_location),
                _evidence_index(row, evidence_count, item_location),
            )
        )
    return tuple(result)


def _payment_signals(
    value: object, evidence_count: int, location: str
) -> tuple[PaymentSignalDraft, ...]:
    result: list[PaymentSignalDraft] = []
    for index, row in enumerate(_signal_rows(value, "payment_signals", location)):
        item_location = f"{location}.payment_signals[{index}]"
        try:
            payment_type = PaymentEvidenceType(row.get("type"))
        except (TypeError, ValueError) as exc:
            raise BenchmarkValidationError(f"{item_location}: invalid payment type") from exc
        amount = _optional_signal_text(row, "amount", item_location)
        currency = _optional_signal_text(row, "currency", item_location)
        if (amount is None) != (currency is None):
            raise BenchmarkValidationError(
                f"{item_location}: amount and currency must be supplied together"
            )
        result.append(
            PaymentSignalDraft(
                payment_type,
                amount,
                currency,
                _optional_signal_text(row, "frequency", item_location),
                _evidence_index(row, evidence_count, item_location),
            )
        )
    return tuple(result)


def _enum_value(
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


def _fields(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in cast(dict[object, object], value)
    ):
        raise BenchmarkValidationError(f"{location}: fields must be an object with string keys")
    fields = cast(dict[str, Any], value)
    if "pipeline_run_id" in fields:
        raise BenchmarkValidationError(f"{location}: pipeline_run_id is assigned by the system")
    try:
        validate_observation_fields(fields)
    except ValueError as exc:
        raise BenchmarkValidationError(f"{location}: {exc}") from exc
    return dict(fields)


def _evidence(value: object, location: str) -> tuple[_PredictionEvidence, ...]:
    if not isinstance(value, list):
        raise BenchmarkValidationError(f"{location}: evidence must be an array")
    result: list[_PredictionEvidence] = []
    for index, raw_span in enumerate(cast(list[object], value)):
        span_location = f"{location}.evidence[{index}]"
        if not isinstance(raw_span, dict):
            raise BenchmarkValidationError(f"{span_location}: span must be an object")
        span = cast(dict[str, Any], raw_span)
        start, end, excerpt = span.get("start"), span.get("end"), span.get("excerpt")
        if not isinstance(start, int) or isinstance(start, bool):
            raise BenchmarkValidationError(f"{span_location}: start must be an integer")
        if not isinstance(end, int) or isinstance(end, bool):
            raise BenchmarkValidationError(f"{span_location}: end must be an integer")
        if not isinstance(excerpt, str) or not excerpt:
            raise BenchmarkValidationError(f"{span_location}: excerpt must be a non-empty string")
        result.append(_PredictionEvidence(EvidenceRange(start, end), excerpt))
    return tuple(result)

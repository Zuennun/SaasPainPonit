"""Loading and validation for manually labelled extraction benchmarks."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from .domain import (
    EvidenceRange,
    EvidenceScope,
    ProblemFamily,
    ProblemType,
    validate_observation_fields,
)
from .normalization import normalize_url


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark fixture is ambiguous or internally inconsistent."""


class BenchmarkOrigin(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    PUBLIC_SOURCE = "PUBLIC_SOURCE"
    FIRST_PARTY = "FIRST_PARTY"


class BenchmarkRightsStatus(StrEnum):
    APPROVED = "APPROVED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BenchmarkLabelMethod(StrEnum):
    HUMAN = "HUMAN"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    UNREVIEWED = "UNREVIEWED"


@dataclass(frozen=True, slots=True)
class BenchmarkProvenance:
    origin: BenchmarkOrigin
    rights_status: BenchmarkRightsStatus
    source_url: str | None
    label_method: BenchmarkLabelMethod
    reviewed_by: str | None
    reviewed_at: str | None

    @property
    def permissioned(self) -> bool:
        return (
            self.origin in {BenchmarkOrigin.PUBLIC_SOURCE, BenchmarkOrigin.FIRST_PARTY}
            and self.rights_status is BenchmarkRightsStatus.APPROVED
        )

    @property
    def human_reviewed(self) -> bool:
        return self.label_method in {
            BenchmarkLabelMethod.HUMAN,
            BenchmarkLabelMethod.HUMAN_REVIEWED,
        }

    @property
    def manually_labeled(self) -> bool:
        return self.label_method is BenchmarkLabelMethod.HUMAN


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    range: EvidenceRange
    excerpt: str


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    text: str
    is_problem: bool
    problem_type: ProblemType | None
    problem_family: ProblemFamily | None
    evidence_scope: EvidenceScope | None
    problem: str | None
    fields: dict[str, Any]
    evidence: tuple[BenchmarkEvidence, ...]
    provenance: BenchmarkProvenance


def parse_benchmark_provenance(
    record: dict[str, Any], location: str
) -> BenchmarkProvenance:
    raw: object = record.get("provenance")
    if not isinstance(raw, dict):
        raise BenchmarkValidationError(f"{location}.provenance: must be an object")
    value = cast(dict[str, object], raw)
    expected = {
        "origin",
        "rights_status",
        "source_url",
        "label_method",
        "reviewed_by",
        "reviewed_at",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise BenchmarkValidationError(
            f"{location}.provenance: {'; '.join(details)}"
        )
    try:
        origin = BenchmarkOrigin(value["origin"])
        rights = BenchmarkRightsStatus(value["rights_status"])
        label_method = BenchmarkLabelMethod(value["label_method"])
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(
            f"{location}.provenance: invalid origin, rights_status, or label_method"
        ) from exc

    raw_url = value["source_url"]
    if raw_url is not None and not isinstance(raw_url, str):
        raise BenchmarkValidationError(
            f"{location}.provenance.source_url: must be a string or null"
        )
    try:
        source_url = normalize_url(raw_url) if raw_url else None
    except ValueError as exc:
        raise BenchmarkValidationError(
            f"{location}.provenance.source_url: {exc}"
        ) from exc
    if origin is BenchmarkOrigin.PUBLIC_SOURCE and source_url is None:
        raise BenchmarkValidationError(
            f"{location}.provenance: PUBLIC_SOURCE requires source_url"
        )
    if origin is BenchmarkOrigin.SYNTHETIC:
        if source_url is not None or rights is not BenchmarkRightsStatus.NOT_APPLICABLE:
            raise BenchmarkValidationError(
                f"{location}.provenance: SYNTHETIC requires null source_url and "
                "NOT_APPLICABLE rights"
            )
    elif rights is BenchmarkRightsStatus.NOT_APPLICABLE:
        raise BenchmarkValidationError(
            f"{location}.provenance: sourced cases require a rights decision"
        )

    reviewed_by = _nullable_string(
        value["reviewed_by"], f"{location}.provenance.reviewed_by"
    )
    reviewed_at = _nullable_string(
        value["reviewed_at"], f"{location}.provenance.reviewed_at"
    )
    if label_method is BenchmarkLabelMethod.UNREVIEWED:
        if reviewed_by is not None or reviewed_at is not None:
            raise BenchmarkValidationError(
                f"{location}.provenance: UNREVIEWED labels cannot name a reviewer or date"
            )
    elif reviewed_by is None or reviewed_at is None:
        raise BenchmarkValidationError(
            f"{location}.provenance: reviewed labels require reviewed_by and reviewed_at"
        )
    if reviewed_at is not None:
        try:
            date.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise BenchmarkValidationError(
                f"{location}.provenance.reviewed_at: must be an ISO date"
            ) from exc
    return BenchmarkProvenance(
        origin=origin,
        rights_status=rights,
        source_url=source_url,
        label_method=label_method,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )


def _nullable_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: must be a non-empty string or null")
    return value.strip()


def _required_string(record: dict[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{location}: {key} must be a non-empty string")
    return value


def _optional_enum(
    record: dict[str, Any],
    key: str,
    enum_type: type[ProblemType] | type[ProblemFamily] | type[EvidenceScope],
    location: str,
) -> ProblemType | ProblemFamily | EvidenceScope | None:
    value = record.get(key)
    if value is None:
        return None
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(f"{location}: invalid {key}: {value!r}") from exc


def _parse_case(record: object, location: str) -> BenchmarkCase:
    if not isinstance(record, dict):
        raise BenchmarkValidationError(f"{location}: each line must contain a JSON object")
    record = cast(dict[str, Any], record)

    case_id = _required_string(record, "id", location)
    text = _required_string(record, "text", location)
    is_problem = record.get("is_problem")
    if not isinstance(is_problem, bool):
        raise BenchmarkValidationError(f"{location}: is_problem must be a boolean")

    problem_type = _optional_enum(record, "problem_type", ProblemType, location)
    problem_family = _optional_enum(record, "problem_family", ProblemFamily, location)
    evidence_scope = _optional_enum(record, "evidence_scope", EvidenceScope, location)
    problem_value = record.get("problem")
    if problem_value is not None and (
        not isinstance(problem_value, str) or not problem_value.strip()
    ):
        raise BenchmarkValidationError(f"{location}: problem must be null or a non-empty string")

    raw_fields: object = record.get("fields", {})
    if not isinstance(raw_fields, dict) or any(
        not isinstance(key, str) for key in cast(dict[object, object], raw_fields)
    ):
        raise BenchmarkValidationError(f"{location}: fields must be an object with string keys")
    fields = cast(dict[str, Any], raw_fields)
    try:
        validate_observation_fields(fields)
    except ValueError as exc:
        raise BenchmarkValidationError(f"{location}: {exc}") from exc

    raw_evidence: object = record.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise BenchmarkValidationError(f"{location}: evidence must be an array")
    evidence: list[BenchmarkEvidence] = []
    for index, raw_span in enumerate(cast(list[object], raw_evidence)):
        span_location = f"{location}.evidence[{index}]"
        if not isinstance(raw_span, dict):
            raise BenchmarkValidationError(f"{span_location}: span must be an object")
        raw_span = cast(dict[str, Any], raw_span)
        start = raw_span.get("start")
        end = raw_span.get("end")
        excerpt = raw_span.get("excerpt")
        if not isinstance(start, int) or isinstance(start, bool):
            raise BenchmarkValidationError(f"{span_location}: start must be an integer")
        if not isinstance(end, int) or isinstance(end, bool):
            raise BenchmarkValidationError(f"{span_location}: end must be an integer")
        if not isinstance(excerpt, str) or not excerpt:
            raise BenchmarkValidationError(f"{span_location}: excerpt must be a non-empty string")
        evidence_range = EvidenceRange(start, end)
        try:
            actual_excerpt = evidence_range.excerpt_from(text)
        except ValueError as exc:
            raise BenchmarkValidationError(f"{span_location}: {exc}") from exc
        if actual_excerpt != excerpt:
            raise BenchmarkValidationError(
                f"{span_location}: excerpt does not match text at [{start}:{end}]"
            )
        evidence.append(BenchmarkEvidence(evidence_range, excerpt))

    if is_problem:
        missing = [
            name
            for name, value in (
                ("problem_type", problem_type),
                ("problem_family", problem_family),
                ("evidence_scope", evidence_scope),
                ("problem", problem_value),
            )
            if value is None
        ]
        if missing:
            raise BenchmarkValidationError(
                f"{location}: positive case is missing {', '.join(missing)}"
            )
        if not evidence:
            raise BenchmarkValidationError(f"{location}: positive case requires evidence")
    elif any(
        (
            problem_type is not None,
            problem_family is not None,
            evidence_scope is not None,
            problem_value is not None,
            fields,
            evidence,
        )
    ):
        raise BenchmarkValidationError(
            f"{location}: negative case must not contain extraction labels"
        )

    return BenchmarkCase(
        case_id=case_id,
        text=text,
        is_problem=is_problem,
        problem_type=problem_type if isinstance(problem_type, ProblemType) else None,
        problem_family=(
            problem_family if isinstance(problem_family, ProblemFamily) else None
        ),
        evidence_scope=evidence_scope if isinstance(evidence_scope, EvidenceScope) else None,
        problem=problem_value,
        fields=dict(fields),
        evidence=tuple(evidence),
        provenance=parse_benchmark_provenance(record, location),
    )


def load_benchmark(path: str | Path) -> tuple[BenchmarkCase, ...]:
    """Load a JSONL fixture and reject labels that cannot be audited."""

    fixture_path = Path(path)
    cases: list[BenchmarkCase] = []
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
            case = _parse_case(record, location)
            if case.case_id in seen_ids:
                raise BenchmarkValidationError(f"{location}: duplicate id {case.case_id!r}")
            seen_ids.add(case.case_id)
            cases.append(case)
    if not cases:
        raise BenchmarkValidationError(f"{fixture_path}: benchmark must contain at least one case")
    return tuple(cases)


def benchmark_summary(cases: Iterable[BenchmarkCase]) -> dict[str, int]:
    materialized = tuple(cases)
    positives = sum(case.is_problem for case in materialized)
    return {
        "cases": len(materialized),
        "positive_cases": positives,
        "negative_cases": len(materialized) - positives,
        "evidence_spans": sum(len(case.evidence) for case in materialized),
        **benchmark_provenance_summary(case.provenance for case in materialized),
    }


def benchmark_provenance_summary(
    provenance: Iterable[BenchmarkProvenance],
) -> dict[str, int]:
    materialized = tuple(provenance)
    return {
        "permissioned_cases": sum(item.permissioned for item in materialized),
        "human_reviewed_cases": sum(item.human_reviewed for item in materialized),
        "manually_labeled_cases": sum(item.manually_labeled for item in materialized),
        "permissioned_human_reviewed_cases": sum(
            item.permissioned and item.human_reviewed for item in materialized
        ),
    }

"""Versioned extraction pipeline with exact, structured outputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .domain import (
    EvidenceRange,
    EvidenceScope,
    ImpactSignalDraft,
    PaymentSignalDraft,
    PipelineStage,
    ProblemFamily,
    ProblemType,
    SourceItemRecord,
    WorkaroundSignalDraft,
)
from .repository import IntegrityError, Repository


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    problem_type: ProblemType
    problem_family: ProblemFamily
    evidence_scope: EvidenceScope
    problem: str
    evidence_ranges: tuple[EvidenceRange, ...]
    fields: dict[str, Any] = field(default_factory=lambda: {})
    workarounds: tuple[WorkaroundSignalDraft, ...] = ()
    impact_signals: tuple[ImpactSignalDraft, ...] = ()
    payment_signals: tuple[PaymentSignalDraft, ...] = ()


class ProblemExtractor(Protocol):
    """Provider-neutral interface for a versioned extraction implementation."""

    @property
    def version(self) -> str: ...

    def extract(self, item: SourceItemRecord) -> Sequence[ObservationDraft]: ...


@runtime_checkable
class BatchValidatingExtractor(Protocol):
    """Optional extractor hook for validating a complete selected input batch."""

    def validate_batch(self, items: Sequence[SourceItemRecord]) -> None: ...


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    pipeline_run_id: str
    processed_items: int
    created_observations: int


def run_extraction(
    repository: Repository,
    extractor: ProblemExtractor,
    *,
    source_item_ids: Sequence[int] | None = None,
) -> ExtractionResult:
    """Run an extractor and retain both successful and failed run provenance."""

    items = repository.source_items(source_item_ids)
    if source_item_ids is not None and len(items) != len(set(source_item_ids)):
        raise ValueError("one or more source items do not exist")
    if isinstance(extractor, BatchValidatingExtractor):
        extractor.validate_batch(items)
    input_signature = _input_signature(items)
    completed = repository.completed_pipeline_run(
        stage=PipelineStage.EXTRACTION,
        version=extractor.version,
        input_signature=input_signature,
    )
    if completed is not None:
        run_id, input_count, output_count = completed
        return ExtractionResult(run_id, input_count, output_count)
    run_id = repository.start_pipeline_run(
        stage=PipelineStage.EXTRACTION,
        version=extractor.version,
        input_count=len(items),
    )
    output_count = 0
    try:
        for item in items:
            for draft in extractor.extract(item):
                if not draft.evidence_ranges:
                    raise IntegrityError("extractor returned an observation without evidence")
                fields = dict(draft.fields)
                fields.setdefault("country_code", item.country_code)
                fields.setdefault("language_code", item.language_code)
                repository.create_observation_with_evidence(
                    source_item_id=item.id,
                    problem_type=draft.problem_type,
                    problem_family=draft.problem_family,
                    ontology_version="problem-ontology-v1",
                    evidence_scope=draft.evidence_scope,
                    problem=draft.problem,
                    extraction_version=extractor.version,
                    evidence_ranges=draft.evidence_ranges,
                    fields=fields,
                    pipeline_run_id=run_id,
                    workarounds=draft.workarounds,
                    impact_signals=draft.impact_signals,
                    payment_signals=draft.payment_signals,
                )
                output_count += 1
    except Exception as exc:
        repository.fail_pipeline_run(run_id, output_count=output_count, error=str(exc))
        raise
    repository.finish_pipeline_run(
        run_id,
        output_count=output_count,
        input_signature=input_signature,
    )
    return ExtractionResult(run_id, len(items), output_count)


def _input_signature(items: Sequence[SourceItemRecord]) -> str:
    payload = [
        {
            "country_code": item.country_code,
            "external_id": item.external_id,
            "id": item.id,
            "language_code": item.language_code,
            "raw_text": item.raw_text,
            "source_id": item.source_id,
        }
        for item in items
    ]
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

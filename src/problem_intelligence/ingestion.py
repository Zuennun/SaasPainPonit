"""Application service for provider-neutral, idempotent ingestion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .connectors import ResearchJsonlCapture, SourceConnector
from .normalization import normalize_identifier, normalize_url
from .repository import Repository


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_id: int
    processed_items: int
    source_item_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ResearchCaptureResult:
    processed_sources: int
    processed_items: int
    source_ids: tuple[int, ...]
    source_item_ids: tuple[int, ...]


def ingest(repository: Repository, connector: SourceConnector) -> IngestionResult:
    """Persist every connector item while keeping provider details outside the repository."""

    descriptor = connector.source
    items = tuple(connector.iter_items())

    # Complete deterministic validation before the first write. A bad later line
    # must not leave an apparently successful prefix in the database.
    normalize_identifier(descriptor.source_type)
    normalize_identifier(descriptor.name)
    for item in items:
        normalize_identifier(item.external_id)
        normalize_url(item.url)
        json.dumps(item.metadata, sort_keys=True, separators=(",", ":"))

    source_id = repository.upsert_source(
        source_type=descriptor.source_type,
        name=descriptor.name,
        access_method=descriptor.access_method,
        commercial_use_status=descriptor.commercial_use_status,
        retention_rules=descriptor.retention_rules,
        attribution_requirements=descriptor.attribution_requirements,
        quoting_rules=descriptor.quoting_rules,
        deletion_requirements=descriptor.deletion_requirements,
        rate_limit_notes=descriptor.rate_limit_notes,
        rights_reviewed_at=descriptor.rights_reviewed_at,
    )
    item_ids: list[int] = []
    for item in items:
        item_ids.append(
            repository.upsert_source_item(
                source_id=source_id,
                external_id=item.external_id,
                raw_text=item.raw_text,
                url=item.url,
                title=item.title,
                author_external_id=item.author_external_id,
                published_at=item.published_at,
                country_code=item.country_code,
                language_code=item.language_code,
                metadata=item.metadata,
            )
        )
    return IngestionResult(source_id, len(item_ids), tuple(item_ids))


def ingest_research_capture(
    repository: Repository, capture: ResearchJsonlCapture | str | Path
) -> ResearchCaptureResult:
    """Ingest a fully validated multi-source research capture idempotently."""

    reader = capture if isinstance(capture, ResearchJsonlCapture) else ResearchJsonlCapture(capture)
    entries = tuple(reader.iter_entries())

    # Validate the complete capture before writing any prefix. Unknown policy is
    # represented explicitly in the input, never by an omitted field.
    for entry in entries:
        normalize_identifier(entry.source.source_type)
        normalize_identifier(entry.source.name)
        normalize_identifier(entry.item.external_id)
        normalize_url(entry.item.url)
        json.dumps(entry.item.metadata, sort_keys=True, separators=(",", ":"))

    source_ids: list[int] = []
    item_ids: list[int] = []
    source_cache: dict[tuple[str, str], int] = {}
    for entry in entries:
        descriptor = entry.source
        source_key = (
            normalize_identifier(descriptor.source_type),
            normalize_identifier(descriptor.name),
        )
        source_id = source_cache.get(source_key)
        if source_id is None:
            source_id = repository.upsert_source(
                source_type=descriptor.source_type,
                name=descriptor.name,
                access_method=descriptor.access_method,
                commercial_use_status=descriptor.commercial_use_status,
                retention_rules=descriptor.retention_rules,
                attribution_requirements=descriptor.attribution_requirements,
                quoting_rules=descriptor.quoting_rules,
                deletion_requirements=descriptor.deletion_requirements,
                rate_limit_notes=descriptor.rate_limit_notes,
                rights_reviewed_at=descriptor.rights_reviewed_at,
            )
            source_cache[source_key] = source_id
            source_ids.append(source_id)
        item = entry.item
        item_ids.append(
            repository.upsert_source_item(
                source_id=source_id,
                external_id=item.external_id,
                raw_text=item.raw_text,
                url=item.url,
                title=item.title,
                author_external_id=item.author_external_id,
                published_at=item.published_at,
                country_code=item.country_code,
                language_code=item.language_code,
                metadata=item.metadata,
            )
        )
    return ResearchCaptureResult(
        processed_sources=len(source_ids),
        processed_items=len(item_ids),
        source_ids=tuple(source_ids),
        source_item_ids=tuple(item_ids),
    )

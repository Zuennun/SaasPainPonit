"""Provider boundary and a connector for explicitly supplied local JSONL data."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast


class ConnectorDataError(ValueError):
    """Raised when a connector record cannot be represented without guessing."""


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_type: str
    name: str
    access_method: str
    commercial_use_status: str | None = None
    retention_rules: str | None = None
    attribution_requirements: str | None = None
    quoting_rules: str | None = None
    deletion_requirements: str | None = None
    rate_limit_notes: str | None = None
    rights_reviewed_at: str | None = None


@dataclass(frozen=True, slots=True)
class SourceItemInput:
    external_id: str
    raw_text: str
    url: str | None = None
    title: str | None = None
    author_external_id: str | None = None
    published_at: str | None = None
    country_code: str | None = None
    language_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=lambda: {})


class SourceConnector(Protocol):
    """Interface implemented by source-specific acquisition adapters."""

    @property
    def source(self) -> SourceDescriptor: ...

    def iter_items(self) -> Iterator[SourceItemInput]: ...


class JsonlFileConnector:
    """Read source items from a local file deliberately supplied by the operator."""

    _OPTIONAL_STRINGS = (
        "url",
        "title",
        "author_external_id",
        "published_at",
        "country_code",
        "language_code",
    )
    _KNOWN_FIELDS = frozenset(("external_id", "text", "metadata", *_OPTIONAL_STRINGS))

    def __init__(self, path: str | Path, *, source: SourceDescriptor) -> None:
        self.path = Path(path)
        self._source = source

    @property
    def source(self) -> SourceDescriptor:
        return self._source

    def iter_items(self) -> Iterator[SourceItemInput]:
        with self.path.open(encoding="utf-8") as source_file:
            for line_number, line in enumerate(source_file, start=1):
                if not line.strip():
                    continue
                location = f"{self.path}:{line_number}"
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ConnectorDataError(f"{location}: invalid JSON: {exc.msg}") from exc
                yield self.parse_record(record, location)

    @classmethod
    def parse_record(cls, record: object, location: str) -> SourceItemInput:
        if not isinstance(record, dict):
            raise ConnectorDataError(f"{location}: record must be a JSON object")
        record = cast(dict[str, Any], record)
        unknown = set(record) - cls._KNOWN_FIELDS
        if unknown:
            raise ConnectorDataError(
                f"{location}: unknown fields: {', '.join(sorted(unknown))}"
            )
        external_id = record.get("external_id")
        raw_text = record.get("text")
        if not isinstance(external_id, str) or not external_id.strip():
            raise ConnectorDataError(f"{location}: external_id must be a non-empty string")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ConnectorDataError(f"{location}: text must be a non-empty string")
        for field_name in cls._OPTIONAL_STRINGS:
            value = record.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ConnectorDataError(f"{location}: {field_name} must be a string or null")
        raw_metadata: object = record.get("metadata", {})
        if not isinstance(raw_metadata, dict):
            raise ConnectorDataError(f"{location}: metadata must be an object")
        metadata = cast(dict[str, Any], raw_metadata)
        return SourceItemInput(
            external_id=external_id,
            raw_text=raw_text,
            url=record.get("url"),
            title=record.get("title"),
            author_external_id=record.get("author_external_id"),
            published_at=record.get("published_at"),
            country_code=record.get("country_code"),
            language_code=record.get("language_code"),
            metadata=dict(metadata),
        )


@dataclass(frozen=True, slots=True)
class ResearchCaptureEntry:
    source: SourceDescriptor
    item: SourceItemInput


class ResearchJsonlCapture:
    """Read heterogeneous research evidence with policy metadata per source."""

    _TOP_LEVEL_FIELDS = frozenset(("source", "item"))
    _SOURCE_FIELDS = frozenset(
        (
            "source_type",
            "name",
            "access_method",
            "commercial_use_status",
            "retention_rules",
            "attribution_requirements",
            "quoting_rules",
            "deletion_requirements",
            "rate_limit_notes",
            "rights_reviewed_at",
        )
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def iter_entries(self) -> Iterator[ResearchCaptureEntry]:
        with self.path.open(encoding="utf-8") as source_file:
            for line_number, line in enumerate(source_file, start=1):
                if not line.strip():
                    continue
                location = f"{self.path}:{line_number}"
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ConnectorDataError(f"{location}: invalid JSON: {exc.msg}") from exc
                yield self._parse_entry(record, location)

    @classmethod
    def _parse_entry(cls, record: object, location: str) -> ResearchCaptureEntry:
        if not isinstance(record, dict):
            raise ConnectorDataError(f"{location}: record must be a JSON object")
        record = cast(dict[str, Any], record)
        unknown = set(record) - cls._TOP_LEVEL_FIELDS
        if unknown:
            raise ConnectorDataError(
                f"{location}: unknown fields: {', '.join(sorted(unknown))}"
            )
        raw_source = record.get("source")
        raw_item = record.get("item")
        if not isinstance(raw_source, dict):
            raise ConnectorDataError(f"{location}: source must be an object")
        if not isinstance(raw_item, dict):
            raise ConnectorDataError(f"{location}: item must be an object")
        source = cast(dict[str, Any], raw_source)
        unknown_source = set(source) - cls._SOURCE_FIELDS
        missing_source = cls._SOURCE_FIELDS - set(source)
        if unknown_source:
            raise ConnectorDataError(
                f"{location}.source: unknown fields: {', '.join(sorted(unknown_source))}"
            )
        if missing_source:
            raise ConnectorDataError(
                f"{location}.source: missing policy fields: "
                f"{', '.join(sorted(missing_source))}"
            )
        for field_name in cls._SOURCE_FIELDS:
            value = source[field_name]
            if not isinstance(value, str) or not value.strip():
                raise ConnectorDataError(
                    f"{location}.source: {field_name} must be a non-empty string"
                )
        descriptor = SourceDescriptor(
            source_type=source["source_type"],
            name=source["name"],
            access_method=source["access_method"],
            commercial_use_status=source["commercial_use_status"],
            retention_rules=source["retention_rules"],
            attribution_requirements=source["attribution_requirements"],
            quoting_rules=source["quoting_rules"],
            deletion_requirements=source["deletion_requirements"],
            rate_limit_notes=source["rate_limit_notes"],
            rights_reviewed_at=source["rights_reviewed_at"],
        )
        item = JsonlFileConnector.parse_record(
            cast(dict[str, Any], raw_item), f"{location}.item"
        )
        return ResearchCaptureEntry(descriptor, item)

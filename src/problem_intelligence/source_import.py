"""Import legacy source registries without turning old scores into truth."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .domain import AudienceType
from .repository import Repository


@dataclass(frozen=True, slots=True)
class _RegistryRow:
    line_number: int
    name: str
    values: dict[str, str]


_AUDIENCE_ALIASES = {
    "EMPLOYEE": AudienceType.PRACTITIONER,
    "PROFESSIONAL": AudienceType.PRACTITIONER,
    "GIG": AudienceType.PRACTITIONER,
    "GIG_WORKER": AudienceType.PRACTITIONER,
    "TECHNICAL": AudienceType.PRACTITIONER,
    "CREATOR": AudienceType.PRACTITIONER,
    "SELLER": AudienceType.OWNER,
    "SIDE_HUSTLE": AudienceType.OWNER,
    "LOCAL_SERVICE": AudienceType.OWNER,
    "FREELANCER": AudienceType.OWNER,
    "MANAGER": AudienceType.BUYER,
    "ORGANIZATION": AudienceType.BUYER,
    "HOBBY": AudienceType.CONSUMER,
    "HOBBY_PROSUMER": AudienceType.CONSUMER,
    "PROSUMER": AudienceType.CONSUMER,
    "COLLECTOR": AudienceType.CONSUMER,
    "TRAVEL": AudienceType.CONSUMER,
}


def _optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _integer(value: str | None, *, path: Path, line_number: int, field: str) -> int | None:
    cleaned = _optional(value)
    if cleaned is None:
        return None
    try:
        result = int(cleaned)
    except ValueError as exc:
        raise ValueError(f"{path}:{line_number}: {field} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{path}:{line_number}: {field} must not be negative")
    return result


def _scan_flag(value: str | None, *, path: Path, line_number: int) -> bool | None:
    cleaned = (value or "").strip().upper()
    if not cleaned:
        return None
    if cleaned in {"JA", "JA_LIGHT"}:
        return True
    if cleaned in {"NEIN", "NEIN_BIS_GEPRUEFT", "NUR_SEKUNDAER"}:
        return False
    raise ValueError(f"{path}:{line_number}: scan_now has unsupported value {value!r}")


STRICT_RELEVANCE_STATES = frozenset(
    {"CORE", "PILOT", "SECONDARY", "DROP", "RECHECK_ACCESS"}
)


def _strict_relevance(value: str | None, *, path: Path, line_number: int) -> str | None:
    cleaned = _optional(value)
    if cleaned is None:
        return None
    normalized = cleaned.strip().upper()
    if normalized not in STRICT_RELEVANCE_STATES:
        raise ValueError(
            f"{path}:{line_number}: strict_relevance has unsupported value {value!r}"
        )
    return normalized


def _audience(value: str | None) -> tuple[AudienceType, tuple[str, ...]]:
    raw_segments = tuple(
        dict.fromkeys(part.strip().upper() for part in (value or "").split("/") if part.strip())
    )
    mapped: list[AudienceType] = []
    for segment in raw_segments:
        try:
            candidate = AudienceType(segment)
        except ValueError:
            candidate = _AUDIENCE_ALIASES.get(segment, AudienceType.GENERAL)
        if candidate not in mapped:
            mapped.append(candidate)
    if not mapped:
        return AudienceType.GENERAL, ()
    if len(mapped) == 1:
        return mapped[0], raw_segments
    return AudienceType.MIXED, raw_segments


def _professions(value: str | None) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            part.strip()
            for part in re.split(r",\s*|\s+(?:und|sowie)\s+", value or "")
            if part.strip()
        )
    )


def import_subreddit_csv(repository: Repository, path: Path) -> tuple[int, ...]:
    parsed: list[_RegistryRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV requires a header row")
        lookup = {name.lower().strip(): name for name in reader.fieldnames}
        name_column = next(
            (lookup[key] for key in ("subreddit", "name", "community") if key in lookup),
            None,
        )
        if name_column is None:
            raise ValueError("CSV requires a subreddit, name, or community column")
        for line_number, row in enumerate(reader, 2):
            raw_name = (row.get(name_column) or "").strip()
            if not raw_name:
                raise ValueError(f"{path}:{line_number}: subreddit name is empty")
            name = raw_name[2:] if raw_name.lower().startswith("r/") else raw_name
            values = {key: value or "" for key, value in row.items() if key is not None}
            # Parse constrained values before making the first write, so malformed
            # registries cannot be partially imported.
            _scan_flag(values.get("scan_now"), path=path, line_number=line_number)
            _integer(
                values.get("pilot_posts"),
                path=path,
                line_number=line_number,
                field="pilot_posts",
            )
            _integer(
                values.get("strict_pilot_posts"),
                path=path,
                line_number=line_number,
                field="strict_pilot_posts",
            )
            _strict_relevance(values.get("strict_relevance"), path=path, line_number=line_number)
            parsed.append(_RegistryRow(line_number, name, values))

    source_ids: list[int] = []
    for entry in parsed:
        row = entry.values
        source_id = repository.upsert_source(
            source_type="reddit",
            name=f"r/{entry.name}",
        )
        repository.ensure_source_access_defaults(
            source_id,
            access_method="PUBLIC_WEB",
            commercial_use_status="REVIEW_REQUIRED",
        )
        repository.set_source_registry_metadata(
            source_id,
            namespace="legacy-csv",
            metadata=row,
        )
        if any(
            field in row
            for field in (
                "kategorie",
                "zielgruppe",
                "audience_type",
                "source_url",
                "recommended_action",
            )
        ):
            audience_type, audience_segments = _audience(row.get("audience_type"))
            repository.upsert_source_registry_profile(
                source_id,
                platform="REDDIT",
                canonical_url=_optional(row.get("source_url")),
                external_id=entry.name,
                primary_industry=_optional(row.get("kategorie")),
                professions=_professions(row.get("zielgruppe")),
                audience_type=audience_type,
                audience_segments=audience_segments,
                curation_decision=_optional(row.get("entscheidung")),
                curation_priority=_optional(row.get("prioritaet")),
                research_role=_optional(row.get("research_role")),
                scan_directive=_optional(row.get("scan_now")),
                scan_now=_scan_flag(
                    row.get("scan_now"), path=path, line_number=entry.line_number
                ),
                recommended_action=_optional(row.get("recommended_action")),
                strict_relevance=_strict_relevance(
                    row.get("strict_relevance"), path=path, line_number=entry.line_number
                ),
                strict_reason=_optional(row.get("strict_reason")),
                activity_status=_optional(row.get("aktivitaet")),
                activity_confidence=_optional(row.get("aktivitaet_confidence")),
                activity_basis=_optional(row.get("aktivitaet_basis")),
                dach_transfer=_optional(row.get("dach_transfer")),
                sensitive_data_risk=_optional(row.get("sensitive_data_risk")),
                research_angle=_optional(row.get("research_angle")),
                rationale=_optional(row.get("warum")),
                pilot_posts=_integer(
                    row.get("pilot_posts"),
                    path=path,
                    line_number=entry.line_number,
                    field="pilot_posts",
                ),
                strict_pilot_posts=_integer(
                    row.get("strict_pilot_posts"),
                    path=path,
                    line_number=entry.line_number,
                    field="strict_pilot_posts",
                ),
                registry_verified_at=_optional(row.get("verified_at")),
                notes=_optional(row.get("notes")),
            )
        source_ids.append(source_id)
    return tuple(source_ids)

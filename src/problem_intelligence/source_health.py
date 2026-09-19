"""Conservative, provider-neutral Reddit source-health capture and history."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

from .normalization import normalize_url
from .reddit import canonicalize_reddit_url
from .repository import IntegrityError, Repository


class HealthStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE_OR_LOW_ACTIVITY = "INACTIVE_OR_LOW_ACTIVITY"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AccessResult(StrEnum):
    PUBLIC_CONTENT = "PUBLIC_CONTENT"
    PUBLIC_NO_RECENT = "PUBLIC_NO_RECENT"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    PROVIDER_FAILED = "PROVIDER_FAILED"


@dataclass(frozen=True, slots=True)
class HealthCapture:
    source: str
    provider: str
    checked_at: str
    access_result: AccessResult
    http_status: int | None
    latest_visible_item_at: str | None
    visible_item_count: int
    sample_window_start: str | None
    sample_window_end: str | None
    coverage_complete: bool
    reason: str
    evidence_urls: tuple[str, ...]
    latency_ms: int | None
    cost_usd: float | None


@dataclass(frozen=True, slots=True)
class HealthDecision:
    status: HealthStatus
    confidence: str
    reason: str


class HealthProvider(Protocol):
    name: str

    def check(self, source: str) -> HealthCapture: ...


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def classify_health(capture: HealthCapture) -> HealthDecision:
    """One recent visible item proves activity; absence needs complete coverage."""

    checked = _utc(capture.checked_at, "checked_at")
    latest = (
        _utc(capture.latest_visible_item_at, "latest_visible_item_at")
        if capture.latest_visible_item_at
        else None
    )
    start = (
        _utc(capture.sample_window_start, "sample_window_start")
        if capture.sample_window_start
        else None
    )
    end = (
        _utc(capture.sample_window_end, "sample_window_end") if capture.sample_window_end else None
    )
    if latest and latest > checked:
        raise ValueError("latest_visible_item_at cannot be later than checked_at")
    if start and end and (start > end or end > checked):
        raise ValueError("sample window must end after its start and before checked_at")
    if capture.visible_item_count < 0:
        raise ValueError("visible_item_count must not be negative")
    if capture.access_result is AccessResult.PUBLIC_CONTENT and capture.evidence_urls:
        source_name = capture.source.removeprefix("r/").casefold()
        if not any(
            (identity := canonicalize_reddit_url(url)) is not None
            and identity.subreddit is not None
            and identity.subreddit.casefold() == source_name
            for url in capture.evidence_urls
        ):
            raise ValueError("public-content evidence must include a post in the checked source")
    if capture.access_result is AccessResult.ACCESS_RESTRICTED:
        return HealthDecision(HealthStatus.ACCESS_RESTRICTED, "HIGH", capture.reason)
    if capture.access_result is AccessResult.SOURCE_NOT_FOUND:
        return HealthDecision(HealthStatus.SOURCE_UNAVAILABLE, "MEDIUM", capture.reason)
    if capture.access_result is AccessResult.PROVIDER_FAILED:
        return HealthDecision(HealthStatus.UNKNOWN, "LOW", capture.reason)
    if (
        capture.access_result is AccessResult.PUBLIC_CONTENT
        and capture.visible_item_count > 0
        and latest is not None
        and latest >= checked - timedelta(days=30)
        and capture.evidence_urls
    ):
        return HealthDecision(HealthStatus.ACTIVE, "MEDIUM", capture.reason)
    if (
        capture.access_result is AccessResult.PUBLIC_NO_RECENT
        and capture.coverage_complete
        and start is not None
        and end is not None
        and start <= checked - timedelta(days=30)
        and end >= checked - timedelta(days=1)
        and (latest is None or latest < checked - timedelta(days=30))
    ):
        return HealthDecision(HealthStatus.INACTIVE_OR_LOW_ACTIVITY, "MEDIUM", capture.reason)
    return HealthDecision(
        HealthStatus.UNKNOWN,
        "LOW",
        "Insufficient public evidence to distinguish inactivity from retrieval limits: "
        + capture.reason,
    )


def _parse_capture(value: object, location: str) -> HealthCapture:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected object")
    row = cast(dict[str, Any], value)
    required = {
        "source",
        "provider",
        "checked_at",
        "access_result",
        "http_status",
        "latest_visible_item_at",
        "visible_item_count",
        "sample_window_start",
        "sample_window_end",
        "coverage_complete",
        "reason",
        "evidence_urls",
        "latency_ms",
        "cost_usd",
    }
    if set(row) != required:
        raise ValueError(f"{location}: missing or unknown fields: {sorted(set(row) ^ required)}")
    for key in ("source", "provider", "checked_at", "reason"):
        if not isinstance(row[key], str) or not row[key].strip():
            raise ValueError(f"{location}: {key} must be non-empty")
    for key in ("latest_visible_item_at", "sample_window_start", "sample_window_end"):
        if row[key] is not None and not isinstance(row[key], str):
            raise ValueError(f"{location}: {key} must be string or null")
    if not isinstance(row["visible_item_count"], int) or isinstance(
        row["visible_item_count"], bool
    ):
        raise ValueError(f"{location}: visible_item_count must be integer")
    if type(row["coverage_complete"]) is not bool:
        raise ValueError(f"{location}: coverage_complete must be boolean")
    for key in ("http_status", "latency_ms"):
        if row[key] is not None and (type(row[key]) is not int or row[key] < 0):
            raise ValueError(f"{location}: {key} must be non-negative integer or null")
    if row["http_status"] is not None and not 100 <= row["http_status"] <= 599:
        raise ValueError(f"{location}: http_status must be between 100 and 599")
    if row["cost_usd"] is not None and (
        type(row["cost_usd"]) not in (int, float)
        or not math.isfinite(row["cost_usd"])
        or row["cost_usd"] < 0
    ):
        raise ValueError(f"{location}: cost_usd must be non-negative number or null")
    urls = row["evidence_urls"]
    if not isinstance(urls, list) or not all(
        isinstance(url, str) for url in cast(list[object], urls)
    ):
        raise ValueError(f"{location}: evidence_urls must be a string array")
    typed_urls = cast(list[str], urls)
    normalized_urls = tuple(dict.fromkeys(normalize_url(url) for url in typed_urls))
    if any(url is None for url in normalized_urls):
        raise ValueError(f"{location}: evidence URL cannot be empty")
    capture = HealthCapture(
        source=row["source"].strip(),
        provider=row["provider"].strip(),
        checked_at=row["checked_at"],
        access_result=AccessResult(row["access_result"]),
        http_status=row["http_status"],
        latest_visible_item_at=row["latest_visible_item_at"],
        visible_item_count=row["visible_item_count"],
        sample_window_start=row["sample_window_start"],
        sample_window_end=row["sample_window_end"],
        coverage_complete=row["coverage_complete"],
        reason=row["reason"].strip(),
        evidence_urls=cast(tuple[str, ...], normalized_urls),
        latency_ms=row["latency_ms"],
        cost_usd=row["cost_usd"],
    )
    classify_health(capture)
    return capture


class JsonlHealthProvider:
    """Replay operator-reviewed observations from a permitted public provider."""

    def __init__(self, path: Path) -> None:
        captures: dict[str, HealthCapture] = {}
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = _parse_capture(json.loads(line), f"{path}:{line_number}")
            key = value.source.casefold()
            if key in captures:
                raise ValueError(f"{path}:{line_number}: duplicate source {value.source}")
            captures[key] = value
        if not captures:
            raise ValueError("health capture must not be empty")
        self._captures = captures
        self.name = "capture"

    def check(self, source: str) -> HealthCapture:
        try:
            return self._captures[source.casefold()]
        except KeyError as exc:
            raise ValueError(f"health capture lacks source {source}") from exc


def select_health_sources(
    repository: Repository,
    *,
    source: str | None = None,
    manifest: Path | None = None,
    relevance: str | None = None,
) -> tuple[tuple[int, str], ...]:
    if sum(value is not None for value in (source, manifest, relevance)) != 1:
        raise ValueError("choose exactly one of source, manifest, or relevance")
    if source is not None:
        names = (source,)
    elif manifest is not None:
        with manifest.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("health manifest requires a header")
            column = next(
                (name for name in ("source", "subreddit") if name in reader.fieldnames), None
            )
            if column is None:
                raise ValueError("health manifest requires source or subreddit column")
            names = tuple((row.get(column) or "").strip() for row in reader)
    else:
        if relevance not in {"CORE", "PILOT", "SECONDARY", "DROP", "RECHECK_ACCESS"}:
            raise ValueError("unsupported relevance state")
        rows = repository.connection.execute(
            """SELECT s.id, s.name FROM sources s
               JOIN source_registry_profiles p ON p.source_id = s.id
               WHERE p.strict_relevance = ? AND s.source_type = 'reddit'
               ORDER BY s.name COLLATE NOCASE, s.id""",
            (relevance,),
        ).fetchall()
        return tuple((int(row["id"]), str(row["name"])) for row in rows)
    if not names or any(not name for name in names):
        raise ValueError("health source selection is empty or contains blanks")
    selected: list[tuple[int, str]] = []
    seen: set[int] = set()
    for name in names:
        normalized = name if name.lower().startswith("r/") else f"r/{name}"
        row = repository.connection.execute(
            """SELECT id, name FROM sources WHERE source_type = 'reddit'
               AND lower(name) = lower(?)""",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Reddit source is not registered: {name}")
        source_id = int(row["id"])
        if source_id in seen:
            raise ValueError(f"duplicate source in selection: {name}")
        seen.add(source_id)
        selected.append((source_id, str(row["name"])))
    return tuple(selected)


def run_health_checks(
    repository: Repository,
    provider: HealthProvider,
    sources: tuple[tuple[int, str], ...],
) -> tuple[dict[str, Any], ...]:
    captures = tuple(provider.check(name) for _, name in sources)
    for capture, (_, name) in zip(captures, sources, strict=True):
        if capture.source.casefold() != name.casefold():
            raise ValueError(f"capture source mismatch: {capture.source} vs {name}")
    output: list[dict[str, Any]] = []
    with repository.transaction() as connection:
        for capture, (source_id, name) in zip(captures, sources, strict=True):
            decision = classify_health(capture)
            payload = json.dumps(asdict(capture), ensure_ascii=False, sort_keys=True)
            existing = connection.execute(
                """SELECT id, capture_json FROM source_health_checks
                   WHERE source_id = ? AND provider = ? AND checked_at = ?""",
                (source_id, capture.provider, capture.checked_at),
            ).fetchone()
            if existing is not None and existing["capture_json"] != payload:
                raise IntegrityError("health check identity already contains different evidence")
            if existing is None:
                cursor = connection.execute(
                    """INSERT INTO source_health_checks (
                           source_id, provider, checked_at, health_status, confidence,
                           access_result, http_status, latest_visible_item_at,
                           visible_item_count, sample_window_start, sample_window_end,
                           coverage_complete, reason, evidence_urls_json, latency_ms,
                           cost_usd, capture_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        capture.provider,
                        capture.checked_at,
                        decision.status.value,
                        decision.confidence,
                        capture.access_result.value,
                        capture.http_status,
                        capture.latest_visible_item_at,
                        capture.visible_item_count,
                        capture.sample_window_start,
                        capture.sample_window_end,
                        int(capture.coverage_complete),
                        decision.reason,
                        json.dumps(capture.evidence_urls),
                        capture.latency_ms,
                        capture.cost_usd,
                        payload,
                    ),
                )
                check_id = cursor.lastrowid
            else:
                check_id = existing["id"]
            output.append(
                {
                    "check_id": check_id,
                    "source_id": source_id,
                    "source": name,
                    "health_status": decision.status.value,
                    "confidence": decision.confidence,
                    "checked_at": capture.checked_at,
                    "provider": capture.provider,
                    "reason": decision.reason,
                }
            )
    return tuple(output)

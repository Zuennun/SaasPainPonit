"""Wave 1 selection and conservative acquisition-normalization helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .repository import Repository
from .source_health import HealthStatus
from .source_policy import source_policy_decision


@dataclass(frozen=True, slots=True)
class WaveSlot:
    slot: int
    category: str
    primary: str
    backup: str
    target_items: int


@dataclass(frozen=True, slots=True)
class WaveSelection:
    slot: int
    category: str
    source: str
    primary: str
    backup: str
    target_items: int
    health_status: str
    policy_ready: bool
    selection_status: str
    acquisition_eligible: bool


def read_wave_slots(path: Path) -> tuple[WaveSlot, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["slot", "category", "primary", "backup", "target_items"]:
            raise ValueError("Wave candidate CSV has unexpected columns")
        slots = tuple(
            WaveSlot(
                int(row["slot"]),
                row["category"].strip(),
                row["primary"].strip(),
                row["backup"].strip(),
                int(row["target_items"]),
            )
            for row in reader
        )
    if not slots or len({slot.slot for slot in slots}) != len(slots):
        raise ValueError("Wave slots must be nonempty and unique")
    if any(
        not slot.category
        or not slot.primary.startswith("r/")
        or not slot.backup.startswith("r/")
        or slot.target_items <= 0
        for slot in slots
    ):
        raise ValueError("Wave slots need category, Reddit candidates, and positive target")
    return slots


def _candidate_status(repository: Repository, source: str) -> tuple[str, bool]:
    row = repository.connection.execute(
        """SELECT s.*, p.strict_relevance, p.recommended_action,
                  (SELECT h.health_status FROM source_health_checks h
                   WHERE h.source_id = s.id ORDER BY h.checked_at DESC, h.id DESC LIMIT 1)
                  AS health_status
           FROM sources s JOIN source_registry_profiles p ON p.source_id = s.id
           WHERE s.source_type = 'reddit' AND lower(s.name) = lower(?)""",
        (source,),
    ).fetchone()
    if row is None or row["strict_relevance"] != "CORE":
        return "NOT_CORE", False
    return (
        str(row["health_status"] or HealthStatus.UNKNOWN),
        source_policy_decision(dict(row)).production_ready,
    )


def select_wave_sources(
    repository: Repository, slots: tuple[WaveSlot, ...]
) -> tuple[WaveSelection, ...]:
    """Only ACTIVE CORE sources are executable; failed primaries need healthy backups."""

    selections: list[WaveSelection] = []
    used: set[str] = set()
    for slot in slots:
        primary, primary_policy = _candidate_status(repository, slot.primary)
        backup, backup_policy = _candidate_status(repository, slot.backup)
        primary_available = slot.primary.casefold() not in used
        backup_available = slot.backup.casefold() not in used
        if primary == HealthStatus.ACTIVE and primary_available:
            source, health, policy_ready, selection = (
                slot.primary, primary, primary_policy, "PRIMARY_ACTIVE"
            )
        elif backup == HealthStatus.ACTIVE and backup_available:
            source, health, policy_ready, selection = (
                slot.backup, backup, backup_policy, "REPLACED_WITH_ACTIVE_BACKUP"
            )
        elif primary == HealthStatus.UNKNOWN and primary_available:
            source, health, policy_ready, selection = (
                slot.primary, primary, primary_policy, "NEEDS_HEALTH_CHECK"
            )
        elif backup == HealthStatus.UNKNOWN and backup_available:
            source, health, policy_ready, selection = (
                slot.backup, backup, backup_policy, "NEEDS_BACKUP_HEALTH_CHECK"
            )
        else:
            source, health, policy_ready, selection = (
                slot.primary, primary, primary_policy, "BLOCKED_NO_HEALTHY_REPLACEMENT"
            )
        if selection != "BLOCKED_NO_HEALTHY_REPLACEMENT":
            used.add(source.casefold())
        selections.append(
            WaveSelection(
                slot.slot,
                slot.category,
                source,
                slot.primary,
                slot.backup,
                slot.target_items,
                health,
                policy_ready,
                selection,
                health == HealthStatus.ACTIVE and policy_ready,
            )
        )
    return tuple(selections)


def write_wave_manifest(path: Path, selections: tuple[WaveSelection, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ("slot", "category", "source", "primary", "backup", "target_items",
             "health_status", "policy_ready", "selection_status", "acquisition_eligible")
        )
        for row in selections:
            writer.writerow(
                (row.slot, row.category, row.source, row.primary, row.backup,
                 row.target_items, row.health_status, str(row.policy_ready).lower(),
                 row.selection_status,
                 str(row.acquisition_eligible).lower())
            )


@dataclass(frozen=True, slots=True)
class AcquisitionCounts:
    requested: int
    discovered: int
    unique_urls: int
    full: int
    partial: int
    metadata_only: int
    failed: int

    @property
    def duplicates_removed(self) -> int:
        return max(0, self.discovered - self.unique_urls)

    @property
    def usable(self) -> int:
        return self.full

    @property
    def acquisition_success_rate(self) -> float | None:
        if not self.unique_urls:
            return None
        return self.full / self.unique_urls


def per_thousand(count: int, usable: int) -> float | None:
    return count * 1000 / usable if usable > 0 else None


def cost_per_strong_signal(cost_usd: float | None, strong_signals: int) -> float | None:
    if cost_usd is None or strong_signals <= 0:
        return None
    return cost_usd / strong_signals

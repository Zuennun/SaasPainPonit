"""Observable status of Reddit data providers behind the generic acquisition contract.

Only providers actually implemented in this codebase are reported. This module never
invents a status for a provider that does not exist, and never marks Brandwatch
production-approved on its own: that decision stays with contract/rights review.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .brandwatch import BrandwatchConfig, BrandwatchRedditProvider
from .brandwatch_poc import load_manifest
from .reddit_provider import ProductionReadiness


@dataclass(frozen=True, slots=True)
class ProviderStatusRow:
    name: str
    technical: str
    credentials: str
    rights: str
    production: str


@dataclass(frozen=True, slots=True)
class LiveRunGateResult:
    allowed: bool
    reasons: tuple[str, ...]


def brandwatch_provider_status(*, env: Mapping[str, str] | None = None) -> ProviderStatusRow:
    """Brandwatch's adapter, normalization, and conformance suite are already built and
    tested, so `technical` is READY independent of live credentials or configuration."""

    credentials = "AVAILABLE"
    try:
        BrandwatchConfig.from_environment(env)
    except ValueError:
        credentials = "MISSING"
    rights = BrandwatchRedditProvider.readiness
    production = "APPROVED" if rights is ProductionReadiness.PRODUCTION_APPROVED else "BLOCKED"
    return ProviderStatusRow("brandwatch", "READY", credentials, rights.value, production)


def known_provider_rows(*, env: Mapping[str, str] | None = None) -> tuple[ProviderStatusRow, ...]:
    return (brandwatch_provider_status(env=env),)


def render_provider_status_table(rows: Sequence[ProviderStatusRow]) -> str:
    headers = ("Provider", "Technical", "Credentials", "Rights", "Production")
    columns = [
        [row.name for row in rows], [row.technical for row in rows],
        [row.credentials for row in rows], [row.rights for row in rows],
        [row.production for row in rows],
    ]
    widths = [
        max(len(header), *(len(value) for value in column)) if rows else len(header)
        for header, column in zip(headers, columns, strict=True)
    ]
    lines = ["  ".join(header.ljust(width) for header, width in zip(headers, widths, strict=True))]
    for row in rows:
        values = (row.name, row.technical, row.credentials, row.rights, row.production)
        cells = (value.ljust(width) for value, width in zip(values, widths, strict=True))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def evaluate_live_run_gate(
    *,
    technical_adapter_ready: bool,
    credentials_available: bool,
    provider_configuration_valid: bool,
    rights_status: ProductionReadiness,
) -> LiveRunGateResult:
    reasons: list[str] = []
    if not technical_adapter_ready:
        reasons.append("technical adapter is not ready")
    if not credentials_available:
        reasons.append("provider credentials are not available in the environment")
    if not provider_configuration_valid:
        reasons.append("provider configuration (e.g. query IDs) is missing or invalid")
    if rights_status is not ProductionReadiness.PRODUCTION_APPROVED:
        reasons.append(f"rights status is {rights_status.value}, not PRODUCTION_APPROVED")
    return LiveRunGateResult(allowed=not reasons, reasons=tuple(reasons))


def evaluate_brandwatch_live_run_gate(
    manifest_path: Path, *, env: Mapping[str, str] | None = None
) -> LiveRunGateResult:
    credentials_available = True
    try:
        BrandwatchConfig.from_environment(env)
    except ValueError:
        credentials_available = False
    try:
        sources = load_manifest(manifest_path)
        configuration_valid = all(source.query_id is not None for source in sources)
    except ValueError:
        configuration_valid = False
    return evaluate_live_run_gate(
        technical_adapter_ready=True,
        credentials_available=credentials_available,
        provider_configuration_valid=configuration_valid,
        rights_status=BrandwatchRedditProvider.readiness,
    )

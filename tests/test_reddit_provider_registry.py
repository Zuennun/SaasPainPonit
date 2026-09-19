"""Provider readiness reporting and the live-run gate stay honest without credentials."""

from __future__ import annotations

import json
from pathlib import Path

from problem_intelligence.reddit_provider import ProductionReadiness
from problem_intelligence.reddit_provider_registry import (
    brandwatch_provider_status,
    evaluate_brandwatch_live_run_gate,
    evaluate_live_run_gate,
    known_provider_rows,
    render_provider_status_table,
)


def test_brandwatch_status_reports_missing_credentials_without_guessing() -> None:
    row = brandwatch_provider_status(env={})
    assert row.name == "brandwatch"
    assert row.technical == "READY"
    assert row.credentials == "MISSING"
    assert row.rights == "CONTRACT_REVIEW_REQUIRED"
    assert row.production == "BLOCKED"


def test_brandwatch_status_detects_available_credentials() -> None:
    row = brandwatch_provider_status(
        env={"BRANDWATCH_ACCESS_TOKEN": "secret", "BRANDWATCH_PROJECT_ID": "42"}
    )
    assert row.credentials == "AVAILABLE"
    assert row.production == "BLOCKED"


def test_only_implemented_providers_are_listed() -> None:
    rows = known_provider_rows(env={})
    assert [row.name for row in rows] == ["brandwatch"]


def test_status_table_renders_aligned_columns() -> None:
    table = render_provider_status_table(known_provider_rows(env={}))
    lines = table.splitlines()
    assert lines[0].startswith("Provider")
    assert "brandwatch" in lines[1]
    assert len(lines[0]) == len(lines[1])


def test_live_run_gate_blocks_on_any_missing_condition() -> None:
    blocked = evaluate_live_run_gate(
        technical_adapter_ready=True, credentials_available=False,
        provider_configuration_valid=True,
        rights_status=ProductionReadiness.CONTRACT_REVIEW_REQUIRED,
    )
    assert blocked.allowed is False
    assert any("credentials" in reason for reason in blocked.reasons)
    assert any("rights status" in reason for reason in blocked.reasons)


def test_live_run_gate_allows_only_when_every_condition_holds() -> None:
    allowed = evaluate_live_run_gate(
        technical_adapter_ready=True, credentials_available=True,
        provider_configuration_valid=True,
        rights_status=ProductionReadiness.PRODUCTION_APPROVED,
    )
    assert allowed == evaluate_live_run_gate(
        technical_adapter_ready=True, credentials_available=True,
        provider_configuration_valid=True,
        rights_status=ProductionReadiness.PRODUCTION_APPROVED,
    )
    assert allowed.allowed is True and allowed.reasons == ()


def test_brandwatch_live_run_gate_blocked_without_credentials_or_query_ids(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"sources": [{"name": "r/Accounting", "query_id": None}]}),
        encoding="utf-8",
    )
    result = evaluate_brandwatch_live_run_gate(manifest, env={})
    assert result.allowed is False
    assert any("credentials" in reason for reason in result.reasons)
    assert any("configuration" in reason for reason in result.reasons)
    assert any("rights status" in reason for reason in result.reasons)


def test_brandwatch_live_run_gate_still_blocked_on_rights_even_with_everything_else(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"sources": [{"name": "r/Accounting", "query_id": 1}]}),
        encoding="utf-8",
    )
    result = evaluate_brandwatch_live_run_gate(
        manifest, env={"BRANDWATCH_ACCESS_TOKEN": "secret", "BRANDWATCH_PROJECT_ID": "42"}
    )
    assert result.allowed is False
    assert result.reasons == (
        "rights status is CONTRACT_REVIEW_REQUIRED, not PRODUCTION_APPROVED",
    )

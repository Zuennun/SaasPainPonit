"""CLI surface for provider readiness and the live-run gate; no database required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from problem_intelligence.cli import main
from problem_intelligence.live_pilot import LiveManifestEntry, write_live_manifest_csv


def test_reddit_provider_status_lists_brandwatch(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reddit-provider-status"]) == 0
    out = capsys.readouterr().out
    assert "brandwatch" in out
    assert "Technical" in out and "Credentials" in out and "Rights" in out


def test_live_run_check_blocked_without_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BRANDWATCH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BRANDWATCH_PROJECT_ID", raising=False)
    exit_code = main(["reddit-provider-live-run-check", "--provider", "brandwatch"])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "brandwatch"
    assert payload["allowed"] is False
    assert payload["reasons"]


def test_live_run_check_explains_missing_query_configuration_even_with_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRANDWATCH_ACCESS_TOKEN", "secret")
    monkeypatch.setenv("BRANDWATCH_PROJECT_ID", "42")
    exit_code = main(["reddit-provider-live-run-check", "--provider", "brandwatch"])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert any("configuration" in reason for reason in payload["reasons"])
    assert any("rights status" in reason for reason in payload["reasons"])


def _write_manifest(path: Path) -> None:
    write_live_manifest_csv(path, (
        LiveManifestEntry("r/Accounting", "Finance", "Accountants", 100, "CORE",
                           "ACTIVE", "NOT_FLAGGED"),
        LiveManifestEntry("r/HVAC", "Trades", None, 50, "CORE", "ACTIVE", "NOT_FLAGGED"),
    ))


def test_live_pilot_dry_run_needs_no_database_and_makes_no_provider_calls(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BRANDWATCH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BRANDWATCH_PROJECT_ID", raising=False)
    manifest_path = tmp_path / "manifest.csv"
    _write_manifest(manifest_path)
    exit_code = main([
        "reddit-live-pilot", "--provider", "brandwatch", "--manifest", str(manifest_path),
        "--dry-run",
    ])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["made_external_requests"] is False
    assert payload["selected_source_count"] == 2
    assert payload["total_requested_items"] == 150
    assert payload["allowed"] is False
    assert payload["blocked_reasons"]


def test_live_pilot_real_run_blocked_without_database_or_dates(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BRANDWATCH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BRANDWATCH_PROJECT_ID", raising=False)
    manifest_path = tmp_path / "manifest.csv"
    _write_manifest(manifest_path)
    exit_code = main([
        "reddit-live-pilot", "--provider", "brandwatch", "--manifest", str(manifest_path),
    ])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is False

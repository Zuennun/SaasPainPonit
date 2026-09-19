"""CLI surface for provider readiness and the live-run gate; no database required."""

from __future__ import annotations

import json

import pytest

from problem_intelligence.cli import main


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

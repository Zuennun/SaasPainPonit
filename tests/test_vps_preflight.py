"""The single-VPS preflight is offline and does not acquire holdout data."""

from __future__ import annotations

from pathlib import Path

import pytest

from problem_intelligence.repository import Repository
from problem_intelligence.vps_preflight import check_vps_preflight, main

MANIFEST = Path(__file__).resolve().parents[1] / "docs/providers/arctic-shift-poc-manifest.csv"
USER_AGENT = "GlobalProblemIntelligence/0.1 (research prototype; contact=team)"


def baseline(tmp_path: Path) -> Path:
    path = tmp_path / "baseline.db"
    repository = Repository(path)
    repository.initialize()
    source_id = repository.upsert_source(source_type="reddit", name="r/Accounting")
    repository.upsert_source_item(
        source_id=source_id, external_id="reddit:submission:old001",
        raw_text="Synthetic development fixture.",
    )
    repository.close()
    return path


def local_env() -> dict[str, str]:
    return {
        "DISCOVERY_LLM_PROVIDER": "openai_compatible",
        "DISCOVERY_BASE_URL": "http://127.0.0.1:11434/v1",
        "DISCOVERY_MODEL": "configured-model",
        "DISCOVERY_LOCAL_INFERENCE": "true",
        "ARCTIC_SHIFT_USER_AGENT": USER_AGENT,
    }


def test_preflight_accepts_local_setup_without_network_or_holdout(tmp_path: Path) -> None:
    baseline_path = baseline(tmp_path)
    result = check_vps_preflight(
        local_env(), baseline_database=baseline_path, manifest=MANIFEST,
    )
    assert result["status"] == "READY_FOR_SYNTHETIC_MODEL_CHECK"
    assert result["baseline_exclusion_ids"] == 1
    assert result["manifest_sources"] == 5
    assert result["network_requests"] == result["holdout_records_accessed"] == 0
    assert not (tmp_path / "automated_holdout.db").exists()


def test_preflight_rejects_unsafe_or_incomplete_setup(tmp_path: Path) -> None:
    baseline_path = baseline(tmp_path)
    bad_agent = {**local_env(), "ARCTIC_SHIFT_USER_AGENT": "Mozilla/5.0 (browser)"}
    with pytest.raises(ValueError, match="USER_AGENT"):
        check_vps_preflight(bad_agent, baseline_database=baseline_path, manifest=MANIFEST)
    remote = {**local_env(), "DISCOVERY_BASE_URL": "https://example.invalid/v1"}
    with pytest.raises(ValueError, match="loopback"):
        check_vps_preflight(remote, baseline_database=baseline_path, manifest=MANIFEST)
    without_attestation = {**local_env(), "DISCOVERY_LOCAL_INFERENCE": "false"}
    with pytest.raises(ValueError, match="DISCOVERY_LOCAL_INFERENCE"):
        check_vps_preflight(
            without_attestation, baseline_database=baseline_path, manifest=MANIFEST,
        )
    with pytest.raises(FileNotFoundError):
        check_vps_preflight(
            local_env(), baseline_database=tmp_path / "missing.db", manifest=MANIFEST,
        )


def test_preflight_cli_uses_only_configured_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_path = baseline(tmp_path)
    for key, value in local_env().items():
        monkeypatch.setenv(key, value)
    assert main([
        "--baseline-database", str(baseline_path), "--manifest", str(MANIFEST),
    ]) == 0
    assert "READY_FOR_SYNTHETIC_MODEL_CHECK" in capsys.readouterr().out
    assert not (tmp_path / "automated_holdout.db").exists()

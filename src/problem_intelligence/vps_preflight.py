"""Offline, read-only checks before a single-VPS local-model holdout."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .automated_holdout import (
    EXPECTED_SOURCES,
    load_baseline_reddit_ids,
    valid_research_user_agent,
)
from .discovery_model import provider_from_environment
from .live_pilot import read_live_manifest_csv
from .openai_compatible import OpenAICompatibleProvider


def check_vps_preflight(
    env: Mapping[str, str], *, baseline_database: Path, manifest: Path,
) -> dict[str, Any]:
    """Inspect configuration and baseline identities; never call an API or write data."""
    provider = provider_from_environment(env)
    if not isinstance(provider, OpenAICompatibleProvider):
        raise ValueError("single-VPS setup requires DISCOVERY_LLM_PROVIDER=openai_compatible")
    if provider.endpoint_class != "loopback" or not provider.local_inference:
        raise ValueError(
            "single-VPS setup requires a loopback URL and DISCOVERY_LOCAL_INFERENCE=true"
        )
    user_agent = env.get("ARCTIC_SHIFT_USER_AGENT", "")
    if not valid_research_user_agent(user_agent):
        raise ValueError("truthful ARCTIC_SHIFT_USER_AGENT is required")
    entries = read_live_manifest_csv(manifest)
    if len(entries) != 5 or {entry.subreddit.casefold() for entry in entries} != set(
        EXPECTED_SOURCES
    ):
        raise ValueError("manifest must contain exactly the five baseline communities")
    excluded_ids = load_baseline_reddit_ids(baseline_database)
    return {
        "status": "READY_FOR_SYNTHETIC_MODEL_CHECK",
        "provider": provider.name,
        "model": provider.model,
        "endpoint_class": provider.endpoint_class,
        "local_inference_attested": provider.local_inference,
        "baseline_exclusion_ids": len(excluded_ids),
        "manifest_sources": len(entries),
        "network_requests": 0,
        "holdout_records_accessed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-database", type=Path,
        default=Path("data/reddit/arctic_shift_250_pilot.db"),
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=Path("docs/providers/arctic-shift-poc-manifest.csv"),
    )
    args = parser.parse_args(argv)
    try:
        result = check_vps_preflight(
            os.environ, baseline_database=args.baseline_database, manifest=args.manifest,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "NOT_READY", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

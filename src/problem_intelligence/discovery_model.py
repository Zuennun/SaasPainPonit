"""Configuration and synthetic connectivity gate for discovery inference."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping
from typing import Any

from .automated_discovery import (
    EXTRACT_INSTRUCTIONS,
    EXTRACT_SCHEMA,
    SCREEN_INSTRUCTIONS,
    SCREEN_SCHEMA,
    validate_extraction,
    validate_screen,
)
from .llm_provider import LLMProvider, ModelRequest
from .openai_compatible import OpenAICompatibleProvider
from .openai_responses import OpenAIResponsesProvider

SYNTHETIC_TEXT = "I spend 3 hours each Friday copying invoices between two systems by hand."


def provider_from_environment(env: Mapping[str, str] | None = None) -> LLMProvider:
    values = os.environ if env is None else env
    provider = values.get("DISCOVERY_LLM_PROVIDER", "openai")
    if provider == "openai":
        return OpenAIResponsesProvider.from_environment(values)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider.from_environment(values)
    raise ValueError("DISCOVERY_LLM_PROVIDER must be openai or openai_compatible")


def check_model(provider: LLMProvider, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    started = time.monotonic()
    measurements: list[dict[str, Any]] = []
    for stage, instructions, schema in (
        ("SCREENING", SCREEN_INSTRUCTIONS, SCREEN_SCHEMA),
        ("EXTRACTION", EXTRACT_INSTRUCTIONS, EXTRACT_SCHEMA),
    ):
        response = provider.complete_structured(ModelRequest(
            stage=stage, instructions=instructions, content=SYNTHETIC_TEXT,
            schema_name="connectivity_" + stage.casefold(), schema=schema,
            max_output_tokens=300 if stage == "SCREENING" else 1800,
            temperature=0.0, timeout_seconds=timeout_seconds,
        ))
        if stage == "SCREENING":
            result = validate_screen(response.data, SYNTHETIC_TEXT)
            if result.decision.value != "POTENTIAL_PAIN":
                raise ValueError("synthetic concrete workflow was not screened as pain")
        else:
            validate_extraction(response.data, SYNTHETIC_TEXT)
        measurements.append({
            "stage": stage, "latency_ms": response.latency_ms,
            "usage_reported": response.usage_reported,
            "input_tokens": response.input_tokens if response.usage_reported else None,
            "output_tokens": response.output_tokens if response.usage_reported else None,
        })
    return {
        "status": "READY", "provider": provider.name, "model": provider.model,
        "endpoint_class": getattr(provider, "endpoint_class", "remote"),
        "local_inference_attested": getattr(provider, "local_inference", False),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "stages": measurements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        provider = provider_from_environment()
        report = check_model(provider, timeout_seconds=args.timeout_seconds)
    except Exception as exc:
        report = {"status": "NOT_READY", "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

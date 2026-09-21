"""Codex CLI provider runs hosted structured inference without API-key handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from problem_intelligence.automated_discovery import SCREEN_SCHEMA
from problem_intelligence.codex_cli_provider import CodexCliProvider
from problem_intelligence.discovery_model import provider_from_environment
from problem_intelligence.llm_provider import InferenceFailure, ModelCallError, ModelRequest


def request() -> ModelRequest:
    return ModelRequest(
        stage="SCREENING",
        instructions="Classify the supplied synthetic workflow.",
        content="Synthetic workflow source text",
        schema_name="pain_screen",
        schema=SCREEN_SCHEMA,
        max_output_tokens=200,
        temperature=0,
        timeout_seconds=4,
    )


def screen() -> dict[str, Any]:
    return {
        "decision": "NO_PAIN",
        "origin": "UNCLEAR",
        "reason": "NO_CONCRETE_PROBLEM",
        "evidence_start": None,
        "evidence_end": None,
        "evidence_excerpt": None,
    }


def test_provider_selection_and_successful_structured_output() -> None:
    seen: dict[str, Any] = {}

    def runner(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        seen["args"] = args
        seen["input"] = kwargs["input"]
        seen["cwd"] = kwargs["cwd"]
        output = Path(args[args.index("-o") + 1])
        output.write_text(json.dumps(screen()), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    provider = CodexCliProvider(model="test-model", runner=runner)
    result = provider.complete_structured(request())
    assert result.data == screen()
    assert not result.usage_reported
    args = seen["args"]
    assert "--ephemeral" in args and "--sandbox" in args and "read-only" in args
    assert "--output-schema" in args and "--model" in args
    assert "Synthetic workflow source text" not in args
    assert "Synthetic workflow source text" in seen["input"]
    assert not Path(seen["cwd"]).exists()

    selected = provider_from_environment({"DISCOVERY_LLM_PROVIDER": "codex_cli"})
    assert isinstance(selected, CodexCliProvider)
    assert selected.model == "codex-default"


def test_timeout_and_nonzero_exit_fail_safely() -> None:
    def timeout_runner(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("codex", 4)

    with pytest.raises(ModelCallError) as timeout_error:
        CodexCliProvider(runner=timeout_runner).complete_structured(request())
    assert timeout_error.value.failure is InferenceFailure.TIMEOUT

    def failed_runner(
        args: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="source text", stderr="secret")

    with pytest.raises(ModelCallError, match="status 1") as failed_error:
        CodexCliProvider(runner=failed_runner).complete_structured(request())
    assert failed_error.value.failure is InferenceFailure.MODEL_UNAVAILABLE
    assert "source text" not in str(failed_error.value)
    assert "secret" not in str(failed_error.value)


def test_invalid_or_schema_nonconforming_output_is_rejected() -> None:
    def malformed_runner(
        args: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        output = Path(args[args.index("-o") + 1])
        output.write_text("not json", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with pytest.raises(ModelCallError) as malformed_error:
        CodexCliProvider(runner=malformed_runner).complete_structured(request())
    assert malformed_error.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT

    def invalid_runner(
        args: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        output = Path(args[args.index("-o") + 1])
        output.write_text('{"decision":"NO_PAIN"}', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with pytest.raises(ModelCallError) as invalid_error:
        CodexCliProvider(runner=invalid_runner).complete_structured(request())
    assert invalid_error.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT

"""Claude Code CLI provider runs hosted structured inference without API-key handling."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from problem_intelligence.automated_discovery import SCREEN_SCHEMA
from problem_intelligence.claude_cli_provider import ClaudeCliProvider
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


def envelope(result: str | dict[str, Any], *, usage: bool = True) -> str:
    payload: dict[str, Any] = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": result if isinstance(result, str) else json.dumps(result),
        "session_id": "sess-test",
    }
    if usage:
        payload["usage"] = {"input_tokens": 120, "output_tokens": 40}
    return json.dumps(payload)


def test_provider_selection_and_successful_structured_output() -> None:
    seen: dict[str, Any] = {}

    def runner(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        seen["args"] = args
        seen["input"] = kwargs["input"]
        out = envelope(screen())
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    provider = ClaudeCliProvider(model="test-model", runner=runner)
    result = provider.complete_structured(request())
    assert result.data == screen()
    assert result.usage_reported
    assert result.input_tokens == 120 and result.output_tokens == 40
    assert result.external_run_id == "sess-test"
    args = seen["args"]
    assert args[:3] == ["claude", "-p", "--output-format"]
    assert "--no-session-persistence" in args and "--model" in args
    assert "Synthetic workflow source text" not in args
    assert "Synthetic workflow source text" in seen["input"]
    assert "pain_screen" not in seen["input"] or SCREEN_SCHEMA["type"] in seen["input"]
    # embedded schema is present for output shaping
    assert '"decision"' in seen["input"]

    selected = provider_from_environment({"DISCOVERY_LLM_PROVIDER": "claude_cli"})
    assert isinstance(selected, ClaudeCliProvider)
    assert selected.model == "claude-default"
    assert selected.cache_identity == "claude-cli|claude-default"


def test_envelope_with_prose_wrapped_json_and_no_usage() -> None:
    def runner(
        args: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, 0, stdout=envelope("Sure! " + json.dumps(screen()) + " done",
                                     usage=False), stderr="",
        )

    result = ClaudeCliProvider(runner=runner).complete_structured(request())
    assert result.data == screen()
    assert not result.usage_reported
    assert result.input_tokens == 0


def test_timeout_nonzero_exit_and_error_envelope_fail_safely() -> None:
    def timeout_runner(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("claude", 4)

    with pytest.raises(ModelCallError) as to:
        ClaudeCliProvider(runner=timeout_runner).complete_structured(request())
    assert to.value.failure is InferenceFailure.TIMEOUT

    def failed_runner(
        args: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, 1, stdout="source text", stderr="You've hit your usage limit. sk-SECRET")

    with pytest.raises(ModelCallError, match="status 1") as nz:
        ClaudeCliProvider(runner=failed_runner).complete_structured(request())
    assert nz.value.failure is InferenceFailure.MODEL_UNAVAILABLE
    message = str(nz.value)
    assert "[rate-limited]" in message
    assert "source text" not in message and "sk-SECRET" not in message

    def error_envelope(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        row = {"is_error": True, "result": "credit balance too low sk-XYZ", "session_id": "s"}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(row), stderr="")

    with pytest.raises(ModelCallError) as err:
        ClaudeCliProvider(runner=error_envelope).complete_structured(request())
    assert err.value.failure is InferenceFailure.MODEL_UNAVAILABLE
    assert "sk-XYZ" not in str(err.value)


def test_invalid_or_schema_nonconforming_output_is_rejected() -> None:
    def malformed(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=envelope("not json at all"),
                                           stderr="")

    with pytest.raises(ModelCallError) as mal:
        ClaudeCliProvider(runner=malformed).complete_structured(request())
    assert mal.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT

    def invalid(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, 0, stdout=envelope({"decision": "NO_PAIN"}), stderr="")

    with pytest.raises(ModelCallError) as inv:
        ClaudeCliProvider(runner=invalid).complete_structured(request())
    assert inv.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT


def test_non_json_envelope_stdout_is_rejected() -> None:
    def runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="plain text", stderr="")

    with pytest.raises(ModelCallError) as err:
        ClaudeCliProvider(runner=runner).complete_structured(request())
    assert err.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT

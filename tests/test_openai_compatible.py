"""Local-compatible configuration and schema checks use no live endpoint."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

import pytest

from problem_intelligence.automated_discovery import SCREEN_SCHEMA
from problem_intelligence.discovery_model import (
    SYNTHETIC_TEXT,
    check_model,
    provider_from_environment,
)
from problem_intelligence.llm_provider import (
    InferenceFailure,
    ModelCallError,
    ModelRequest,
    ModelResponse,
)
from problem_intelligence.openai_compatible import OpenAICompatibleProvider
from problem_intelligence.openai_responses import OpenAIResponsesProvider


def request() -> ModelRequest:
    return ModelRequest(
        stage="SCREENING", instructions="Classify the synthetic text",
        content="Synthetic workflow text", schema_name="pain_screen",
        schema=SCREEN_SCHEMA, max_output_tokens=200, temperature=0,
        timeout_seconds=4,
    )


def screen() -> dict[str, Any]:
    return {
        "decision": "NO_PAIN", "origin": "UNCLEAR", "reason": "NO_CONCRETE_PROBLEM",
        "evidence_start": None, "evidence_end": None, "evidence_excerpt": None,
    }


def response(data: object, *, usage: bool = True) -> dict[str, Any]:
    result = {
        "id": "local-1", "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(data)},
        }],
    }
    if usage:
        result["usage"] = {"prompt_tokens": 8, "completion_tokens": 12}
    return result


def test_provider_selection_and_missing_local_settings() -> None:
    external = provider_from_environment({
        "DISCOVERY_LLM_PROVIDER": "openai", "DISCOVERY_MODEL": "external",
        "OPENAI_API_KEY": "test-key",
    })
    assert isinstance(external, OpenAIResponsesProvider)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        provider_from_environment({"DISCOVERY_MODEL": "external"})
    with pytest.raises(ValueError, match="DISCOVERY_BASE_URL"):
        provider_from_environment({"DISCOVERY_LLM_PROVIDER": "openai_compatible",
                                   "DISCOVERY_MODEL": "local"})
    with pytest.raises(ValueError, match="DISCOVERY_MODEL"):
        provider_from_environment({"DISCOVERY_LLM_PROVIDER": "openai_compatible",
                                   "DISCOVERY_BASE_URL": "http://127.0.0.1:11434/v1"})
    local = provider_from_environment({
        "DISCOVERY_LLM_PROVIDER": "openai_compatible",
        "DISCOVERY_BASE_URL": "http://127.0.0.1:11434/v1",
        "DISCOVERY_MODEL": "local",
    })
    assert isinstance(local, OpenAICompatibleProvider)
    assert local.endpoint_class == "loopback"
    assert not local.local_inference


def test_native_schema_request_and_usage_reporting() -> None:
    seen: list[dict[str, Any]] = []

    def transport(http_request: Request, timeout: float) -> dict[str, Any]:
        assert http_request.full_url == "http://127.0.0.1:11434/v1/chat/completions"
        assert http_request.get_header("Authorization") is None
        assert timeout == 4
        seen.append(json.loads(http_request.data or b"{}"))
        return response(screen())

    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:11434/v1", model="local",
        transport=transport,
    )
    result = provider.complete_structured(request())
    assert result.data == screen()
    assert result.usage_reported and (result.input_tokens, result.output_tokens) == (8, 12)
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    assert seen[0]["max_tokens"] == 200 and seen[0]["temperature"] == 0


def test_json_fallback_validates_full_schema_and_missing_usage() -> None:
    env = {
        "DISCOVERY_BASE_URL": "http://localhost:8000/v1", "DISCOVERY_MODEL": "local",
        "DISCOVERY_OUTPUT_MODE": "json_object",
        "DISCOVERY_SUPPORTS_TEMPERATURE": "false",
        "DISCOVERY_SUPPORTS_MAX_TOKENS": "false",
    }
    seen: list[dict[str, Any]] = []

    def transport(http_request: Request, _timeout: float) -> dict[str, Any]:
        seen.append(json.loads(http_request.data or b"{}"))
        return response(screen(), usage=False)

    provider = OpenAICompatibleProvider.from_environment(env, transport=transport)
    result = provider.complete_structured(request())
    assert not result.usage_reported
    assert result.input_tokens == 0
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "temperature" not in seen[0] and "max_tokens" not in seen[0]

    bad = OpenAICompatibleProvider.from_environment(
        env, transport=lambda _request, _timeout: response({"decision": "NO_PAIN"}),
    )
    with pytest.raises(ModelCallError) as error:
        bad.complete_structured(request())
    assert error.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT


def test_malformed_json_timeout_and_remote_classification() -> None:
    bad = OpenAICompatibleProvider(
        base_url="http://localhost:8000/v1", model="local",
        transport=lambda _request, _timeout: {
            "choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]
        },
    )
    with pytest.raises(ModelCallError, match="JSON"):
        bad.complete_structured(request())
    timeout = OpenAICompatibleProvider(
        base_url="http://localhost:8000/v1", model="local",
        transport=lambda _request, _timeout: (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(ModelCallError) as timeout_error:
        timeout.complete_structured(request())
    assert timeout_error.value.failure is InferenceFailure.TIMEOUT
    remote = OpenAICompatibleProvider(
        base_url="https://models.example.invalid/v1", model="remote",
    )
    assert remote.endpoint_class == "remote_or_unknown"
    with pytest.raises(ValueError, match="requires a loopback"):
        OpenAICompatibleProvider(
            base_url="https://models.example.invalid/v1", model="remote",
            local_inference=True,
        )
    with pytest.raises(ValueError, match="without credentials"):
        OpenAICompatibleProvider(
            base_url="http://user:secret@localhost:8000/v1", model="local",
        )


def test_synthetic_connectivity_never_uses_reddit_text() -> None:
    class SyntheticProvider:
        name = "synthetic"
        model = "stub"

        def __init__(self) -> None:
            self.stages: list[str] = []

        def complete_structured(self, model_request: ModelRequest) -> Any:
            self.stages.append(model_request.stage)
            assert "reddit" not in model_request.content.casefold()
            raise ModelCallError(InferenceFailure.MODEL_UNAVAILABLE, "not running")

    provider = SyntheticProvider()
    with pytest.raises(ModelCallError):
        check_model(provider)
    assert provider.stages == ["SCREENING"]


def test_synthetic_check_validates_both_stages_and_usage() -> None:
    excerpt = "I spend 3 hours each Friday copying invoices between two systems by hand."
    assert excerpt == SYNTHETIC_TEXT

    class ReadyProvider:
        name = "openai_compatible"
        model = "synthetic-model"
        endpoint_class = "loopback"

        def complete_structured(self, model_request: ModelRequest) -> ModelResponse:
            assert model_request.content == SYNTHETIC_TEXT
            if model_request.stage == "SCREENING":
                data = {
                    "decision": "POTENTIAL_PAIN", "origin": "PRACTITIONER_EVIDENCE",
                    "reason": "CONCRETE_WORKFLOW", "evidence_start": 0,
                    "evidence_end": len(excerpt), "evidence_excerpt": excerpt,
                }
            else:
                data = {
                    "problem_type": "WORKFLOW_GAP",
                    "problem_family": "MANUAL_DATA_ENTRY",
                    "claims": [{
                        "field": "problem_statement", "value": "Manual invoice copying",
                        "start": 0, "end": len(excerpt), "excerpt": excerpt,
                        "strength": "FIRST_PERSON", "signal_type": "NONE",
                        "quantity_value": None, "quantity_unit": None,
                        "frequency": None,
                    }],
                }
            return ModelResponse(data, 10, 20, 15, "synthetic", True)

    report = check_model(ReadyProvider())
    assert report["status"] == "READY"
    assert [stage["stage"] for stage in report["stages"]] == ["SCREENING", "EXTRACTION"]
    assert all(stage["usage_reported"] for stage in report["stages"])

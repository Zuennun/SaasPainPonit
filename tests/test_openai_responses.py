"""The concrete model adapter is tested without credentials or network calls."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

import pytest

from problem_intelligence.llm_provider import InferenceFailure, ModelCallError, ModelRequest
from problem_intelligence.openai_responses import OpenAIResponsesProvider


def request() -> ModelRequest:
    return ModelRequest(
        stage="SCREENING", instructions="Classify", content="Synthetic text",
        schema_name="test_schema", schema={
            "type": "object", "properties": {"decision": {"type": "string"}},
            "required": ["decision"], "additionalProperties": False,
        },
        max_output_tokens=200, temperature=0, timeout_seconds=5,
    )


def test_responses_adapter_sends_strict_schema_and_reads_usage() -> None:
    seen: list[dict[str, Any]] = []

    def transport(http_request: Request, timeout: float) -> dict[str, Any]:
        assert http_request.full_url == "https://api.openai.com/v1/responses"
        assert http_request.get_header("Authorization") == "Bearer test-secret"
        assert timeout == 5
        seen.append(json.loads(http_request.data or b"{}"))
        return {
            "id": "resp-test", "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 6},
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": '{"decision":"NO_PAIN"}'},
            ]}],
        }

    provider = OpenAIResponsesProvider(
        model="configured-model", api_key="test-secret", transport=transport,
    )
    result = provider.complete_structured(request())
    assert result.data == {"decision": "NO_PAIN"}
    assert result.input_tokens == 12 and result.output_tokens == 6
    assert result.external_run_id == "resp-test"
    assert seen[0]["store"] is False
    assert seen[0]["temperature"] == 0
    assert seen[0]["text"]["format"]["strict"] is True
    assert seen[0]["text"]["format"]["schema"]["additionalProperties"] is False


def test_refusal_or_incomplete_response_is_failure() -> None:
    for response in (
        {"id": "r1", "status": "incomplete", "usage": {
            "input_tokens": 3, "output_tokens": 2,
        }, "output": []},
        {"id": "r2", "status": "completed", "usage": {
            "input_tokens": 3, "output_tokens": 2,
        }, "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]},
    ):
        provider = OpenAIResponsesProvider(
            model="configured-model", api_key="test-secret",
            transport=lambda _request, _timeout, row=response: row,
        )
        with pytest.raises(ModelCallError) as error:
            provider.complete_structured(request())
        assert error.value.failure is InferenceFailure.INVALID_STRUCTURED_OUTPUT
        assert error.value.input_tokens == 3


def test_environment_requires_both_key_and_model() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIResponsesProvider.from_environment({})
    with pytest.raises(ValueError, match="DISCOVERY_MODEL"):
        OpenAIResponsesProvider.from_environment({"OPENAI_API_KEY": "key"})

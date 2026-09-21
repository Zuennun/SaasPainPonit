"""OpenAI Responses implementation of the generic structured LLM boundary."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .llm_provider import InferenceFailure, ModelCallError, ModelRequest, ModelResponse

RESPONSES_URL = "https://api.openai.com/v1/responses"
Transport = Callable[[Request, float], dict[str, Any]]


class OpenAIResponsesProvider:
    name = "openai"
    endpoint_class = "remote"
    cache_identity = RESPONSES_URL

    def __init__(
        self, *, model: str, api_key: str,
        transport: Transport | None = None,
    ) -> None:
        if not model.strip() or not api_key.strip():
            raise ValueError("model and API key are required")
        self.model = model.strip()
        self._api_key = api_key.strip()
        self._transport = transport or self.request_json

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None
    ) -> OpenAIResponsesProvider:
        values = os.environ if env is None else env
        key = values.get("OPENAI_API_KEY", "")
        model = values.get("DISCOVERY_MODEL", "")
        if not key:
            raise ValueError("OPENAI_API_KEY is required")
        if not model:
            raise ValueError("DISCOVERY_MODEL is required")
        return cls(model=model, api_key=key)

    def complete_structured(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": request.instructions,
            "input": request.content,
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.schema,
                }
            },
        }
        transport_request = Request(
            RESPONSES_URL,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            response = self._transport(transport_request, request.timeout_seconds)
        except ModelCallError:
            raise
        latency = round((time.monotonic() - started) * 1000)
        usage = response.get("usage")
        if not isinstance(usage, dict):
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "model usage missing",
                latency_ms=latency,
            )
        usage_data = cast(dict[str, object], usage)
        input_tokens = usage_data.get("input_tokens")
        output_tokens = usage_data.get("output_tokens")
        if (type(input_tokens) is not int or type(output_tokens) is not int
                or input_tokens < 0 or output_tokens < 0):
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "model token usage invalid",
                latency_ms=latency,
            )
        external_id = response.get("id")
        run_id = str(external_id) if isinstance(external_id, str) else None
        if response.get("status") != "completed":
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT,
                f"model response status {response.get('status')!r}",
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            )
        output = response.get("output")
        if not isinstance(output, list):
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "model output missing",
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            )
        texts: list[str] = []
        for item in cast(list[object], output):
            if not isinstance(item, dict):
                continue
            content = cast(dict[str, object], item).get("content")
            if not isinstance(content, list):
                continue
            for block in cast(list[object], content):
                if isinstance(block, dict):
                    parsed = cast(dict[str, object], block)
                    if parsed.get("type") == "refusal":
                        raise ModelCallError(
                            InferenceFailure.INVALID_STRUCTURED_OUTPUT,
                            "model refused structured output",
                            input_tokens=input_tokens, output_tokens=output_tokens,
                            latency_ms=latency, external_run_id=run_id,
                        )
                    if parsed.get("type") == "output_text" and isinstance(
                        parsed.get("text"), str
                    ):
                        texts.append(cast(str, parsed["text"]))
        if len(texts) != 1:
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT,
                "expected exactly one structured output text",
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            )
        try:
            data: object = json.loads(texts[0])
        except ValueError as exc:
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "invalid model JSON",
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            ) from exc
        if not isinstance(data, dict):
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "model JSON must be object",
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            )
        return ModelResponse(cast(dict[str, Any], data), input_tokens, output_tokens,
                             latency, run_id)

    @staticmethod
    def request_json(request: Request, timeout: float) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=timeout) as response:
                payload: object = json.load(response)
        except HTTPError as exc:
            if exc.code == 429:
                failure = InferenceFailure.RATE_LIMITED
            elif exc.code in {408, 504}:
                failure = InferenceFailure.TIMEOUT
            elif exc.code == 413:
                failure = InferenceFailure.CONTENT_TOO_LARGE
            elif exc.code == 400:
                failure = InferenceFailure.INVALID_STRUCTURED_OUTPUT
            elif exc.code in {401, 403} or exc.code >= 500:
                failure = InferenceFailure.MODEL_UNAVAILABLE
            else:
                failure = InferenceFailure.UNKNOWN_ERROR
            raise ModelCallError(failure, f"model HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise ModelCallError(InferenceFailure.TIMEOUT, "model request timed out") from exc
        except URLError as exc:
            raise ModelCallError(
                InferenceFailure.MODEL_UNAVAILABLE, "model request unavailable"
            ) from exc
        except ValueError as exc:
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "invalid response JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, "response is not an object"
            )
        return cast(dict[str, Any], payload)

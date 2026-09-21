"""OpenAI-compatible Chat Completions adapter; no runtime-specific dependency."""

from __future__ import annotations

import ipaddress
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit
from urllib.request import Request

from .llm_provider import InferenceFailure, ModelCallError, ModelRequest, ModelResponse
from .openai_responses import OpenAIResponsesProvider, Transport


def endpoint_class(base_url: str) -> str:
    parsed = urlsplit(base_url)
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("DISCOVERY_BASE_URL must be an http(s) URL without credentials")
    _ALLOWED_PATHS = {"", "/v1", "/v1beta/openai"}
    if parsed.query or parsed.fragment or parsed.path.rstrip("/") not in _ALLOWED_PATHS:
        raise ValueError("DISCOVERY_BASE_URL must end at the API root, /v1, or /v1beta/openai")
    if host.casefold() == "localhost":
        return "loopback"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "remote_or_unknown"
    if address.is_loopback:
        return "loopback"
    if address.is_private:
        return "private_network"
    return "remote_or_unknown"


def matches_schema(value: object, schema: dict[str, Any]) -> bool:
    kinds = schema.get("type")
    types = cast(list[object], kinds) if isinstance(kinds, list) else [kinds]
    if value is None:
        valid = "null" in types
    elif isinstance(value, bool):
        valid = "boolean" in types
    elif isinstance(value, str):
        valid = "string" in types
    elif isinstance(value, int):
        valid = "integer" in types or "number" in types
    elif isinstance(value, float):
        valid = "number" in types
    elif isinstance(value, list):
        valid = "array" in types
    elif isinstance(value, dict):
        valid = "object" in types
    else:
        valid = False
    if not valid or ("enum" in schema and value not in schema["enum"]):
        return False
    if isinstance(value, dict):
        obj = cast(dict[str, object], value)
        properties = cast(dict[str, dict[str, Any]], schema.get("properties", {}))
        required = cast(list[str], schema.get("required", []))
        return (
            all(field in obj for field in required)
            and (schema.get("additionalProperties") is not False
                 or all(field in properties for field in obj))
            and all(matches_schema(item, properties[field]) for field, item in obj.items()
                    if field in properties)
        )
    if isinstance(value, list) and "items" in schema:
        return all(matches_schema(item, cast(dict[str, Any], schema["items"]))
                   for item in cast(list[object], value))
    return True


@dataclass(frozen=True, slots=True)
class CompatibleCapabilities:
    output_mode: str = "json_schema"
    supports_temperature: bool = True
    supports_max_tokens: bool = True
    context_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.output_mode not in {"json_schema", "json_object"}:
            raise ValueError("DISCOVERY_OUTPUT_MODE must be json_schema or json_object")
        if self.context_tokens is not None and self.context_tokens <= 0:
            raise ValueError("DISCOVERY_CONTEXT_TOKENS must be positive")


def _boolean(value: str, name: str) -> bool:
    if value.casefold() in {"true", "1", "yes"}:
        return True
    if value.casefold() in {"false", "0", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _json_content(content: str) -> str:
    """Accept a whole JSON document, optionally wrapped in one Markdown fence."""

    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return stripped
    opener = lines[0].strip().casefold()
    if opener not in {"```", "```json"}:
        return stripped
    return "\n".join(lines[1:-1]).strip()


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self, *, base_url: str, model: str, api_key: str | None = None,
        local_inference: bool = False,
        capabilities: CompatibleCapabilities | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.endpoint_class = endpoint_class(base_url)
        if local_inference and self.endpoint_class != "loopback":
            raise ValueError("DISCOVERY_LOCAL_INFERENCE requires a loopback endpoint")
        self.local_inference = local_inference
        if not model.strip():
            raise ValueError("DISCOVERY_MODEL is required")
        self.base_url = base_url.rstrip("/")
        # Accept /v1, /v1beta/openai, or bare root as canonical API roots.
        _v1_suffixes = ("/v1", "/v1beta/openai")
        self.url = self.base_url if any(
            self.base_url.endswith(s) for s in _v1_suffixes
        ) else self.base_url + "/v1"
        self.model = model.strip()
        self._api_key = api_key
        self.capabilities = capabilities or CompatibleCapabilities()
        self.cache_identity = (
            f"{self.url}|{self.capabilities.output_mode}|"
            f"{self.capabilities.supports_temperature}|"
            f"{self.capabilities.supports_max_tokens}|"
            f"{self.capabilities.context_tokens}"
            f"|local_inference={self.local_inference}"
        )
        self._transport = transport or OpenAIResponsesProvider.request_json

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None,
        transport: Transport | None = None,
    ) -> OpenAICompatibleProvider:
        values = os.environ if env is None else env
        base_url = values.get("DISCOVERY_BASE_URL", "")
        if not base_url:
            raise ValueError("DISCOVERY_BASE_URL is required")
        context_raw = values.get("DISCOVERY_CONTEXT_TOKENS", "")
        capabilities = CompatibleCapabilities(
            output_mode=values.get("DISCOVERY_OUTPUT_MODE", "json_schema"),
            supports_temperature=_boolean(
                values.get("DISCOVERY_SUPPORTS_TEMPERATURE", "true"),
                "DISCOVERY_SUPPORTS_TEMPERATURE",
            ),
            supports_max_tokens=_boolean(
                values.get("DISCOVERY_SUPPORTS_MAX_TOKENS", "true"),
                "DISCOVERY_SUPPORTS_MAX_TOKENS",
            ),
            context_tokens=int(context_raw) if context_raw else None,
        )
        return cls(
            base_url=base_url, model=values.get("DISCOVERY_MODEL", ""),
            api_key=values.get("DISCOVERY_API_KEY"), capabilities=capabilities,
            local_inference=_boolean(
                values.get("DISCOVERY_LOCAL_INFERENCE", "false"),
                "DISCOVERY_LOCAL_INFERENCE",
            ),
            transport=transport,
        )

    def complete_structured(self, request: ModelRequest) -> ModelResponse:
        if self.capabilities.context_tokens is not None:
            # Conservative character-to-token bound: never silently truncate source text.
            if len(request.content) + len(request.instructions) > self.capabilities.context_tokens:
                raise ModelCallError(
                    InferenceFailure.CONTENT_TOO_LARGE, "configured context cap exceeded"
                )
        format_spec: dict[str, Any]
        if self.capabilities.output_mode == "json_schema":
            format_spec = {
                "type": "json_schema", "json_schema": {
                    "name": request.schema_name, "strict": True, "schema": request.schema,
                },
            }
        else:
            format_spec = {"type": "json_object"}
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.instructions + " Return only a JSON object."},
                {"role": "user", "content": request.content},
            ],
            "response_format": format_spec,
            "stream": False,
        }
        if self.capabilities.supports_temperature:
            payload["temperature"] = request.temperature
        if self.capabilities.supports_max_tokens:
            payload["max_tokens"] = request.max_output_tokens
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        http_request = Request(
            self.url + "/chat/completions",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers, method="POST",
        )
        started = time.monotonic()
        try:
            response = self._transport(http_request, request.timeout_seconds)
        except TimeoutError as exc:
            raise ModelCallError(InferenceFailure.TIMEOUT, "model request timed out") from exc
        latency = round((time.monotonic() - started) * 1000)
        usage = response.get("usage")
        usage_data = cast(dict[str, object], usage) if isinstance(usage, dict) else {}
        usage_reported = (
            type(usage_data.get("prompt_tokens")) is int
            and type(usage_data.get("completion_tokens")) is int
        )
        input_tokens = cast(int, usage_data["prompt_tokens"]) if usage_reported else 0
        output_tokens = cast(int, usage_data["completion_tokens"]) if usage_reported else 0
        external_id = response.get("id")
        run_id = external_id if isinstance(external_id, str) else None

        def invalid(message: str) -> ModelCallError:
            return ModelCallError(
                InferenceFailure.INVALID_STRUCTURED_OUTPUT, message,
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency, external_run_id=run_id,
            )

        if usage_reported and (input_tokens < 0 or output_tokens < 0):
            raise invalid("model token usage invalid")

        if response.get("error") or not isinstance(response.get("choices"), list):
            raise invalid("model error or choices missing")
        choices = cast(list[object], response["choices"])
        if len(choices) != 1 or not isinstance(choices[0], dict):
            raise invalid("expected one model choice")
        choice = cast(dict[str, object], choices[0])
        message = choice.get("message")
        if not isinstance(message, dict):
            raise invalid("model message missing or refused")
        message_data = cast(dict[str, object], message)
        if message_data.get("refusal"):
            raise invalid("model message missing or refused")
        if choice.get("finish_reason") not in {"stop", "length"} or not isinstance(
            message_data.get("content"), str
        ):
            raise invalid("model output incomplete or non-text")
        content = _json_content(cast(str, message_data["content"]))
        try:
            parsed: object = json.loads(content)
        except ValueError as exc:
            raise invalid("model did not return JSON") from exc
        if not isinstance(parsed, dict) or not matches_schema(
            cast(dict[str, object], parsed), request.schema
        ):
            raise invalid("model JSON does not satisfy required schema")
        return ModelResponse(
            cast(dict[str, Any], parsed), input_tokens, output_tokens,
            latency, run_id, usage_reported,
        )

"""Provider-neutral, metered structured-model request boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class InferenceFailure(StrEnum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    INVALID_STRUCTURED_OUTPUT = "INVALID_STRUCTURED_OUTPUT"
    EVIDENCE_VALIDATION_FAILED = "EVIDENCE_VALIDATION_FAILED"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ModelCallError(RuntimeError):
    def __init__(
        self, failure: InferenceFailure, message: str, *,
        input_tokens: int = 0, output_tokens: int = 0,
        latency_ms: int = 0, external_run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.external_run_id = external_run_id


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage: str
    instructions: str
    content: str
    schema_name: str
    schema: dict[str, Any]
    max_output_tokens: int
    temperature: float
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ModelResponse:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    external_run_id: str | None = None
    usage_reported: bool = True


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_structured(self, request: ModelRequest) -> ModelResponse: ...

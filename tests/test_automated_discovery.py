"""Synthetic two-stage inference tests; no external model or Reddit calls."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from problem_intelligence.automated_discovery import (
    AutomatedDiscovery,
    InferenceConfig,
    validate_extraction,
    validate_screen,
)
from problem_intelligence.domain import (
    ContentCompleteness,
    DiscoveryState,
    SourceAvailability,
)
from problem_intelligence.llm_provider import (
    InferenceFailure,
    ModelCallError,
    ModelRequest,
    ModelResponse,
)
from problem_intelligence.reddit import SearchResult
from problem_intelligence.repository import Repository

PAIN_TEXT = (
    "I run invoices manually every Friday. I need a tool because copying "
    "them into three systems wastes 3 hours every week."
)
NOISE_TEXT = (
    "The team held a general discussion of industry news today. "
    "Nobody described a specific operational problem or workaround."
)


def claim(
    field: str, value: str, excerpt: str, *,
    signal_type: str = "NONE", strength: str = "FIRST_PERSON",
    quantity_value: str | None = None,
    quantity_unit: str | None = None,
    frequency: str | None = None,
) -> dict[str, Any]:
    start = PAIN_TEXT.index(excerpt)
    return {
        "field": field, "value": value, "start": start,
        "end": start + len(excerpt), "excerpt": excerpt,
        "strength": strength, "signal_type": signal_type,
        "quantity_value": quantity_value, "quantity_unit": quantity_unit,
        "frequency": frequency,
    }


def screen_positive() -> dict[str, Any]:
    excerpt = "I run invoices manually every Friday."
    return {
        "decision": "POTENTIAL_PAIN", "origin": "PRACTITIONER_EVIDENCE",
        "reason": "CONCRETE_WORKFLOW", "evidence_start": 0,
        "evidence_end": len(excerpt), "evidence_excerpt": excerpt,
    }


def screen_negative(origin: str = "UNCLEAR") -> dict[str, Any]:
    return {
        "decision": "NO_PAIN", "origin": origin,
        "reason": "NO_CONCRETE_PROBLEM", "evidence_start": None,
        "evidence_end": None, "evidence_excerpt": None,
    }


def extracted() -> dict[str, Any]:
    return {
        "problem_type": "WORKFLOW_GAP",
        "problem_family": "MANUAL_DATA_ENTRY",
        "claims": [
            claim("problem_statement", "Manual duplicate invoice entry",
                  "copying them into three systems"),
            claim("actor", "I", "I run invoices manually"),
            claim("job_to_be_done", "copying invoices into three systems",
                  "copying them into three systems"),
            claim("context", "every Friday", "every Friday"),
            claim("manual_workaround", "manual invoice entry", "run invoices manually",
                  signal_type="MANUAL_ENTRY"),
            claim("active_solution_search", "need a tool", "I need a tool",
                  strength="ACTIVE_SOLUTION_SEARCH"),
            claim("quantified_impact", "3 hours every week", "3 hours every week",
                  signal_type="TIME", quantity_value="3", quantity_unit="hours",
                  frequency="every week"),
        ],
    }


class QueueProvider:
    name = "mock_llm"
    model = "mock-model-v1"

    def __init__(self, answers: Sequence[dict[str, Any] | ModelCallError]) -> None:
        self.answers = list(answers)
        self.calls: list[ModelRequest] = []

    def complete_structured(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, ModelCallError):
            raise answer
        return ModelResponse(answer, 100, 50, 20, f"mock-{len(self.calls)}")


def add_full_item(repository: Repository, text: str, post_id: str) -> int:
    source_id = repository.upsert_source(
        source_type="reddit", name="r/Accounting", access_method="archive:arctic_shift",
        commercial_use_status="REVIEW_REQUIRED",
    )
    url = f"https://www.reddit.com/r/Accounting/comments/{post_id}/"
    item_id = repository.upsert_source_item(
        source_id=source_id, external_id=f"reddit:submission:{post_id}",
        raw_text=text, url=url, metadata={"content_completeness": "FULL"},
    )
    run_id = repository.record_discovery_response(
        source_id=source_id, provider="arctic_shift", query="Accounting",
        availability=SourceAvailability.RESULTS,
        results=(SearchResult(url),), capabilities={},
        latency_ms=1, cost_usd=None, error=None,
    )
    row = repository.connection.execute(
        "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row is not None
    repository.record_acquisition(
        discovery_id=int(row["id"]), source_item_id=item_id,
        provider="arctic_shift", state=DiscoveryState.CONTENT_COMPLETE,
        completeness=ContentCompleteness.FULL, latency_ms=1,
        cost_usd=None, error=None, metadata={},
    )
    return item_id


@pytest.fixture
def repository() -> Repository:
    repo = Repository()
    repo.initialize()
    yield repo
    repo.close()


def test_validators_reject_missing_or_invalid_evidence() -> None:
    positive = screen_positive()
    assert validate_screen(positive, PAIN_TEXT).decision.value == "POTENTIAL_PAIN"
    with pytest.raises(ModelCallError) as missing:
        validate_screen({**positive, "evidence_excerpt": "invented"}, PAIN_TEXT)
    assert missing.value.failure is InferenceFailure.EVIDENCE_VALIDATION_FAILED
    with pytest.raises(ModelCallError) as vendor:
        validate_screen({**positive, "origin": "VENDOR_OR_PROMOTIONAL"}, PAIN_TEXT)
    assert vendor.value.failure is InferenceFailure.EVIDENCE_VALIDATION_FAILED
    result = extracted()
    assert validate_extraction(result, PAIN_TEXT).claims
    wrong = {**result, "claims": [{**result["claims"][0], "end": 10000}]}
    with pytest.raises(ModelCallError) as invalid:
        validate_extraction(wrong, PAIN_TEXT)
    assert invalid.value.failure is InferenceFailure.EVIDENCE_VALIDATION_FAILED
    no_problem = {**result, "claims": result["claims"][1:]}
    with pytest.raises(ModelCallError):
        validate_extraction(no_problem, PAIN_TEXT)


def test_vendor_claim_cannot_ground_observation() -> None:
    result = extracted()
    claims = list(result["claims"])
    claims[0] = {**claims[0], "strength": "VENDOR_CLAIM"}
    with pytest.raises(ModelCallError) as error:
        validate_extraction({**result, "claims": claims}, PAIN_TEXT)
    assert error.value.failure is InferenceFailure.EVIDENCE_VALIDATION_FAILED


def test_two_stage_pipeline_persists_grounded_observation_and_no_pain(
    repository: Repository,
) -> None:
    positive_id = add_full_item(repository, PAIN_TEXT, "abc100")
    negative_id = add_full_item(repository, NOISE_TEXT, "abc101")
    provider = QueueProvider([screen_positive(), extracted(), screen_negative()])
    runner = AutomatedDiscovery(repository, provider, InferenceConfig(
        max_retries=0, input_usd_per_million=Decimal("0.50"),
        output_usd_per_million=Decimal("1.00"),
    ))
    metrics = runner.run((positive_id, negative_id))
    assert metrics.screening_calls == 2 and metrics.extraction_calls == 1
    assert metrics.potential_pain == 1 and metrics.no_pain == 1
    assert metrics.valid_observations == 1 and metrics.strong_signals == 1
    assert metrics.input_tokens == 300 and metrics.output_tokens == 150
    assert metrics.known_cost_usd == Decimal("0.0003")
    assert metrics.inference_failures == 0
    rows = repository.connection.execute(
        """SELECT o.problem, o.actor, o.job_to_be_done, o.active_solution_search,
                  si.url, e.excerpt
           FROM problem_observations o
           JOIN source_items si ON si.id = o.source_item_id
           JOIN evidence_spans e ON e.observation_id = o.id
           WHERE o.source_item_id = ?""",
        (positive_id,),
    ).fetchall()
    assert rows and rows[0]["problem"] == "Manual duplicate invoice entry"
    assert rows[0]["actor"] == "I" and rows[0]["active_solution_search"] == 1
    assert rows[0]["url"].endswith("/abc100/")
    assert any(row["excerpt"] == "copying them into three systems" for row in rows)
    model_runs = repository.connection.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0]
    assert model_runs == 3
    assert all(call.schema["additionalProperties"] is False for call in provider.calls)

    second = runner.run((positive_id, negative_id))
    assert second.screening_calls == second.extraction_calls == 0
    assert second.cache_hits == 3 and second.valid_observations == 1
    assert len(provider.calls) == 3
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM problem_observations"
    ).fetchone()[0] == 1


def test_model_failure_is_not_no_pain_and_can_retry(repository: Repository) -> None:
    item_id = add_full_item(repository, PAIN_TEXT, "abc102")
    provider = QueueProvider([
        ModelCallError(InferenceFailure.RATE_LIMITED, "429"), screen_positive(), extracted(),
    ])
    metrics = AutomatedDiscovery(repository, provider, InferenceConfig(
        max_retries=1, retry_delay_seconds=0,
    )).run((item_id,))
    assert metrics.retries == 1
    assert metrics.screening_calls == 2 and metrics.extraction_calls == 1
    assert metrics.no_pain == 0 and metrics.valid_observations == 1
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM model_runs WHERE status = 'FAILED'"
    ).fetchone()[0] == 1
    attempts = repository.connection.execute(
        "SELECT attempt_number, failure_code FROM structured_inference_attempts "
        "WHERE stage = 'SCREENING' ORDER BY attempt_number"
    ).fetchall()
    assert [(row["attempt_number"], row["failure_code"]) for row in attempts] == [
        (0, "RATE_LIMITED"), (1, None),
    ]

    another = add_full_item(repository, NOISE_TEXT, "abc103")
    failing = QueueProvider([ModelCallError(InferenceFailure.MODEL_UNAVAILABLE, "offline")])
    failed = AutomatedDiscovery(repository, failing, InferenceConfig(max_retries=0)).run(
        (another,)
    )
    assert failed.no_pain == 0 and failed.inference_failures == 1
    assert failed.outcomes[0].status == "MODEL_FAILURE"


def test_invalid_model_output_metered_and_not_cached(repository: Repository) -> None:
    item_id = add_full_item(repository, PAIN_TEXT, "abc104")
    bad = {**screen_positive(), "evidence_end": 9999}
    provider = QueueProvider([bad])
    metrics = AutomatedDiscovery(repository, provider, InferenceConfig(max_retries=0)).run(
        (item_id,)
    )
    assert metrics.inference_failures == metrics.evidence_validation_failures == 1
    assert metrics.input_tokens == 100 and metrics.output_tokens == 50
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM structured_inference_cache"
    ).fetchone()[0] == 0


def test_pipeline_version_invalidates_cache(repository: Repository) -> None:
    item_id = add_full_item(repository, NOISE_TEXT, "abc105")
    provider = QueueProvider([screen_negative(), screen_negative()])
    AutomatedDiscovery(repository, provider, InferenceConfig(
        pipeline_version="version-one", max_retries=0,
    )).run((item_id,))
    AutomatedDiscovery(repository, provider, InferenceConfig(
        pipeline_version="version-two", max_retries=0,
    )).run((item_id,))
    assert len(provider.calls) == 2
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM structured_inference_cache"
    ).fetchone()[0] == 2


def test_promotional_screening_stops_before_extraction(repository: Repository) -> None:
    item_id = add_full_item(repository, NOISE_TEXT, "abc106")
    provider = QueueProvider([screen_negative("VENDOR_OR_PROMOTIONAL")])
    metrics = AutomatedDiscovery(repository, provider, InferenceConfig(max_retries=0)).run(
        (item_id,)
    )
    assert metrics.no_pain == 1 and metrics.valid_observations == 0
    assert metrics.extraction_calls == 0


def test_cache_identity_includes_content_and_model_configuration(repository: Repository) -> None:
    item_id = add_full_item(repository, NOISE_TEXT, "abc107")
    item = repository.source_items((item_id,))[0]
    provider = QueueProvider([])
    first = AutomatedDiscovery(repository, provider, InferenceConfig())
    changed_setting = AutomatedDiscovery(repository, provider, InferenceConfig(
        max_output_tokens_screen=400,
    ))
    assert first._identity(item, "SCREENING")[0] != (
        changed_setting._identity(item, "SCREENING")[0]
    )
    changed_content = type(item)(
        id=item.id, source_id=item.source_id, external_id=item.external_id,
        raw_text=item.raw_text + " New evidence.",
        country_code=item.country_code, language_code=item.language_code,
    )
    assert first._identity(item, "SCREENING")[0] != (
        first._identity(changed_content, "SCREENING")[0]
    )


def test_unknown_price_remains_unknown_and_missing_fields_are_null(
    repository: Repository,
) -> None:
    item_id = add_full_item(repository, PAIN_TEXT, "abc108")
    only_problem = {**extracted(), "claims": [extracted()["claims"][0]]}
    provider = QueueProvider([screen_positive(), only_problem])
    metrics = AutomatedDiscovery(repository, provider, InferenceConfig(max_retries=0)).run(
        (item_id,)
    )
    assert metrics.known_cost_usd is None
    row = repository.connection.execute(
        "SELECT actor, current_workaround, active_solution_search "
        "FROM problem_observations WHERE source_item_id = ?", (item_id,)
    ).fetchone()
    assert row is not None
    assert row["actor"] is row["current_workaround"] is row["active_solution_search"] is None


def test_unexpected_adapter_exception_is_metered_unknown_failure(
    repository: Repository,
) -> None:
    item_id = add_full_item(repository, PAIN_TEXT, "abc109")

    class BrokenProvider:
        name = "broken"
        model = "broken-model"

        def complete_structured(self, request: ModelRequest) -> ModelResponse:
            raise RuntimeError("unexpected failure")

    metrics = AutomatedDiscovery(
        repository, BrokenProvider(), InferenceConfig(max_retries=0),
    ).run((item_id,))
    assert metrics.no_pain == 0 and metrics.inference_failures == 1
    assert metrics.outcomes[0].failure is InferenceFailure.UNKNOWN_ERROR
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM model_runs WHERE status = 'FAILED'"
    ).fetchone()[0] == 1


def test_loopback_api_charge_zero_and_usage_unreported_is_explicit(
    repository: Repository,
) -> None:
    item_id = add_full_item(repository, NOISE_TEXT, "local110")

    class LocalProvider:
        name = "openai_compatible"
        model = "local-model"
        endpoint_class = "loopback"
        local_inference = True
        cache_identity = "http://127.0.0.1:8000/v1|json_object"

        def complete_structured(self, request: ModelRequest) -> ModelResponse:
            return ModelResponse(screen_negative(), 0, 0, 15, "local-1", False)

    metrics = AutomatedDiscovery(
        repository, LocalProvider(), InferenceConfig(max_retries=0),
    ).run((item_id,))
    assert metrics.no_pain == 1
    assert metrics.known_cost_usd == Decimal(0)
    assert metrics.unreported_usage_calls == 1
    row = repository.connection.execute(
        """SELECT mr.provider, ce.amount_decimal, ce.measurement_source,
                  sia.endpoint_class, sia.usage_reported
           FROM model_runs mr JOIN cost_events ce ON ce.model_run_id = mr.id
           JOIN structured_inference_attempts sia ON sia.model_run_id = mr.id"""
    ).fetchone()
    assert row is not None
    assert row["provider"] == "openai_compatible"
    assert row["amount_decimal"] == "0"
    assert row["measurement_source"] == "local-api-charge"
    assert row["endpoint_class"] == "loopback" and row["usage_reported"] == 0

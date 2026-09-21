# Automated problem discovery, first unseen holdout

For the single-VPS local-server preparation sequence, see
[VPS discovery start](vps-discovery-start.md). Its offline preflight and
synthetic check do not acquire holdout posts.

This phase does **not** change Arctic Shift acquisition or the deterministic
signal policy. It adds a two-stage inference service over canonical FULL Reddit
`SourceItem`s: structured screening (`NO_PAIN` / `POTENTIAL_PAIN`), then
structured extraction, exact source-offset validation, `ProblemObservation`
and `EvidenceSpan` persistence, then the existing strong-signal SQL policy.

The application depends on `LLMProvider`, not on an OpenAI-specific response
shape. `OpenAIResponsesProvider` is one concrete adapter. It uses the
[Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
with [strict JSON-schema structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
explicit token usage, Bearer authorization, and `store: false`. It treats
incomplete, refused, malformed, or usage-less responses as failures, not
`NO_PAIN`. Different models may have different support for temperature or
structured outputs; select and verify an account-accessible model explicitly.

## Two execution paths and rights gate

The existing `LLMProvider` boundary supports the OpenAI Responses API, an
OpenAI-compatible Chat Completions endpoint, and an authenticated Codex CLI
session. The screening/extraction prompts, schemas, validators, and signal
policy are identical in all paths. No model runtime or model weights are
installed by this repository.

For the external OpenAI API, set `DISCOVERY_LLM_PROVIDER=openai`,
`OPENAI_API_KEY`, and `DISCOVERY_MODEL`. The holdout command additionally needs
`--llm-rights-confirmed`, **only after written confirmation** that source text
may be sent to a third-party LLM. Never commit credentials.

For an installed, authenticated Codex CLI subscription, set:

```bash
export DISCOVERY_LLM_PROVIDER=codex_cli
# Optional: export DISCOVERY_MODEL='<account-accessible-codex-model>'
python -m problem_intelligence.discovery_model --timeout-seconds 180
```

This path invokes `codex exec` with an ephemeral read-only sandbox and a strict
output schema. It reads authentication from the Codex CLI; the repository never
reads or stores the OAuth credential. Token usage is reported as unknown because
the CLI does not expose stable per-request usage metadata to this adapter. It is
a remote provider and therefore still requires `--llm-rights-confirmed` for a
holdout run.

For an inference server running on this machine, use:

```bash
export DISCOVERY_LLM_PROVIDER=openai_compatible
export DISCOVERY_BASE_URL=http://127.0.0.1:11434/v1
export DISCOVERY_MODEL='<installed-local-model-id>'
export DISCOVERY_LOCAL_INFERENCE=true
# Optional only when the server demands a token:
# export DISCOVERY_API_KEY='<server-token>'
export ARCTIC_SHIFT_USER_AGENT='GlobalProblemIntelligence/0.1 (research prototype; contact=<your-contact>)'
python -m problem_intelligence.discovery_model
```

`DISCOVERY_BASE_URL` must be an HTTP(S) API root, `/v1` URL, or the Google
AI Studio-compatible `/v1beta/openai` root, without embedded credentials.
`DISCOVERY_OUTPUT_MODE=json_schema` (default) requests native
schema-constrained output. Set `DISCOVERY_OUTPUT_MODE=json_object` only if the
endpoint lacks native schema mode; every response is still checked against the
full schema and the existing evidence validators. Optional capability settings:
`DISCOVERY_SUPPORTS_TEMPERATURE=false`, `DISCOVERY_SUPPORTS_MAX_TOKENS=false`,
and `DISCOVERY_CONTEXT_TOKENS=<positive integer>`. The last setting is a
conservative input-length safety bound; no text is silently truncated. Choose
an endpoint and model that pass the synthetic check; no particular local model
has yet been benchmarked for extraction quality.

The synthetic command above sends **no Reddit content**. It checks both
screening and extraction, exact evidence validation, latency, and whether token
usage is reported. It returns nonzero on incompatibility. The holdout runner
repeats this check before acquisition. Missing usage metadata is recorded as
unknown, never as zero tokens. `DISCOVERY_LOCAL_INFERENCE=true` is an operator
attestation that the loopback server actually runs inference locally and does
not proxy source text elsewhere. It is accepted only for a loopback URL.
Without that attestation, even a loopback URL requires
`--llm-rights-confirmed` and no zero-cost/local-processing claim is made.

Set one truthful, stable `ARCTIC_SHIFT_USER_AGENT` in `Product/version (purpose;
contact=...)` form, or pass `--user-agent`. It is not a secret; do not spoof a
browser/Reddit client or rotate it. No personal email is hard-coded. Local
loopback processing does not send source text to a third-party LLM, but does
**not** itself settle commercial data rights. The project owner has stated
that the required rights are held; the older
[Arctic Shift rights checklist](providers/arctic-shift-rights-checklist.md)
has not yet been reconciled with that confirmation. This documentation gap is
not treated as a VPS-connectivity blocker.

After a human explicitly authorizes the unseen holdout run, the exact command
for the configured local endpoint is:

```bash
python -m problem_intelligence.automated_holdout \
  --start-date 2026-08-15 --end-date 2026-09-05
```

For the external path (or any non-loopback compatible URL), add
`--llm-rights-confirmed`. **Do not run the holdout during endpoint setup.**

Defaults: exactly five sources from the Arctic Shift manifest, 50 records each
(250 maximum), one Arctic Shift request per source, a three-second minimum
request spacing, and a historical window not used by the 250-record baseline.
The runner additionally excludes every Reddit identity in the baseline DB;
it refuses to infer if no unseen FULL items remain. No reddit.com or RSS
fallback exists in this runner. The original 250-post baseline is diagnostic
data, **not** an evaluation holdout.

Model controls: `--temperature`, `--max-screen-tokens`,
`--max-extract-tokens`, `--timeout-seconds`, `--max-retries`. Optional explicit
`--input-usd-per-million` and `--output-usd-per-million` prices produce a
calculated USD cost for non-loopback endpoints; otherwise cost stays `UNKNOWN`.
For loopback inference, the direct API charge is reported as zero, while
hardware/electricity/infrastructure cost stays `UNKNOWN`. They are *configured*
prices, not automatically fetched vendor prices.

## Reliability and provenance

- Each real call is recorded in `model_runs` and
  `structured_inference_attempts`: stage, provider, model, prompt version,
  reported input/output tokens, usage availability, endpoint class, latency,
  status, attempt number, and failure code. No API key or secret URL is stored.
- Valid structured results are cached by SourceItem identity/content hash,
  stage, pipeline/prompt/schema version, and model settings. Repeating an
  unchanged run does not pay for new inference. Failed calls are not cached.
- An observation is stored only after exact excerpts match source character
  offsets. Missing claims stay absent/null. Numeric claims whose digits do not
  appear in the cited excerpt are rejected. This is structural grounding, not
  a substitute for human assessment of semantic faithfulness.
- Evidence strength (`FIRST_PERSON`, `DIRECT_WORKFLOW_DESCRIPTION`,
  `ACTIVE_SOLUTION_SEARCH`, `THIRD_PARTY_DESCRIPTION`, `VENDOR_CLAIM`) remains
  in the versioned structured inference record. A vendor-only problem claim
  cannot create an observation.
- `MODEL_FAILURE` is distinct from `NO_PAIN`; retries apply only to transient
  unavailable/rate-limit/timeout failures. Existing signal thresholds are
  untouched. Exact-fingerprint clustering cannot identify semantic recurrence
  and is intentionally **not** changed here.

## Outputs and interpretation

The live runner writes `exports/automated_discovery_holdout.md`,
`exports/automated_discovery_holdout_metrics.json`, and
`exports/automated_discovery_review.csv`. Positives and a deterministic
NO_PAIN sample are exported with human-review columns blank. Do not edit model
outputs after review. The report includes only actual model-produced examples;
likely false positives and missed pain cannot be identified without later
human labels. It cannot claim precision or readiness for semantic clustering
from unreviewed output alone.

When configuration or rights are missing, these files contain an explicit
`NOT_RUN_CONFIGURATION_REQUIRED` state, null measurements, no examples, and a
header-only review CSV. This is **not** an automated-discovery benchmark.

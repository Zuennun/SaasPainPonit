# VPS start package: local discovery inference

This is a preparation and launch runbook for **one VPS hosting both the model
server and this application**. It does not select or install a model runtime:
the VPS CPU/GPU/RAM and an available model have not yet been confirmed. Keep
the inference API bound to loopback (`127.0.0.1`), not a public interface.
The runtime must expose an OpenAI-compatible `/v1/chat/completions` endpoint.

## Before connecting to Arctic Shift

1. Install this repository on the VPS with Python 3.11+ and its normal project
   dependencies. Transfer `data/reddit/arctic_shift_250_pilot.db` through an
   approved channel: it is deliberately **not** in Git (`*.db` is ignored).
   Verify its SHA-256 digest on the source and VPS. Do not publish it or the
   future holdout database.
2. Start a model server on the VPS and configure a model it actually has. The
   example port below is a placeholder; use the real local server port. Ensure
   no proxy forwards source text to an external provider before attesting local
   inference. Do not expose the model API publicly.
3. Set environment variables in the shell **on the VPS** (not on a laptop):

   ```bash
   export DISCOVERY_LLM_PROVIDER=openai_compatible
   export DISCOVERY_BASE_URL=http://127.0.0.1:11434/v1
   export DISCOVERY_MODEL='<actual-installed-model-id>'
   export DISCOVERY_LOCAL_INFERENCE=true
   export ARCTIC_SHIFT_USER_AGENT='GlobalProblemIntelligence/0.1 (research prototype; contact=<real-contact>)'
   # Only if the server requires a token: export DISCOVERY_API_KEY='<server-token>'
   ```

   Use one truthful, stable User-Agent. Do not put credentials in Git. If the
   endpoint cannot accept native JSON Schema, set
   `DISCOVERY_OUTPUT_MODE=json_object`; schema and evidence validation remain
   mandatory. Optional endpoint capability flags are described in
   [automated-discovery.md](automated-discovery.md).

4. Run the **offline configuration preflight** from the repository root:

   ```bash
   python -m problem_intelligence.vps_preflight
   ```

   It checks local endpoint configuration, User-Agent shape, the five-source
   manifest, and that the original baseline IDs can be read. It does not
   contact the model server or Arctic Shift and does not read future holdout
   posts. It must report `READY_FOR_SYNTHETIC_MODEL_CHECK`.
5. Run the **synthetic connectivity test**:

   ```bash
   python -m problem_intelligence.discovery_model
   ```

   It sends one synthetic workflow sentence to each inference stage. Require
   `status: READY`, successful schema/evidence validation for both stages, and
   inspect latency and `usage_reported`. Missing usage metadata is allowed but
   later token totals must be marked unknown. Failures here are not a reason to
   inspect or tune against the unseen holdout.

Stop at this point. Neither preflight command acquires or inspects holdout
posts. A successful check means the stack is technically ready to attempt the
first benchmark; it does **not** demonstrate discovery quality.

## Human-authorized holdout, later

Only after a separate explicit go-ahead, run once from the same repository
root and environment:

```bash
python -m problem_intelligence.automated_holdout \
  --baseline-database data/reddit/arctic_shift_250_pilot.db \
  --database data/reddit/automated_holdout.db \
  --start-date 2026-08-15 --end-date 2026-09-05
```

The runner repeats the synthetic check, uses only Arctic Shift, caps
acquisition at 250 posts across five communities, excludes previously reviewed
Reddit IDs, and only then invokes inference. No direct Reddit or RSS fallback
is used. Do not edit prompts, thresholds, or model outputs during the holdout.
Inspect `exports/automated_discovery_holdout_metrics.json`, the report, and the
blank-label review CSV afterward. A model failure is not `NO_PAIN`; the human
precision review and any decision about semantic clustering are separate.

Local direct API inference charge can be €0; VPS hardware, electricity,
storage, and administration are **not** zero-cost. The operator has stated that
data rights are settled; this runbook does not make or revise a legal finding.

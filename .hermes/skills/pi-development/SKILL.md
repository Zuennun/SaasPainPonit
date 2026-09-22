---
name: pi-development
description: Engineering workflow for implementing and modifying the Global Problem Intelligence codebase.
---

# PI Development Workflow

Use this skill for backend, frontend, database, pipeline, provider, infrastructure
and automated-discovery development.

Before editing:
- Inspect git status.
- Read relevant AGENTS.md and ADR/docs.
- Locate existing abstractions before introducing new ones.
- Understand existing tests before changing behavior.

Implementation:
- Prefer the smallest coherent change.
- Preserve SourceConnector, provider and repository abstractions.
- Avoid source-specific coupling in domain logic.
- Preserve provenance and evidence semantics.
- Do not weaken validation to make tests pass.
- Do not silently replace deterministic behavior with LLM behavior.
- Keep external services behind interfaces.

Verification:
- Run the relevant tests.
- Run configured linting and type checks.
- Inspect the final diff.
- Report tests actually run and any tests not run.
- Never claim success based only on generated code.

Interrupted pipeline runs:
- Killing an automated-discovery process (SIGTERM) leaves its pipeline_runs row
  RUNNING; queries trusting only COMPLETED/FAILED runs then silently hide valid
  observations. After any aborted run, mark it FAILED with a reason
  (repository.fail_pipeline_run) before aggregating or clustering.
- Provider failover (codex_cli -> claude_cli -> openai_compatible): the
  inference cache is keyed per provider identity, so a new provider only fills
  gaps and never re-bills completed items. Keep provider attribution visible
  per item via model_runs.

Delegation:
- Codex, Claude Code and Antigravity may implement bounded tasks.
- Give delegated agents explicit acceptance criteria.
- Always inspect delegated output and run repository tests afterward.

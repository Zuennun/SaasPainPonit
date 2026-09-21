---
name: pi-efficiency
description: Token- and cost-efficient execution for PI workflows.
---

# PI Efficiency

Use this skill for planning, orchestration, research, development, review and multi-agent work in Global Problem Intelligence.

The goal is not minimum token usage at any cost. The goal is maximum useful progress per model call, token and worker.

## Core principle

Use the cheapest and smallest amount of computation that can reliably complete the task.
Escalate model strength, reasoning effort, context size and number of workers only when the task justifies it.

## Context discipline

Before requesting more context:
- Use information already available in the current task.
- Read AGENTS.md and only the relevant project skill.
- Search for the relevant file, symbol, ADR or heading before opening large files.
- Read only the necessary files or sections.
- Do not repeatedly re-read unchanged material.
- Do not load unrelated skills or documentation.
- Do not restate large project briefs inside every subtask.

Stable project knowledge belongs in:
- AGENTS.md
- project skills
- docs/
- ADRs

It should not be copied into every prompt.

## Agent discipline

Do not spawn multiple agents merely because they are available.

Default:
- one owner for a task;
- one independent reviewer when justified;
- parallel workers only for genuinely independent work.

Do not ask Codex, Claude and Antigravity to solve the same routine task.

Use multiple coding agents only when:
- competing approaches are valuable;
- the first implementation is uncertain;
- a high-risk change needs independent validation;
- the user explicitly requests comparison.

Delegated tasks must be bounded. Give a worker:
- objective;
- relevant repository path;
- relevant skills;
- acceptance criteria;
- constraints;
- expected output.

Do not forward an entire long conversation when the worker only needs a small task briefing.

Worker output should return:
- result;
- changed files or evidence inspected;
- verification performed;
- remaining uncertainty.

## Reasoning discipline

Use low reasoning for:
- routing;
- status checks;
- formatting;
- simple Git operations;
- straightforward lookups;
- mechanical transformations.

Use medium reasoning for:
- ordinary development;
- research synthesis;
- architecture inspection;
- debugging.

Use high reasoning selectively for:
- difficult architecture decisions;
- ambiguous evidence;
- high-risk refactors;
- final independent review.

Do not use high reasoning continuously as a default.

## Model discipline

Prefer the currently selected model when it is adequate.
Avoid frequent model switching inside a long session because it may invalidate provider prompt-cache reuse.

Use another model when:
- the current model lacks the required capability;
- a task needs an intentionally independent reviewer;
- the current provider is rate-limited or unavailable;
- a cheaper auxiliary model is sufficient for a mechanical side task.

Do not repeatedly retry a rate-limited provider.

## Research discipline

Research narrowly before researching broadly.
Start with the concrete question and retrieve supporting evidence. Expand only when evidence is insufficient.

Do not:
- collect sources merely to increase source count;
- summarize the same evidence repeatedly;
- run broad searches when repository evidence already answers the question;
- use an LLM to calculate or transform data that deterministic code can handle.

For large datasets:
- filter deterministically first;
- deduplicate before LLM processing;
- batch when appropriate;
- send only relevant fields to the model.

## Development discipline

Inspect before editing.

Prefer: search → targeted read → plan → edit → targeted tests → final verification

Avoid: read entire repo → speculate → large rewrite → repeated full test suite

Run the smallest relevant test set during iteration. Run broader verification at the appropriate completion boundary.

Do not call external coding agents for trivial edits.

## Review discipline

Review at meaningful stage boundaries rather than after every tiny operation.

A reviewer should inspect the actual artifact, diff, evidence or test output. Do not spend another full-model pass merely to paraphrase the first agent.

## Goal and Kanban discipline

Tasks must have explicit acceptance criteria.
Break very large tasks into bounded stages before consuming dozens of turns.
Do not allow an agent to loop indefinitely.

If progress stalls:
- identify the blocker;
- stop repeated attempts;
- report the blocker;
- change strategy, provider or task decomposition only when justified.

## Output discipline

Internal worker reports should be concise and structured.
Prefer references to files, commits, task IDs and evidence IDs over copying their complete contents.
Do not repeat information already recorded in repository documentation.
The orchestrator should synthesize worker outputs rather than concatenate them.

## Verification

Before expensive additional work, ask:
- Do we already know this?
- Can deterministic code do this?
- Does another agent add independent value?
- Does this require the whole file or only part of it?
- Does this require high reasoning?
- Does this require a model call at all?
- Is this result needed for the current acceptance criteria?

If not, skip the work.

---
name: pi-core
description: Core product principles and non-negotiable rules for the Global Problem Intelligence project. Load for planning, development, research, review, architecture, or product decisions.
---

# Global Problem Intelligence — Core Rules

This repository builds Global Problem Intelligence for DACH founders.

Before substantial work:
1. Read the relevant AGENTS.md.
2. Inspect the existing implementation and relevant docs/ADRs.
3. Preserve existing architecture unless there is evidence for changing it.
4. Distinguish facts, evidence, inference, and recommendations.

Non-negotiable product rules:

- Every factual problem claim must trace back to real source evidence.
- Never fabricate willingness-to-pay, demand signals, source evidence, recurrence, or user quotes.
- Do not invent an arbitrary 0-100 opportunity score.
- A strong single precise observation may remain visible.
- Evidence maturity may include:
  SINGLE_SIGNAL, EMERGING, RECURRING, MULTI_SOURCE, CROSS_MARKET.
- An opportunity means "worth investigating", not "build this".
- Counter-evidence and unknowns are first-class information.
- Keep Global Evidence separate from DACH Evidence.
- Preserve source provenance through every processing stage.
- Competition includes software, legacy tools, manual processes, employees,
  freelancers/agencies, spreadsheets, scripts and internal tooling.
- Reddit or any other source must never define the core architecture.
- Source-specific code belongs behind generic provider/connector interfaces.

When instructions conflict with repository ADRs or explicit current user decisions,
surface the conflict before silently changing product semantics.

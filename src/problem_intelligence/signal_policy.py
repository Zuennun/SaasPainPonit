"""Shared, transparent policy for unusually strong individual observations."""

from __future__ import annotations


def is_strong_individual_signal(
    *,
    allowed_problem_type: bool,
    has_actor: bool,
    has_job: bool,
    has_context: bool,
    has_workaround: bool,
    has_quantified_impact: bool,
    has_payment: bool,
    active_search: bool,
    switching_intent: bool,
) -> bool:
    """Apply the high-precision single-signal admission rule."""

    return (
        allowed_problem_type
        and has_actor
        and has_job
        and (has_context or has_workaround)
        and (has_quantified_impact or has_payment or active_search or switching_intent)
    )


def strong_individual_signal_sql(alias: str) -> str:
    """Return the equivalent SQLite predicate for one trusted query alias."""

    if not alias.isidentifier():
        raise ValueError("SQL alias must be an identifier")
    return f"""(
        {alias}.problem_type NOT IN ('TEMPORARY_INCIDENT','SUPPORT_QUESTION','USER_ERROR')
        AND ({alias}.actor IS NOT NULL OR {alias}.actor_role IS NOT NULL)
        AND {alias}.job_to_be_done IS NOT NULL
        AND (
            {alias}.context IS NOT NULL
            OR {alias}.current_workaround IS NOT NULL
            OR EXISTS (
                SELECT 1 FROM workarounds w WHERE w.observation_id = {alias}.id
            )
        )
        AND (
            {alias}.active_solution_search = 1
            OR {alias}.switching_intent = 1
            OR EXISTS (
                SELECT 1 FROM impact_signals i
                WHERE i.observation_id = {alias}.id AND i.quantified = 1
            )
            OR {alias}.existing_spend IS NOT NULL
            OR {alias}.paid_workaround IS NOT NULL
            OR EXISTS (
                SELECT 1 FROM payment_signals p WHERE p.observation_id = {alias}.id
            )
        )
    )"""

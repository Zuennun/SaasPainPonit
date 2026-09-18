"""Transactional persistence with evidence-integrity checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from .domain import (
    OBSERVATION_FIELDS,
    ActorEquivalence,
    AudienceType,
    CaseStakeholder,
    ClaimKind,
    Competitor,
    CompetitorComplaint,
    CompetitorEvidenceRole,
    ContentCompleteness,
    CounterEvidenceItem,
    CounterEvidenceType,
    DachAssessment,
    DachTransferType,
    DiscoveryState,
    EvidenceCitation,
    EvidenceRange,
    EvidenceScope,
    EvidenceScopeSummary,
    EvidenceState,
    ImpactSignalDraft,
    ImpactType,
    LocalEvidenceState,
    ModelRunRecord,
    ModelRunStatus,
    ObservationRecord,
    OpportunityClaimRole,
    OpportunityRecord,
    OpportunityStatus,
    OpportunityType,
    PaymentEvidenceType,
    PaymentSignalDraft,
    PipelineStage,
    PipelineStatus,
    ProblemFamily,
    ProblemProfile,
    ProblemType,
    RequirementFinding,
    RequirementProgress,
    RequirementStatus,
    ResearchCaseReportData,
    ResearchCaseStatus,
    ResearchCaseSummary,
    ResearchOutcome,
    ResearchRequirement,
    SavedOpportunity,
    SolutionType,
    SourceAvailability,
    SourceItemRecord,
    SourceLifecycle,
    SourceScanCandidate,
    StakeholderKnowledge,
    StakeholderRole,
    ValidationQuestion,
    WorkaroundSignalDraft,
    WorkaroundType,
    WorkflowEquivalence,
    validate_observation_fields,
)
from .normalization import normalize_identifier, normalize_url


class IntegrityError(ValueError):
    """Raised when a write would weaken evidence integrity."""


SCHEMA_VERSION = 21


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    value = cursor.lastrowid
    if value is None:
        raise IntegrityError("database did not return an inserted row id")
    return value


def _decode_string_list(payload: str, column: str) -> tuple[str, ...]:
    values: Any = json.loads(payload)
    if not isinstance(values, list):
        raise IntegrityError(f"invalid string list stored in {column}")
    objects = cast(list[object], values)
    if not all(isinstance(value, str) for value in objects):
        raise IntegrityError(f"invalid string list stored in {column}")
    return tuple(cast(list[str], objects))


def _validate_dach_evidence_counts(
    *,
    local_evidence_state: LocalEvidenceState,
    dach_observation_count: int,
    dach_unique_author_count: int,
    dach_source_count: int,
) -> None:
    """Mirror the dach_assessments CHECK constraint with a locating error message."""

    minimums = {
        LocalEvidenceState.NONE_FOUND: (0, 0, 0),
        LocalEvidenceState.SINGLE_LOCAL_SIGNAL: (1, 1, 1),
        LocalEvidenceState.MULTIPLE_LOCAL_SIGNALS: (2, 1, 1),
        LocalEvidenceState.MULTI_SOURCE_LOCAL_SIGNALS: (2, 1, 2),
    }[local_evidence_state]
    min_observations, min_authors, min_sources = minimums
    exact = local_evidence_state is LocalEvidenceState.NONE_FOUND
    counts_are_valid = (
        (
            dach_observation_count == 0
            and dach_unique_author_count == 0
            and dach_source_count == 0
        )
        if exact
        else (
            dach_observation_count >= min_observations
            and dach_unique_author_count >= min_authors
            and dach_source_count >= min_sources
        )
    )
    if not counts_are_valid:
        raise IntegrityError(
            f"local_evidence_state {local_evidence_state.value!r} is inconsistent with "
            f"dach_observation_count={dach_observation_count}, "
            f"dach_unique_author_count={dach_unique_author_count}, "
            f"dach_source_count={dach_source_count}"
        )


def _format_impact_signal(row: sqlite3.Row) -> str:
    label = str(row["impact_type"])
    if not bool(row["quantified"]):
        return f"{label}: qualitative impact recorded"
    measurement = f"{row['value']} {row['unit']}"
    if row["frequency"] is not None:
        measurement += f" ({row['frequency']})"
    return f"{label}: {measurement}"


def _format_payment_signal(row: sqlite3.Row) -> str:
    label = str(row["payment_type"])
    if row["amount"] is None:
        measurement = "amount unknown"
    else:
        measurement = f"{row['amount']} {row['currency']}"
    if row["frequency"] is not None:
        measurement += f" ({row['frequency']})"
    return f"{label}: {measurement}"


def _unicode_casefold(value: object) -> str:
    return str(value).casefold() if value is not None else ""


class Repository:
    def __init__(self, database: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(database))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.create_function(
            "unicode_casefold",
            1,
            _unicode_casefold,
            deterministic=True,
        )

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        current_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise IntegrityError(
                f"database schema version {current_version} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if current_version < 13:
            self.connection.execute("DROP TRIGGER IF EXISTS research_case_completion_guard")
            self.connection.execute("DROP TRIGGER IF EXISTS research_case_transition_guard")
            has_research_cases = self.connection.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type = 'table' AND name = 'research_cases'"""
            ).fetchone()
            if has_research_cases is not None:
                # Completion gates have become stricter over time. Existing
                # COMPLETE cases must be reviewed against the current contract.
                self.connection.execute(
                    "UPDATE research_cases SET status = 'REVIEW' WHERE status = 'COMPLETE'"
                )
            self.connection.commit()
        if current_version < 14:
            self.connection.execute("DROP TRIGGER IF EXISTS research_requirement_keeps_fact")
            self.connection.commit()
        schema = files("problem_intelligence").joinpath("schema.sql").read_text(encoding="utf-8")
        self.connection.executescript(schema)
        if current_version < 5:
            columns = {
                str(row["name"])
                for row in self.connection.execute(
                    "PRAGMA table_info(source_registry_profiles)"
                ).fetchall()
            }
            if "scan_directive" not in columns:
                self.connection.execute(
                    "ALTER TABLE source_registry_profiles ADD COLUMN scan_directive TEXT"
                )
                self.connection.commit()
        if current_version < 7:
            observation_columns = {
                str(row["name"])
                for row in self.connection.execute(
                    "PRAGMA table_info(problem_observations)"
                ).fetchall()
            }
            if "problem_family" not in observation_columns:
                self.connection.execute(
                    """ALTER TABLE problem_observations ADD COLUMN problem_family TEXT
                       CHECK (problem_family IN (
                           'MANUAL_DATA_ENTRY','RECONCILIATION','INTEGRATION',
                           'DOCUMENT_COLLECTION','REPORTING','SCHEDULING','APPROVAL',
                           'COMMUNICATION','MIGRATION','COMPLIANCE','HANDOVER',
                           'ERROR_CORRECTION','SEARCH_RETRIEVAL','MONITORING',
                           'PROCUREMENT','PAYMENTS','INVENTORY','CUSTOMER_MANAGEMENT',
                           'WORKFORCE','OTHER'
                       ) OR problem_family IS NULL)"""
                )
            if "ontology_version" not in observation_columns:
                self.connection.execute(
                    "ALTER TABLE problem_observations ADD COLUMN ontology_version TEXT"
                )
            self.connection.commit()
        if current_version < 9:
            with self.connection:
                for requirement in ResearchRequirement:
                    self.connection.execute(
                        """INSERT OR IGNORE INTO research_passes (case_id, pass_type)
                           SELECT id, ? FROM research_cases""",
                        (requirement.value,),
                    )
                self.connection.execute(
                    """UPDATE research_passes
                       SET status = 'SATISFIED', outcome = 'EVIDENCE_FOUND',
                           summary_claim_id = (
                               SELECT rr.satisfied_by_claim_id
                               FROM research_requirements rr
                               WHERE rr.case_id = research_passes.case_id
                                 AND rr.requirement_type = research_passes.pass_type
                           ),
                           note = (
                               SELECT rr.note FROM research_requirements rr
                               WHERE rr.case_id = research_passes.case_id
                                 AND rr.requirement_type = research_passes.pass_type
                           )
                       WHERE EXISTS (
                           SELECT 1 FROM research_requirements rr
                           WHERE rr.case_id = research_passes.case_id
                             AND rr.requirement_type = research_passes.pass_type
                             AND rr.status = 'SATISFIED'
                       )
                         AND (
                             (research_passes.pass_type = 'COMPETITION' AND EXISTS (
                                 SELECT 1 FROM competitors
                                 WHERE competitors.case_id = research_passes.case_id
                             ))
                             OR (research_passes.pass_type = 'COUNTER_EVIDENCE' AND EXISTS (
                                 SELECT 1 FROM counter_evidence
                                 WHERE counter_evidence.case_id = research_passes.case_id
                             ))
                             OR research_passes.pass_type NOT IN (
                                 'COMPETITION', 'COUNTER_EVIDENCE'
                             )
                         )"""
                )
        if current_version < 12:
            with self.connection:
                self.connection.execute(
                    """UPDATE research_passes
                       SET status = 'PENDING', outcome = NULL,
                           summary_claim_id = NULL,
                           note = 'Schema v12 requires a structured competitor inventory.',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE pass_type = 'COMPETITION'
                         AND status = 'SATISFIED'
                         AND outcome = 'EVIDENCE_FOUND'
                         AND NOT EXISTS (
                             SELECT 1 FROM competitors
                             WHERE competitors.case_id = research_passes.case_id
                         )"""
                )
        if current_version < 13:
            with self.connection:
                self.connection.execute(
                    """UPDATE research_passes
                       SET status = 'PENDING', outcome = NULL,
                           summary_claim_id = NULL,
                           note = 'Schema v13 requires structured counter-evidence.',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE pass_type = 'COUNTER_EVIDENCE'
                         AND status = 'SATISFIED'
                         AND outcome = 'EVIDENCE_FOUND'
                         AND NOT EXISTS (
                             SELECT 1 FROM counter_evidence
                             WHERE counter_evidence.case_id = research_passes.case_id
                         )"""
                )
        if current_version < 15:
            source_columns = {
                str(row["name"])
                for row in self.connection.execute("PRAGMA table_info(sources)").fetchall()
            }
            policy_columns = (
                "quoting_rules",
                "deletion_requirements",
                "rate_limit_notes",
                "rights_reviewed_at",
            )
            with self.connection:
                for column in policy_columns:
                    if column not in source_columns:
                        self.connection.execute(
                            f"ALTER TABLE sources ADD COLUMN {column} TEXT"
                        )
        if current_version < 17:
            with self.connection:
                self.connection.execute(
                    """UPDATE sources SET commercial_use_status = 'REVIEW_REQUIRED'
                       WHERE lower(replace(commercial_use_status, '_', '-')) =
                             'requires-review'"""
                )

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            with self.connection:
                yield self.connection
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def upsert_source(
        self,
        *,
        source_type: str,
        name: str,
        lifecycle: SourceLifecycle | None = None,
        access_method: str | None = None,
        commercial_use_status: str | None = None,
        retention_rules: str | None = None,
        attribution_requirements: str | None = None,
        quoting_rules: str | None = None,
        deletion_requirements: str | None = None,
        rate_limit_notes: str | None = None,
        rights_reviewed_at: str | None = None,
    ) -> int:
        key = f"{normalize_identifier(source_type)}:{normalize_identifier(name)}"
        initial_lifecycle = lifecycle or SourceLifecycle.CANDIDATE
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    source_type, name, normalized_key, lifecycle, access_method,
                    commercial_use_status, retention_rules, attribution_requirements,
                    quoting_rules, deletion_requirements, rate_limit_notes,
                    rights_reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_key) DO UPDATE SET
                    name = excluded.name,
                    lifecycle = COALESCE(?, sources.lifecycle),
                    access_method = COALESCE(excluded.access_method, sources.access_method),
                    commercial_use_status = COALESCE(
                        excluded.commercial_use_status, sources.commercial_use_status
                    ),
                    retention_rules = COALESCE(excluded.retention_rules, sources.retention_rules),
                    attribution_requirements = COALESCE(
                        excluded.attribution_requirements, sources.attribution_requirements
                    ),
                    quoting_rules = COALESCE(excluded.quoting_rules, sources.quoting_rules),
                    deletion_requirements = COALESCE(
                        excluded.deletion_requirements, sources.deletion_requirements
                    ),
                    rate_limit_notes = COALESCE(
                        excluded.rate_limit_notes, sources.rate_limit_notes
                    ),
                    rights_reviewed_at = COALESCE(
                        excluded.rights_reviewed_at, sources.rights_reviewed_at
                    ),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source_type,
                    name,
                    key,
                    initial_lifecycle.value,
                    access_method,
                    commercial_use_status,
                    retention_rules,
                    attribution_requirements,
                    quoting_rules,
                    deletion_requirements,
                    rate_limit_notes,
                    rights_reviewed_at,
                    lifecycle.value if lifecycle is not None else None,
                ),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE normalized_key = ?", (key,)
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def set_source_lifecycle(self, source_id: int, lifecycle: SourceLifecycle) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE sources SET lifecycle = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (lifecycle.value, source_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("source does not exist")

    def ensure_source_access_defaults(
        self,
        source_id: int,
        *,
        access_method: str,
        commercial_use_status: str,
    ) -> None:
        """Fill unresolved access policy without replacing reviewed decisions."""

        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE sources
                   SET access_method = COALESCE(access_method, ?),
                       commercial_use_status = CASE
                           WHEN commercial_use_status IS NULL THEN ?
                           WHEN UPPER(REPLACE(commercial_use_status, '-', '_')) =
                                'REQUIRES_REVIEW' THEN ?
                           ELSE commercial_use_status
                       END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    access_method,
                    commercial_use_status,
                    commercial_use_status,
                    source_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("source does not exist")

    def set_source_registry_metadata(
        self, source_id: int, *, namespace: str, metadata: dict[str, Any]
    ) -> None:
        if not namespace.strip():
            raise ValueError("metadata namespace must not be empty")
        payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO source_registry_metadata (source_id, namespace, metadata_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(source_id, namespace) DO UPDATE SET
                       metadata_json = excluded.metadata_json,
                       updated_at = CURRENT_TIMESTAMP""",
                (source_id, namespace, payload),
            )

    def upsert_source_registry_profile(
        self,
        source_id: int,
        *,
        platform: str,
        canonical_url: str | None,
        external_id: str | None,
        primary_industry: str | None,
        professions: Sequence[str],
        audience_type: AudienceType,
        audience_segments: Sequence[str],
        curation_decision: str | None = None,
        curation_priority: str | None = None,
        research_role: str | None = None,
        scan_directive: str | None = None,
        scan_now: bool | None = None,
        recommended_action: str | None = None,
        strict_relevance: str | None = None,
        activity_status: str | None = None,
        activity_confidence: str | None = None,
        activity_basis: str | None = None,
        dach_transfer: str | None = None,
        sensitive_data_risk: str | None = None,
        research_angle: str | None = None,
        rationale: str | None = None,
        pilot_posts: int | None = None,
        strict_pilot_posts: int | None = None,
        registry_verified_at: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Store curated registry fields separately from untrusted legacy metadata."""

        if not platform.strip():
            raise ValueError("registry platform must not be empty")
        if pilot_posts is not None and pilot_posts < 0:
            raise ValueError("pilot_posts must not be negative")
        if strict_pilot_posts is not None and strict_pilot_posts < 0:
            raise ValueError("strict_pilot_posts must not be negative")

        def encode(values: Sequence[str]) -> str:
            cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
            return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO source_registry_profiles (
                       source_id, platform, canonical_url, external_id, primary_industry,
                       professions_json, audience_type, audience_segments_json,
                       curation_decision, curation_priority, research_role,
                       scan_directive, scan_now,
                       recommended_action, strict_relevance, activity_status,
                       activity_confidence, activity_basis, dach_transfer,
                       sensitive_data_risk, research_angle, rationale, pilot_posts,
                       strict_pilot_posts, registry_verified_at, notes
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )
                   ON CONFLICT(source_id) DO UPDATE SET
                       platform = excluded.platform,
                       canonical_url = COALESCE(
                           excluded.canonical_url, source_registry_profiles.canonical_url
                       ),
                       external_id = COALESCE(
                           excluded.external_id, source_registry_profiles.external_id
                       ),
                       primary_industry = COALESCE(
                           excluded.primary_industry, source_registry_profiles.primary_industry
                       ),
                       professions_json = COALESCE(
                           NULLIF(excluded.professions_json, '[]'),
                           source_registry_profiles.professions_json
                       ),
                       audience_type = excluded.audience_type,
                       audience_segments_json = COALESCE(
                           NULLIF(excluded.audience_segments_json, '[]'),
                           source_registry_profiles.audience_segments_json
                       ),
                       curation_decision = COALESCE(
                           excluded.curation_decision, source_registry_profiles.curation_decision
                       ),
                       curation_priority = COALESCE(
                           excluded.curation_priority, source_registry_profiles.curation_priority
                       ),
                       research_role = COALESCE(
                           excluded.research_role, source_registry_profiles.research_role
                       ),
                       scan_directive = COALESCE(
                           excluded.scan_directive, source_registry_profiles.scan_directive
                       ),
                       scan_now = COALESCE(excluded.scan_now, source_registry_profiles.scan_now),
                       recommended_action = COALESCE(
                           excluded.recommended_action,
                           source_registry_profiles.recommended_action
                       ),
                       strict_relevance = COALESCE(
                           excluded.strict_relevance, source_registry_profiles.strict_relevance
                       ),
                       activity_status = COALESCE(
                           excluded.activity_status, source_registry_profiles.activity_status
                       ),
                       activity_confidence = COALESCE(
                           excluded.activity_confidence,
                           source_registry_profiles.activity_confidence
                       ),
                       activity_basis = COALESCE(
                           excluded.activity_basis, source_registry_profiles.activity_basis
                       ),
                       dach_transfer = COALESCE(
                           excluded.dach_transfer, source_registry_profiles.dach_transfer
                       ),
                       sensitive_data_risk = COALESCE(
                           excluded.sensitive_data_risk,
                           source_registry_profiles.sensitive_data_risk
                       ),
                       research_angle = COALESCE(
                           excluded.research_angle, source_registry_profiles.research_angle
                       ),
                       rationale = COALESCE(
                           excluded.rationale, source_registry_profiles.rationale
                       ),
                       pilot_posts = COALESCE(
                           excluded.pilot_posts, source_registry_profiles.pilot_posts
                       ),
                       strict_pilot_posts = COALESCE(
                           excluded.strict_pilot_posts,
                           source_registry_profiles.strict_pilot_posts
                       ),
                       registry_verified_at = COALESCE(
                           excluded.registry_verified_at,
                           source_registry_profiles.registry_verified_at
                       ),
                       notes = COALESCE(excluded.notes, source_registry_profiles.notes),
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    source_id,
                    platform.strip().upper(),
                    normalize_url(canonical_url),
                    external_id,
                    primary_industry,
                    encode(professions),
                    audience_type.value,
                    encode(audience_segments),
                    curation_decision,
                    curation_priority,
                    research_role,
                    scan_directive,
                    None if scan_now is None else int(scan_now),
                    recommended_action,
                    strict_relevance,
                    activity_status,
                    activity_confidence,
                    activity_basis,
                    dach_transfer,
                    sensitive_data_risk,
                    research_angle,
                    rationale,
                    pilot_posts,
                    strict_pilot_posts,
                    registry_verified_at,
                    notes,
                ),
            )

    def source_scan_candidates(
        self,
        *,
        priorities: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> tuple[SourceScanCandidate, ...]:
        """Return curated immediate-scan candidates without bypassing policy status."""

        if limit is not None and limit <= 0:
            raise ValueError("scan plan limit must be positive")
        normalized_priorities = tuple(
            dict.fromkeys(value.strip().upper() for value in priorities or () if value.strip())
        )
        conditions = ["p.scan_now = 1", "s.lifecycle <> 'EXCLUDED'"]
        parameters: list[Any] = []
        if normalized_priorities:
            placeholders = ", ".join("?" for _ in normalized_priorities)
            conditions.append(f"p.curation_priority IN ({placeholders})")
            parameters.extend(normalized_priorities)
        sql = f"""SELECT s.id, s.name, s.commercial_use_status,
                          p.primary_industry, p.audience_type, p.curation_priority,
                          p.research_role, p.scan_directive, p.recommended_action,
                          COALESCE(p.strict_pilot_posts, p.pilot_posts) AS pilot_posts
                   FROM source_registry_profiles AS p
                   JOIN sources AS s ON s.id = p.source_id
                   WHERE {' AND '.join(conditions)}
                   ORDER BY CASE p.curation_priority
                                WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2
                                WHEN 'C' THEN 3 WHEN 'R' THEN 4 WHEN 'X' THEN 5 ELSE 6
                            END,
                            p.primary_industry, s.name COLLATE NOCASE, s.id"""
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(sql, parameters).fetchall()
        return tuple(
            SourceScanCandidate(
                source_id=int(row["id"]),
                name=str(row["name"]),
                primary_industry=row["primary_industry"],
                audience_type=AudienceType(row["audience_type"]),
                curation_priority=row["curation_priority"],
                research_role=row["research_role"],
                scan_directive=str(row["scan_directive"]),
                recommended_action=row["recommended_action"],
                pilot_posts=(int(row["pilot_posts"]) if row["pilot_posts"] is not None else None),
                commercial_use_status=row["commercial_use_status"],
                production_ready=row["commercial_use_status"] == "APPROVED",
            )
            for row in rows
        )

    def record_discovery_response(
        self,
        *,
        source_id: int,
        provider: str,
        query: str,
        availability: SourceAvailability,
        results: Sequence[Any],
        capabilities: dict[str, Any],
        latency_ms: int | None,
        cost_usd: float | None,
        error: str | None,
    ) -> str:
        """Persist one provider request and all recognizable Reddit results atomically."""

        from .reddit import canonicalize_reddit_url

        run_id = str(uuid.uuid4())
        recognized: list[tuple[Any, Any]] = []
        for result in results:
            identity = canonicalize_reddit_url(str(result.url))
            if identity is not None:
                recognized.append((result, identity))
        capabilities_json = json.dumps(capabilities, sort_keys=True, separators=(",", ":"))
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO discovery_runs (
                       id, source_id, provider, query, availability, search_requests,
                       results_returned, reddit_urls_discovered, latency_ms, cost_usd,
                       error, provider_capabilities_json
                   ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    source_id,
                    provider,
                    query,
                    availability.value,
                    len(results),
                    len(recognized),
                    latency_ms,
                    cost_usd,
                    error,
                    capabilities_json,
                ),
            )
            for result, identity in recognized:
                connection.execute(
                    """INSERT OR IGNORE INTO discovery_records (
                           run_id, source_id, provider, query, url, canonical_url,
                           submission_id, comment_id, title, snippet, state
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DISCOVERED')""",
                    (
                        run_id,
                        source_id,
                        provider,
                        query,
                        result.url,
                        identity.canonical_url,
                        identity.submission_id,
                        identity.comment_id,
                        result.title,
                        result.snippet,
                    ),
                )
        return run_id

    def pending_discoveries(self, acquisition_provider: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self.connection.execute(
                """SELECT d.* FROM discovery_records AS d
                   WHERE NOT EXISTS (
                       SELECT 1 FROM acquisition_records AS a
                       WHERE a.discovery_id = d.id AND a.provider = ?
                   )
                   ORDER BY d.id""",
                (acquisition_provider,),
            ).fetchall()
        )

    def record_acquisition(
        self,
        *,
        discovery_id: int,
        source_item_id: int | None,
        provider: str,
        state: DiscoveryState,
        completeness: ContentCompleteness | None,
        latency_ms: int | None,
        cost_usd: float | None,
        error: str | None,
        metadata: dict[str, Any],
    ) -> int:
        payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO acquisition_records (
                       discovery_id, source_item_id, provider, state, completeness,
                       latency_ms, cost_usd, error, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(discovery_id, provider) DO UPDATE SET
                       source_item_id = COALESCE(
                           excluded.source_item_id, acquisition_records.source_item_id
                       ),
                       state = excluded.state,
                       completeness = COALESCE(
                           excluded.completeness, acquisition_records.completeness
                       ),
                       latency_ms = excluded.latency_ms,
                       cost_usd = excluded.cost_usd,
                       error = excluded.error,
                       metadata_json = excluded.metadata_json,
                       acquired_at = CURRENT_TIMESTAMP
                   RETURNING id""",
                (
                    discovery_id,
                    source_item_id,
                    provider,
                    state.value,
                    completeness.value if completeness else None,
                    latency_ms,
                    cost_usd,
                    error,
                    payload,
                ),
            )
            connection.execute(
                "UPDATE discovery_records SET state = ? WHERE id = ?",
                (state.value, discovery_id),
            )
            row = cursor.fetchone()
        assert row is not None
        return int(row["id"])

    def extraction_eligible_source_item_ids(
        self, *, minimum_characters: int = 40
    ) -> tuple[int, ...]:
        """Exclude metadata-only and too-short captures from downstream extraction."""

        rows = self.connection.execute(
            """SELECT DISTINCT si.id
               FROM source_items AS si
               JOIN acquisition_records AS a ON a.source_item_id = si.id
               WHERE a.completeness IN ('FULL','PARTIAL') AND length(si.raw_text) >= ?
               ORDER BY si.id""",
            (minimum_characters,),
        ).fetchall()
        return tuple(int(row["id"]) for row in rows)

    def upsert_source_item(
        self,
        *,
        source_id: int,
        external_id: str,
        raw_text: str,
        url: str | None = None,
        title: str | None = None,
        author_external_id: str | None = None,
        published_at: str | None = None,
        country_code: str | None = None,
        language_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if not raw_text.strip():
            raise ValueError("source item text must not be empty")
        normalized_external_id = normalize_identifier(external_id)
        normalized_source_url = normalize_url(url)
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))

        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT id, raw_text FROM source_items
                   WHERE source_id = ? AND normalized_external_id = ?""",
                (source_id, normalized_external_id),
            ).fetchone()
            if existing is not None and existing["raw_text"] != raw_text:
                referenced = connection.execute(
                    "SELECT 1 FROM evidence_spans WHERE source_item_id = ? LIMIT 1",
                    (existing["id"],),
                ).fetchone()
                if referenced is not None:
                    raise IntegrityError(
                        "cannot change source text after evidence has been recorded"
                    )

            connection.execute(
                """
                INSERT INTO source_items (
                    source_id, external_id, normalized_external_id, url, title,
                    raw_text, author_external_id, published_at, country_code,
                    language_code, metadata_json, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, normalized_external_id) DO UPDATE SET
                    external_id = excluded.external_id,
                    url = excluded.url,
                    title = excluded.title,
                    raw_text = excluded.raw_text,
                    author_external_id = excluded.author_external_id,
                    published_at = excluded.published_at,
                    country_code = excluded.country_code,
                    language_code = excluded.language_code,
                    metadata_json = excluded.metadata_json,
                    content_hash = excluded.content_hash,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    source_id,
                    external_id,
                    normalized_external_id,
                    normalized_source_url,
                    title,
                    raw_text,
                    author_external_id,
                    published_at,
                    country_code,
                    language_code,
                    metadata_json,
                    content_hash,
                ),
            )
            row = connection.execute(
                """SELECT id FROM source_items
                   WHERE source_id = ? AND normalized_external_id = ?""",
                (source_id, normalized_external_id),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def create_observation(
        self,
        *,
        source_item_id: int,
        problem_type: ProblemType,
        evidence_scope: EvidenceScope,
        problem: str,
        extraction_version: str,
        fields: dict[str, Any] | None = None,
        problem_family: ProblemFamily | None = None,
        ontology_version: str | None = None,
    ) -> int:
        if not problem.strip():
            raise ValueError("problem must not be empty")
        supplied = fields or {}
        validate_observation_fields(supplied)
        columns = [
            "source_item_id", "problem_type", "problem_family", "ontology_version",
            "evidence_scope", "problem", "extraction_version",
            *supplied.keys(),
        ]
        values = [
            source_item_id,
            problem_type.value,
            problem_family.value if problem_family else None,
            ontology_version,
            evidence_scope.value,
            problem,
            extraction_version,
            *supplied.values(),
        ]
        placeholders = ", ".join("?" for _ in columns)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"INSERT INTO problem_observations ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        return _last_insert_id(cursor)

    def create_observation_with_evidence(
        self,
        *,
        source_item_id: int,
        problem_type: ProblemType,
        evidence_scope: EvidenceScope,
        problem: str,
        extraction_version: str,
        evidence_ranges: Sequence[EvidenceRange],
        fields: dict[str, Any] | None = None,
        pipeline_run_id: str | None = None,
        problem_family: ProblemFamily | None = None,
        ontology_version: str | None = None,
        workarounds: Sequence[WorkaroundSignalDraft] = (),
        impact_signals: Sequence[ImpactSignalDraft] = (),
        payment_signals: Sequence[PaymentSignalDraft] = (),
    ) -> tuple[int, tuple[int, ...]]:
        """Atomically store an extracted observation and all exact evidence spans."""

        if not evidence_ranges:
            raise IntegrityError("extracted observations require at least one evidence span")
        supplied = dict(fields or {})
        if "pipeline_run_id" in supplied:
            raise ValueError("pipeline_run_id must be passed explicitly")
        supplied["pipeline_run_id"] = pipeline_run_id

        row = self.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (source_item_id,)
        ).fetchone()
        if row is None:
            raise ValueError("source item does not exist")
        raw_text = str(row["raw_text"])
        excerpts = [evidence_range.excerpt_from(raw_text) for evidence_range in evidence_ranges]
        self._validate_signal_drafts(
            len(evidence_ranges), workarounds, impact_signals, payment_signals
        )

        if not problem.strip():
            raise ValueError("problem must not be empty")
        validate_observation_fields(supplied)
        columns = [
            "source_item_id",
            "problem_type",
            "problem_family",
            "ontology_version",
            "evidence_scope",
            "problem",
            "extraction_version",
            *supplied.keys(),
        ]
        values = [
            source_item_id,
            problem_type.value,
            problem_family.value if problem_family else None,
            ontology_version,
            evidence_scope.value,
            problem,
            extraction_version,
            *supplied.values(),
        ]
        placeholders = ", ".join("?" for _ in columns)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"INSERT INTO problem_observations ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            observation_id = _last_insert_id(cursor)
            evidence_ids: list[int] = []
            for evidence_range, excerpt in zip(evidence_ranges, excerpts, strict=True):
                evidence_cursor = connection.execute(
                    """INSERT INTO evidence_spans (
                           source_item_id, observation_id, start_offset, end_offset,
                           excerpt, evidence_scope
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        source_item_id,
                        observation_id,
                        evidence_range.start,
                        evidence_range.end,
                        excerpt,
                        evidence_scope.value,
                    ),
                )
                evidence_ids.append(_last_insert_id(evidence_cursor))
            self._insert_observation_signals(
                connection,
                observation_id=observation_id,
                evidence_ids=evidence_ids,
                workarounds=workarounds,
                impact_signals=impact_signals,
                payment_signals=payment_signals,
            )
        return observation_id, tuple(evidence_ids)

    def revise_observation_field(
        self,
        *,
        observation_id: int,
        field_name: str,
        value: Any,
        reason: str,
        evidence_span_id: int,
        revision_version: str,
    ) -> int:
        """Apply an evidence-backed reviewed correction and invalidate clustering.

        Corrections are blocked once a research case references the observation's
        cluster. This prevents a reviewed case from silently changing underneath
        its research artifacts.
        """

        revisable_fields = OBSERVATION_FIELDS - {"pipeline_run_id"}
        if field_name not in revisable_fields:
            raise ValueError(f"observation field is not revisable: {field_name}")
        validate_observation_fields({field_name: value})
        if not reason.strip():
            raise ValueError("revision reason must not be empty")
        if not revision_version.strip():
            raise ValueError("revision version must not be empty")

        observation = self.connection.execute(
            f"SELECT {field_name} AS value FROM problem_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        if observation is None:
            raise ValueError("observation does not exist")
        evidence = self.connection.execute(
            "SELECT observation_id FROM evidence_spans WHERE id = ?",
            (evidence_span_id,),
        ).fetchone()
        if evidence is None or evidence["observation_id"] != observation_id:
            raise IntegrityError("revision evidence must belong to the observation")
        existing_revision = self.connection.execute(
            """SELECT id, new_value_json FROM observation_revisions
               WHERE observation_id = ? AND field_name = ? AND revision_version = ?""",
            (observation_id, field_name, revision_version),
        ).fetchone()
        new_value_json = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if existing_revision is not None:
            if str(existing_revision["new_value_json"]) != new_value_json:
                raise IntegrityError("revision version already exists with another value")
            return int(existing_revision["id"])
        old_value = observation["value"]
        if field_name in {"active_solution_search", "switching_intent"}:
            old_value = bool(old_value) if old_value is not None else None
        if old_value == value:
            raise ValueError("revision must change the observation value")
        referenced_case = self.connection.execute(
            """SELECT rc.id FROM cluster_members cm
               JOIN research_cases rc ON rc.cluster_id = cm.cluster_id
               WHERE cm.observation_id = ? LIMIT 1""",
            (observation_id,),
        ).fetchone()
        if referenced_case is not None:
            raise IntegrityError(
                "cannot revise an observation after a research case references its cluster"
            )

        old_value_json = json.dumps(
            old_value, ensure_ascii=False, separators=(",", ":")
        )
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO observation_revisions (
                       observation_id, field_name, old_value_json, new_value_json,
                       reason, evidence_span_id, revision_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation_id,
                    field_name,
                    old_value_json,
                    new_value_json,
                    reason.strip(),
                    evidence_span_id,
                    revision_version.strip(),
                ),
            )
            connection.execute(
                f"UPDATE problem_observations SET {field_name} = ? WHERE id = ?",
                (value, observation_id),
            )
            connection.execute(
                "DELETE FROM cluster_members WHERE observation_id = ?", (observation_id,)
            )
            connection.execute(
                "DELETE FROM observation_fingerprints WHERE observation_id = ?",
                (observation_id,),
            )
            connection.execute(
                """DELETE FROM problem_clusters
                   WHERE NOT EXISTS (
                       SELECT 1 FROM cluster_members cm WHERE cm.cluster_id = problem_clusters.id
                   )
                     AND NOT EXISTS (
                       SELECT 1 FROM research_cases rc WHERE rc.cluster_id = problem_clusters.id
                   )"""
            )
        return _last_insert_id(cursor)

    @staticmethod
    def _validate_signal_drafts(
        evidence_count: int,
        workarounds: Sequence[WorkaroundSignalDraft],
        impact_signals: Sequence[ImpactSignalDraft],
        payment_signals: Sequence[PaymentSignalDraft],
    ) -> None:
        for signal in (*workarounds, *impact_signals, *payment_signals):
            if signal.evidence_index < 0 or signal.evidence_index >= evidence_count:
                raise ValueError("signal evidence_index is outside the observation evidence")
        for workaround in workarounds:
            if not workaround.description.strip():
                raise ValueError("workaround description must not be empty")
        for impact in impact_signals:
            if impact.quantified:
                if (
                    not impact.value
                    or not impact.value.strip()
                    or not impact.unit
                    or not impact.unit.strip()
                ):
                    raise ValueError("quantified impact requires value and unit")
            elif impact.value is not None or impact.unit is not None:
                raise ValueError("qualitative impact must not contain value or unit")
        for payment in payment_signals:
            if (payment.amount is None) != (payment.currency is None):
                raise ValueError("payment amount and currency must be supplied together")

    @staticmethod
    def _insert_observation_signals(
        connection: sqlite3.Connection,
        *,
        observation_id: int,
        evidence_ids: Sequence[int],
        workarounds: Sequence[WorkaroundSignalDraft],
        impact_signals: Sequence[ImpactSignalDraft],
        payment_signals: Sequence[PaymentSignalDraft],
    ) -> None:
        connection.executemany(
            """INSERT INTO workarounds (
                   observation_id, workaround_type, description, evidence_span_id
               ) VALUES (?, ?, ?, ?)""",
            (
                (
                    observation_id,
                    signal.workaround_type.value,
                    signal.description,
                    evidence_ids[signal.evidence_index],
                )
                for signal in workarounds
            ),
        )
        connection.executemany(
            """INSERT INTO impact_signals (
                   observation_id, impact_type, quantified, value, unit,
                   frequency, evidence_span_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    observation_id,
                    signal.impact_type.value,
                    int(signal.quantified),
                    signal.value,
                    signal.unit,
                    signal.frequency,
                    evidence_ids[signal.evidence_index],
                )
                for signal in impact_signals
            ),
        )
        connection.executemany(
            """INSERT INTO payment_signals (
                   observation_id, payment_type, amount, currency,
                   frequency, evidence_span_id
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (
                    observation_id,
                    signal.payment_type.value,
                    signal.amount,
                    signal.currency,
                    signal.frequency,
                    evidence_ids[signal.evidence_index],
                )
                for signal in payment_signals
            ),
        )

    def set_observation_problem_family(
        self,
        observation_id: int,
        *,
        problem_family: ProblemFamily,
        ontology_version: str,
    ) -> None:
        if not ontology_version.strip():
            raise ValueError("ontology version must not be empty")
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE problem_observations
                   SET problem_family = ?, ontology_version = ?
                   WHERE id = ?""",
                (problem_family.value, ontology_version, observation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("observation does not exist")

    def add_workaround_signal(
        self,
        *,
        observation_id: int,
        evidence_span_id: int,
        workaround_type: WorkaroundType,
        description: str,
    ) -> int:
        if not description.strip():
            raise ValueError("workaround description must not be empty")
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO workarounds (
                       observation_id, workaround_type, description, evidence_span_id
                   ) VALUES (?, ?, ?, ?)""",
                (observation_id, workaround_type.value, description, evidence_span_id),
            )
            row = connection.execute(
                """SELECT id FROM workarounds
                   WHERE observation_id = ? AND workaround_type = ?
                     AND description = ? AND evidence_span_id = ?""",
                (observation_id, workaround_type.value, description, evidence_span_id),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def add_impact_signal(
        self,
        *,
        observation_id: int,
        evidence_span_id: int,
        impact_type: ImpactType,
        quantified: bool,
        value: str | None = None,
        unit: str | None = None,
        frequency: str | None = None,
    ) -> int:
        self._validate_signal_drafts(
            1,
            (),
            (ImpactSignalDraft(impact_type, quantified, value, unit, frequency, 0),),
            (),
        )
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO impact_signals (
                       observation_id, impact_type, quantified, value, unit,
                       frequency, evidence_span_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation_id,
                    impact_type.value,
                    int(quantified),
                    value,
                    unit,
                    frequency,
                    evidence_span_id,
                ),
            )
            row = connection.execute(
                """SELECT id FROM impact_signals
                   WHERE observation_id = ? AND impact_type = ? AND quantified = ?
                     AND value IS ? AND unit IS ? AND frequency IS ?
                     AND evidence_span_id = ?""",
                (
                    observation_id,
                    impact_type.value,
                    int(quantified),
                    value,
                    unit,
                    frequency,
                    evidence_span_id,
                ),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def add_payment_signal(
        self,
        *,
        observation_id: int,
        evidence_span_id: int,
        payment_type: PaymentEvidenceType,
        amount: str | None = None,
        currency: str | None = None,
        frequency: str | None = None,
    ) -> int:
        self._validate_signal_drafts(
            1,
            (),
            (),
            (PaymentSignalDraft(payment_type, amount, currency, frequency, 0),),
        )
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO payment_signals (
                       observation_id, payment_type, amount, currency,
                       frequency, evidence_span_id
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    observation_id,
                    payment_type.value,
                    amount,
                    currency,
                    frequency,
                    evidence_span_id,
                ),
            )
            row = connection.execute(
                """SELECT id FROM payment_signals
                   WHERE observation_id = ? AND payment_type = ?
                     AND amount IS ? AND currency IS ? AND frequency IS ?
                     AND evidence_span_id = ?""",
                (
                    observation_id,
                    payment_type.value,
                    amount,
                    currency,
                    frequency,
                    evidence_span_id,
                ),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def source_items(
        self, source_item_ids: Sequence[int] | None = None
    ) -> tuple[SourceItemRecord, ...]:
        if source_item_ids is None:
            rows = self.connection.execute(
                """SELECT id, source_id, external_id, raw_text, country_code, language_code
                   FROM source_items ORDER BY id"""
            ).fetchall()
        elif not source_item_ids:
            return ()
        else:
            placeholders = ", ".join("?" for _ in source_item_ids)
            rows = self.connection.execute(
                f"""SELECT id, source_id, external_id, raw_text, country_code, language_code
                    FROM source_items WHERE id IN ({placeholders}) ORDER BY id""",
                tuple(source_item_ids),
            ).fetchall()
        return tuple(
            SourceItemRecord(
                id=int(row["id"]),
                source_id=int(row["source_id"]),
                external_id=str(row["external_id"]),
                raw_text=str(row["raw_text"]),
                country_code=row["country_code"],
                language_code=row["language_code"],
            )
            for row in rows
        )

    def start_pipeline_run(self, *, stage: PipelineStage, version: str, input_count: int) -> str:
        if not version.strip():
            raise ValueError("pipeline version must not be empty")
        if input_count < 0:
            raise ValueError("input count must not be negative")
        run_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO pipeline_runs (id, stage, version, status, input_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, stage.value, version, PipelineStatus.RUNNING.value, input_count),
            )
        return run_id

    def completed_pipeline_run(
        self, *, stage: PipelineStage, version: str, input_signature: str
    ) -> tuple[str, int, int] | None:
        row = self.connection.execute(
            """SELECT r.id, r.input_count, r.output_count
               FROM completed_pipeline_signatures AS s
               JOIN pipeline_runs AS r ON r.id = s.run_id
               WHERE s.stage = ? AND s.version = ? AND s.input_signature = ?
                 AND r.status = 'COMPLETED'""",
            (stage.value, version, input_signature),
        ).fetchone()
        if row is None:
            return None
        return str(row["id"]), int(row["input_count"]), int(row["output_count"])

    def finish_pipeline_run(
        self, run_id: str, *, output_count: int, input_signature: str
    ) -> None:
        if not input_signature:
            raise ValueError("input signature must not be empty")
        run = self.connection.execute(
            "SELECT stage, version FROM pipeline_runs WHERE id = ? AND status = 'RUNNING'",
            (run_id,),
        ).fetchone()
        if run is None:
            raise IntegrityError("pipeline run does not exist or is already finished")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO completed_pipeline_signatures (
                       run_id, stage, version, input_signature
                   ) VALUES (?, ?, ?, ?)""",
                (run_id, run["stage"], run["version"], input_signature),
            )
            cursor = connection.execute(
                """UPDATE pipeline_runs
                   SET status = 'COMPLETED', output_count = ?, error = NULL,
                       finished_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'RUNNING'""",
                (output_count, run_id),
            )
            if cursor.rowcount != 1:
                raise IntegrityError("pipeline run does not exist or is already finished")

    def fail_pipeline_run(self, run_id: str, *, output_count: int, error: str) -> None:
        self._finish_pipeline_run(run_id, PipelineStatus.FAILED, output_count, error)

    def _finish_pipeline_run(
        self, run_id: str, status: PipelineStatus, output_count: int, error: str | None
    ) -> None:
        if output_count < 0:
            raise ValueError("output count must not be negative")
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE pipeline_runs
                   SET status = ?, output_count = ?, error = ?, finished_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'RUNNING'""",
                (status.value, output_count, error, run_id),
            )
            if cursor.rowcount != 1:
                raise IntegrityError("pipeline run does not exist or is already finished")

    def record_model_run(
        self,
        *,
        operation_key: str,
        provider: str,
        model: str,
        pipeline_stage: str,
        template_version: str,
        status: ModelRunStatus,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        items_processed: int,
        pipeline_run_id: str | None = None,
        external_run_id: str | None = None,
        error: str | None = None,
        measured_cost: str | None = None,
        currency: str | None = None,
        cost_measurement_source: str | None = None,
    ) -> ModelRunRecord:
        """Record exact provider telemetry without estimating missing cost data."""

        required_text = {
            "operation_key": operation_key,
            "provider": provider,
            "model": model,
            "pipeline_stage": pipeline_stage,
            "template_version": template_version,
        }
        if any(not value.strip() for value in required_text.values()):
            raise ValueError("model run identity fields must not be empty")
        counts = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "items_processed": items_processed,
        }
        if any(isinstance(value, bool) or value < 0 for value in counts.values()):
            raise ValueError("model run measurements must be non-negative integers")
        clean_error = error.strip() if error and error.strip() else None
        if status is ModelRunStatus.FAILED and clean_error is None:
            raise ValueError("failed model runs require an error")
        if status is ModelRunStatus.COMPLETED and clean_error is not None:
            raise ValueError("completed model runs cannot contain an error")
        clean_external_id = (
            external_run_id.strip() if external_run_id and external_run_id.strip() else None
        )

        supplied_cost_fields = (
            measured_cost is not None,
            currency is not None,
            cost_measurement_source is not None,
        )
        if any(supplied_cost_fields) and not all(supplied_cost_fields):
            raise ValueError(
                "measured cost, currency, and measurement source must be supplied together"
            )
        normalized_cost: str | None = None
        clean_currency: str | None = None
        clean_cost_source: str | None = None
        if measured_cost is not None:
            try:
                amount = Decimal(measured_cost)
            except InvalidOperation as exc:
                raise ValueError("measured cost must be a decimal number") from exc
            if not amount.is_finite() or amount < 0:
                raise ValueError("measured cost must be finite and non-negative")
            normalized_cost = format(amount.normalize(), "f")
            if normalized_cost == "-0":
                normalized_cost = "0"
            assert currency is not None
            clean_currency = currency.strip().upper()
            if len(clean_currency) != 3 or not clean_currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            assert cost_measurement_source is not None
            clean_cost_source = cost_measurement_source.strip()
            if not clean_cost_source:
                raise ValueError("cost measurement source must not be empty")

        expected = (
            operation_key.strip(),
            provider.strip(),
            model.strip(),
            pipeline_stage.strip(),
            template_version.strip(),
            status.value,
            input_tokens,
            output_tokens,
            latency_ms,
            items_processed,
            pipeline_run_id,
            clean_external_id,
            clean_error,
            normalized_cost,
            clean_currency,
            clean_cost_source,
        )
        existing = self.connection.execute(
            """SELECT mr.*, ce.amount_decimal, ce.currency, ce.measurement_source
               FROM model_runs mr
               LEFT JOIN cost_events ce ON ce.model_run_id = mr.id
               WHERE mr.operation_key = ?""",
            (operation_key.strip(),),
        ).fetchone()
        if existing is not None:
            actual = (
                str(existing["operation_key"]),
                str(existing["provider"]),
                str(existing["model"]),
                str(existing["pipeline_stage"]),
                str(existing["template_version"]),
                str(existing["status"]),
                int(existing["input_tokens"]),
                int(existing["output_tokens"]),
                int(existing["latency_ms"]),
                int(existing["items_processed"]),
                existing["pipeline_run_id"],
                existing["external_run_id"],
                existing["error"],
                existing["amount_decimal"],
                existing["currency"],
                existing["measurement_source"],
            )
            if actual != expected:
                raise IntegrityError("operation key already records different model telemetry")
            return self.model_run(str(existing["id"]))

        model_run_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO model_runs (
                       id, operation_key, pipeline_run_id, provider, model,
                       pipeline_stage, template_version, external_run_id, status,
                       input_tokens, output_tokens, latency_ms, items_processed, error
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    model_run_id,
                    operation_key.strip(),
                    pipeline_run_id,
                    provider.strip(),
                    model.strip(),
                    pipeline_stage.strip(),
                    template_version.strip(),
                    clean_external_id,
                    status.value,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    items_processed,
                    clean_error,
                ),
            )
            if normalized_cost is not None:
                connection.execute(
                    """INSERT INTO cost_events (
                           model_run_id, amount_decimal, currency, measurement_source
                       ) VALUES (?, ?, ?, ?)""",
                    (
                        model_run_id,
                        normalized_cost,
                        clean_currency,
                        clean_cost_source,
                    ),
                )
        return self.model_run(model_run_id)

    def model_run(self, model_run_id: str) -> ModelRunRecord:
        row = self.connection.execute(
            """SELECT mr.*, ce.amount_decimal, ce.currency, ce.measurement_source
               FROM model_runs mr
               LEFT JOIN cost_events ce ON ce.model_run_id = mr.id
               WHERE mr.id = ?""",
            (model_run_id,),
        ).fetchone()
        if row is None:
            raise ValueError("model run does not exist")
        return ModelRunRecord(
            id=str(row["id"]),
            operation_key=str(row["operation_key"]),
            pipeline_run_id=row["pipeline_run_id"],
            provider=str(row["provider"]),
            model=str(row["model"]),
            pipeline_stage=str(row["pipeline_stage"]),
            template_version=str(row["template_version"]),
            external_run_id=row["external_run_id"],
            status=ModelRunStatus(row["status"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            latency_ms=int(row["latency_ms"]),
            items_processed=int(row["items_processed"]),
            error=row["error"],
            measured_cost=row["amount_decimal"],
            currency=row["currency"],
            cost_measurement_source=row["measurement_source"],
        )

    def clusterable_observations(self) -> tuple[ObservationRecord, ...]:
        """Return manual observations and outputs from completed extraction runs."""

        rows = self.connection.execute(
            """SELECT o.id, o.problem_type, o.problem_family, o.problem, o.actor,
                      o.job_to_be_done, o.context, o.root_cause,
                      o.current_workaround, o.tools_used
               FROM problem_observations AS o
               LEFT JOIN pipeline_runs AS r ON r.id = o.pipeline_run_id
               WHERE o.pipeline_run_id IS NULL OR r.status = 'COMPLETED'
               ORDER BY o.id"""
        ).fetchall()
        return tuple(
            ObservationRecord(
                id=int(row["id"]),
                problem_type=ProblemType(row["problem_type"]),
                problem_family=(
                    ProblemFamily(row["problem_family"])
                    if row["problem_family"] is not None
                    else None
                ),
                problem=str(row["problem"]),
                actor=row["actor"],
                job_to_be_done=row["job_to_be_done"],
                context=row["context"],
                root_cause=row["root_cause"],
                current_workaround=row["current_workaround"],
                tools_used=row["tools_used"],
            )
            for row in rows
        )

    def store_cluster_assignments(
        self,
        *,
        algorithm_version: str,
        assignments: dict[str, Sequence[int]],
    ) -> tuple[int, ...]:
        """Replace one version of derived fingerprints and cluster memberships."""

        if not algorithm_version.strip():
            raise ValueError("algorithm version must not be empty")
        cluster_ids: list[int] = []
        with self.transaction() as connection:
            connection.execute(
                """DELETE FROM cluster_members
                   WHERE cluster_id IN (
                       SELECT id FROM problem_clusters WHERE algorithm_version = ?
                   )""",
                (algorithm_version,),
            )
            connection.execute(
                "DELETE FROM observation_fingerprints WHERE fingerprint_version = ?",
                (algorithm_version,),
            )
            for fingerprint, observation_ids in sorted(assignments.items()):
                connection.execute(
                    """INSERT INTO problem_clusters (algorithm_version, fingerprint)
                       VALUES (?, ?)
                       ON CONFLICT(algorithm_version, fingerprint) DO NOTHING""",
                    (algorithm_version, fingerprint),
                )
                cluster = connection.execute(
                    """SELECT id FROM problem_clusters
                       WHERE algorithm_version = ? AND fingerprint = ?""",
                    (algorithm_version, fingerprint),
                ).fetchone()
                assert cluster is not None
                cluster_id = int(cluster["id"])
                cluster_ids.append(cluster_id)
                for observation_id in observation_ids:
                    connection.execute(
                        """INSERT INTO observation_fingerprints (
                               observation_id, fingerprint_version, fingerprint
                           ) VALUES (?, ?, ?)
                           ON CONFLICT(observation_id, fingerprint_version) DO UPDATE SET
                               fingerprint = excluded.fingerprint""",
                        (observation_id, algorithm_version, fingerprint),
                    )
                    connection.execute(
                        """INSERT INTO cluster_members (cluster_id, observation_id)
                           VALUES (?, ?)
                           ON CONFLICT(cluster_id, observation_id) DO NOTHING""",
                        (cluster_id, observation_id),
                    )
            connection.execute(
                """DELETE FROM problem_clusters
                   WHERE algorithm_version = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM cluster_members
                         WHERE cluster_members.cluster_id = problem_clusters.id
                     )""",
                (algorithm_version,),
            )
        return tuple(cluster_ids)

    def create_research_case(self, *, cluster_id: int, title: str) -> int:
        if not title.strip():
            raise ValueError("research case title must not be empty")
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO research_cases (cluster_id, title) VALUES (?, ?)",
                (cluster_id, title),
            )
            case_id = _last_insert_id(cursor)
            connection.executemany(
                """INSERT INTO research_passes (case_id, pass_type)
                   VALUES (?, ?)""",
                tuple((case_id, requirement.value) for requirement in ResearchRequirement),
            )
        return case_id

    def upsert_competitor(
        self,
        *,
        case_id: int,
        name: str,
        solution_type: SolutionType,
        profile_claim_id: int,
        url: str | None = None,
        target_customer: str | None = None,
        market: str | None = None,
        pricing: str | None = None,
        pricing_model: str | None = None,
        features: Sequence[str] = (),
        integrations: Sequence[str] = (),
        dach_available: bool | None = None,
        dach_specific: bool | None = None,
        incumbent_fix_risk: bool | None = None,
        incumbent_fix_rationale: str | None = None,
        additional_evidence: Sequence[tuple[CompetitorEvidenceRole, int]] = (),
    ) -> int:
        if not name.strip():
            raise ValueError("competitor name must not be empty")
        clean_fix_rationale = (
            incumbent_fix_rationale.strip()
            if incumbent_fix_rationale and incumbent_fix_rationale.strip()
            else None
        )
        if (incumbent_fix_risk is None) != (clean_fix_rationale is None):
            raise ValueError(
                "incumbent fix risk and its non-empty rationale must be supplied together"
            )

        def encode(values: Sequence[str]) -> str:
            cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
            return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

        normalized_url = normalize_url(url) if url else None
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO competitors (
                       case_id, name, url, solution_type, target_customer, market,
                       pricing, pricing_model, features_json, integrations_json,
                       dach_available, dach_specific, incumbent_fix_risk,
                       incumbent_fix_rationale, profile_claim_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(case_id, name) DO UPDATE SET
                       url = excluded.url,
                       solution_type = excluded.solution_type,
                       target_customer = excluded.target_customer,
                       market = excluded.market,
                       pricing = excluded.pricing,
                       pricing_model = excluded.pricing_model,
                       features_json = excluded.features_json,
                       integrations_json = excluded.integrations_json,
                       dach_available = excluded.dach_available,
                       dach_specific = excluded.dach_specific,
                       incumbent_fix_risk = excluded.incumbent_fix_risk,
                       incumbent_fix_rationale = excluded.incumbent_fix_rationale,
                       profile_claim_id = excluded.profile_claim_id,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    case_id,
                    name.strip(),
                    normalized_url,
                    solution_type.value,
                    target_customer,
                    market,
                    pricing,
                    pricing_model,
                    encode(features),
                    encode(integrations),
                    dach_available,
                    dach_specific,
                    incumbent_fix_risk,
                    clean_fix_rationale,
                    profile_claim_id,
                ),
            )
            row = connection.execute(
                "SELECT id FROM competitors WHERE case_id = ? AND name = ?",
                (case_id, name.strip()),
            ).fetchone()
            assert row is not None
            competitor_id = int(row["id"])
            connection.execute(
                """INSERT OR IGNORE INTO competitor_evidence (
                       competitor_id, claim_id, evidence_role
                   ) VALUES (?, ?, 'PROFILE')""",
                (competitor_id, profile_claim_id),
            )
            connection.executemany(
                """INSERT OR IGNORE INTO competitor_evidence (
                       competitor_id, claim_id, evidence_role
                   ) VALUES (?, ?, ?)""",
                tuple(
                    (competitor_id, claim_id, role.value)
                    for role, claim_id in additional_evidence
                ),
            )
        return competitor_id

    def add_competitor_complaint(
        self,
        *,
        competitor_id: int,
        complaint_type: str,
        statement: str,
        factual_claim_ids: Sequence[int],
        affected_segment: str | None = None,
        frequency_observed: str | None = None,
    ) -> int:
        if not complaint_type.strip() or not statement.strip():
            raise ValueError("complaint type and statement must not be empty")
        claim_ids = tuple(dict.fromkeys(factual_claim_ids))
        if not claim_ids:
            raise ValueError("competitor complaint requires factual claim evidence")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO competitor_complaints (
                       competitor_id, complaint_type, complaint_statement,
                       affected_segment, frequency_observed, summary_claim_id
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(competitor_id, complaint_type, complaint_statement)
                   DO UPDATE SET
                       affected_segment = excluded.affected_segment,
                       frequency_observed = excluded.frequency_observed,
                       summary_claim_id = excluded.summary_claim_id""",
                (
                    competitor_id,
                    complaint_type.strip(),
                    statement.strip(),
                    affected_segment,
                    frequency_observed,
                    claim_ids[0],
                ),
            )
            row = connection.execute(
                """SELECT id FROM competitor_complaints
                   WHERE competitor_id = ? AND complaint_type = ?
                     AND complaint_statement = ?""",
                (competitor_id, complaint_type.strip(), statement.strip()),
            ).fetchone()
            assert row is not None
            complaint_id = int(row["id"])
            connection.executemany(
                """INSERT OR IGNORE INTO competitor_complaint_evidence (
                       complaint_id, claim_id
                   ) VALUES (?, ?)""",
                tuple((complaint_id, claim_id) for claim_id in claim_ids),
            )
        return complaint_id

    def competition_inventory(self, case_id: int) -> tuple[Competitor, ...]:
        rows = self.connection.execute(
            "SELECT * FROM competitors WHERE case_id = ? ORDER BY name, id", (case_id,)
        ).fetchall()
        inventory: list[Competitor] = []
        for row in rows:
            competitor_id = int(row["id"])
            evidence_rows = self.connection.execute(
                """SELECT claim_id FROM competitor_evidence
                   WHERE competitor_id = ? ORDER BY claim_id""",
                (competitor_id,),
            ).fetchall()
            complaint_rows = self.connection.execute(
                """SELECT * FROM competitor_complaints
                   WHERE competitor_id = ? ORDER BY id""",
                (competitor_id,),
            ).fetchall()
            complaints: list[CompetitorComplaint] = []
            for complaint in complaint_rows:
                complaint_claims = self.connection.execute(
                    """SELECT claim_id FROM competitor_complaint_evidence
                       WHERE complaint_id = ? ORDER BY claim_id""",
                    (int(complaint["id"]),),
                ).fetchall()
                claims = {int(claim["claim_id"]) for claim in complaint_claims}
                claims.add(int(complaint["summary_claim_id"]))
                complaints.append(
                    CompetitorComplaint(
                        complaint_id=int(complaint["id"]),
                        complaint_type=str(complaint["complaint_type"]),
                        statement=str(complaint["complaint_statement"]),
                        affected_segment=complaint["affected_segment"],
                        frequency_observed=complaint["frequency_observed"],
                        factual_claim_ids=tuple(sorted(claims)),
                    )
                )
            claim_ids = {int(item["claim_id"]) for item in evidence_rows}
            claim_ids.add(int(row["profile_claim_id"]))
            inventory.append(
                Competitor(
                    competitor_id=competitor_id,
                    name=str(row["name"]),
                    url=row["url"],
                    solution_type=SolutionType(row["solution_type"]),
                    target_customer=row["target_customer"],
                    market=row["market"],
                    pricing=row["pricing"],
                    pricing_model=row["pricing_model"],
                    features=_decode_string_list(str(row["features_json"]), "features_json"),
                    integrations=_decode_string_list(
                        str(row["integrations_json"]), "integrations_json"
                    ),
                    dach_available=(
                        bool(row["dach_available"])
                        if row["dach_available"] is not None
                        else None
                    ),
                    dach_specific=(
                        bool(row["dach_specific"])
                        if row["dach_specific"] is not None
                        else None
                    ),
                    incumbent_fix_risk=(
                        bool(row["incumbent_fix_risk"])
                        if row["incumbent_fix_risk"] is not None
                        else None
                    ),
                    incumbent_fix_rationale=row["incumbent_fix_rationale"],
                    factual_claim_ids=tuple(sorted(claim_ids)),
                    complaints=tuple(complaints),
                )
            )
        return tuple(inventory)

    def add_counter_evidence(
        self,
        *,
        case_id: int,
        evidence_type: CounterEvidenceType,
        statement: str,
        factual_claim_id: int,
    ) -> int:
        if not statement.strip():
            raise ValueError("counter-evidence statement must not be empty")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO counter_evidence (
                       case_id, evidence_type, statement, factual_claim_id
                   ) VALUES (?, ?, ?, ?)
                   ON CONFLICT(case_id, evidence_type, statement) DO UPDATE SET
                       factual_claim_id = excluded.factual_claim_id""",
                (case_id, evidence_type.value, statement.strip(), factual_claim_id),
            )
            row = connection.execute(
                """SELECT id FROM counter_evidence
                   WHERE case_id = ? AND evidence_type = ? AND statement = ?""",
                (case_id, evidence_type.value, statement.strip()),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def counter_evidence_for_case(self, case_id: int) -> tuple[CounterEvidenceItem, ...]:
        rows = self.connection.execute(
            """SELECT id, evidence_type, statement, factual_claim_id
               FROM counter_evidence WHERE case_id = ? ORDER BY evidence_type, id""",
            (case_id,),
        ).fetchall()
        return tuple(
            CounterEvidenceItem(
                counter_evidence_id=int(row["id"]),
                evidence_type=CounterEvidenceType(row["evidence_type"]),
                statement=str(row["statement"]),
                factual_claim_id=int(row["factual_claim_id"]),
            )
            for row in rows
        )

    def case_evidence_state(self, case_id: int) -> EvidenceState:
        rows = self.connection.execute(
            """SELECT DISTINCT po.source_item_id, si.source_id, es.evidence_scope
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN problem_observations po ON po.id = cm.observation_id
               JOIN source_items si ON si.id = po.source_item_id
               JOIN evidence_spans es ON es.observation_id = po.id
               WHERE rc.id = ?""",
            (case_id,),
        ).fetchall()
        if not rows:
            raise IntegrityError("research case has no clustered observation evidence")
        scopes = {EvidenceScope(row["evidence_scope"]) for row in rows}
        source_ids = {int(row["source_id"]) for row in rows}
        item_ids = {int(row["source_item_id"]) for row in rows}
        if EvidenceScope.GLOBAL in scopes and EvidenceScope.DACH in scopes:
            return EvidenceState.CROSS_MARKET
        if len(source_ids) >= 2:
            return EvidenceState.MULTI_SOURCE
        if len(item_ids) >= 3:
            return EvidenceState.RECURRING
        if len(item_ids) >= 2:
            return EvidenceState.EMERGING
        return EvidenceState.SINGLE_SIGNAL

    def create_opportunity(
        self,
        *,
        case_id: int,
        opportunity_types: Sequence[OpportunityType],
        title: str | None = None,
    ) -> int:
        unique_types = tuple(dict.fromkeys(opportunity_types))
        if not unique_types:
            raise ValueError("opportunity requires at least one opportunity type")
        case = self.connection.execute(
            "SELECT title, status, cluster_id FROM research_cases WHERE id = ?", (case_id,)
        ).fetchone()
        if case is None:
            raise ValueError("research case does not exist")
        if ResearchCaseStatus(case["status"]) is not ResearchCaseStatus.COMPLETE:
            raise IntegrityError("opportunities require a completed research case")
        opportunity_title = title.strip() if title and title.strip() else str(case["title"])
        evidence_state = self.case_evidence_state(case_id)
        existing = self.connection.execute(
            "SELECT id, status FROM opportunities WHERE case_id = ?", (case_id,)
        ).fetchone()
        if existing is not None:
            if OpportunityStatus(existing["status"]) is OpportunityStatus.REPORT_READY:
                raise IntegrityError("a report-ready opportunity cannot be reconfigured")
            opportunity_id = int(existing["id"])
            with self.transaction() as connection:
                connection.execute(
                    """UPDATE opportunities
                       SET title = ?, evidence_state = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (opportunity_title, evidence_state.value, opportunity_id),
                )
                connection.executemany(
                    """INSERT OR IGNORE INTO opportunity_types (
                           opportunity_id, opportunity_type
                       ) VALUES (?, ?)""",
                    tuple((opportunity_id, item.value) for item in unique_types),
                )
            return opportunity_id

        problem_row = self.connection.execute(
            """SELECT po.id AS observation_id, po.problem, es.id AS evidence_span_id
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN problem_observations po ON po.id = cm.observation_id
               JOIN evidence_spans es ON es.observation_id = po.id
               WHERE rc.id = ?
                 AND length(trim(COALESCE(po.problem, ''))) > 0
               ORDER BY po.id, es.id LIMIT 1""",
            (case_id,),
        ).fetchone()
        if problem_row is None:
            raise IntegrityError("opportunity requires an evidence-backed problem claim")

        with self.transaction() as connection:
            claim_cursor = connection.execute(
                """INSERT INTO claims (observation_id, claim_kind, text)
                   VALUES (?, 'ANALYSIS', ?)""",
                (int(problem_row["observation_id"]), str(problem_row["problem"])),
            )
            problem_claim_id = _last_insert_id(claim_cursor)
            connection.execute(
                "INSERT INTO claim_evidence (claim_id, evidence_span_id) VALUES (?, ?)",
                (problem_claim_id, int(problem_row["evidence_span_id"])),
            )
            connection.execute(
                "UPDATE claims SET claim_kind = 'FACT' WHERE id = ?", (problem_claim_id,)
            )
            cursor = connection.execute(
                """INSERT INTO opportunities (case_id, title, evidence_state)
                   VALUES (?, ?, ?)""",
                (case_id, opportunity_title, evidence_state.value),
            )
            opportunity_id = _last_insert_id(cursor)
            connection.executemany(
                """INSERT INTO opportunity_types (opportunity_id, opportunity_type)
                   VALUES (?, ?)""",
                tuple((opportunity_id, item.value) for item in unique_types),
            )
            connection.execute(
                """INSERT INTO opportunity_claims (opportunity_id, claim_id, claim_role)
                   VALUES (?, ?, ?)""",
                (opportunity_id, problem_claim_id, OpportunityClaimRole.PROBLEM.value),
            )
            pass_claims = connection.execute(
                """SELECT pass_type, summary_claim_id FROM research_passes
                   WHERE case_id = ? AND summary_claim_id IS NOT NULL""",
                (case_id,),
            ).fetchall()
            for pass_claim in pass_claims:
                role = (
                    OpportunityClaimRole.CONTRADICTING
                    if pass_claim["pass_type"] == ResearchRequirement.COUNTER_EVIDENCE.value
                    else OpportunityClaimRole.SUPPORTING
                )
                connection.execute(
                    """INSERT OR IGNORE INTO opportunity_claims (
                           opportunity_id, claim_id, claim_role
                       ) VALUES (?, ?, ?)""",
                    (opportunity_id, int(pass_claim["summary_claim_id"]), role.value),
                )
            context_claims = connection.execute(
                """SELECT profile_claim_id AS claim_id FROM competitors WHERE case_id = ?
                   UNION SELECT ce.claim_id
                         FROM competitor_evidence ce
                         JOIN competitors c ON c.id = ce.competitor_id
                         WHERE c.case_id = ?
                   UNION SELECT cc.summary_claim_id
                         FROM competitor_complaints cc
                         JOIN competitors c ON c.id = cc.competitor_id
                         WHERE c.case_id = ?
                   UNION SELECT cce.claim_id
                         FROM competitor_complaint_evidence cce
                         JOIN competitor_complaints cc ON cc.id = cce.complaint_id
                         JOIN competitors c ON c.id = cc.competitor_id
                         WHERE c.case_id = ?""",
                (case_id, case_id, case_id, case_id),
            ).fetchall()
            connection.executemany(
                """INSERT OR IGNORE INTO opportunity_claims (
                       opportunity_id, claim_id, claim_role
                   ) VALUES (?, ?, ?)""",
                tuple(
                    (opportunity_id, int(row["claim_id"]), OpportunityClaimRole.CONTEXT.value)
                    for row in context_claims
                ),
            )
            counter_claims = connection.execute(
                "SELECT factual_claim_id FROM counter_evidence WHERE case_id = ?",
                (case_id,),
            ).fetchall()
            connection.executemany(
                """INSERT OR IGNORE INTO opportunity_claims (
                       opportunity_id, claim_id, claim_role
                   ) VALUES (?, ?, ?)""",
                tuple(
                    (
                        opportunity_id,
                        int(row["factual_claim_id"]),
                        OpportunityClaimRole.CONTRADICTING.value,
                    )
                    for row in counter_claims
                ),
            )
        return opportunity_id

    def transition_opportunity(
        self, opportunity_id: int, status: OpportunityStatus
    ) -> None:
        row = self.connection.execute(
            "SELECT case_id FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        if row is None:
            raise ValueError("opportunity does not exist")
        evidence_state = self.case_evidence_state(int(row["case_id"]))
        with self.transaction() as connection:
            connection.execute(
                """UPDATE opportunities
                   SET status = ?, evidence_state = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (status.value, evidence_state.value, opportunity_id),
            )

    def opportunity(self, opportunity_id: int) -> OpportunityRecord:
        row = self.connection.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        if row is None:
            raise ValueError("opportunity does not exist")
        type_rows = self.connection.execute(
            """SELECT opportunity_type FROM opportunity_types
               WHERE opportunity_id = ? ORDER BY opportunity_type""",
            (opportunity_id,),
        ).fetchall()
        return OpportunityRecord(
            opportunity_id=int(row["id"]),
            case_id=int(row["case_id"]),
            title=str(row["title"]),
            status=OpportunityStatus(row["status"]),
            evidence_state=EvidenceState(row["evidence_state"]),
            opportunity_types=tuple(
                OpportunityType(item["opportunity_type"]) for item in type_rows
            ),
        )

    def search_opportunities(
        self,
        *,
        query: str | None = None,
        status: OpportunityStatus | None = None,
        evidence_state: EvidenceState | None = None,
        opportunity_type: OpportunityType | None = None,
        saved_only: bool = False,
        limit: int = 100,
    ) -> tuple[OpportunityRecord, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("opportunity search limit must be between 1 and 1000")
        clean_query = query.strip() if query and query.strip() else None
        clauses: list[str] = []
        parameters: list[object] = []
        if status is not None:
            clauses.append("o.status = ?")
            parameters.append(status.value)
        if evidence_state is not None:
            clauses.append("o.evidence_state = ?")
            parameters.append(evidence_state.value)
        if opportunity_type is not None:
            clauses.append(
                """EXISTS (
                       SELECT 1 FROM opportunity_types ot
                       WHERE ot.opportunity_id = o.id AND ot.opportunity_type = ?
                   )"""
            )
            parameters.append(opportunity_type.value)
        if saved_only:
            clauses.append(
                "EXISTS (SELECT 1 FROM saved_opportunities so WHERE so.opportunity_id = o.id)"
            )
        if clean_query is not None:
            escaped = (
                clean_query.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            clauses.append(
                """(
                       unicode_casefold(o.title) LIKE ? ESCAPE '\\'
                       OR EXISTS (
                           SELECT 1 FROM research_cases rc
                           JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                           JOIN problem_observations po ON po.id = cm.observation_id
                           WHERE rc.id = o.case_id AND (
                               unicode_casefold(po.problem) LIKE ? ESCAPE '\\'
                               OR unicode_casefold(po.actor) LIKE ? ESCAPE '\\'
                               OR unicode_casefold(po.job_to_be_done) LIKE ? ESCAPE '\\'
                               OR unicode_casefold(po.context) LIKE ? ESCAPE '\\'
                           )
                       )
                   )"""
            )
            parameters.extend((pattern,) * 5)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        rows = self.connection.execute(
            f"""SELECT o.* FROM opportunities o
                {where}
                ORDER BY o.updated_at DESC, o.id DESC
                LIMIT ?""",
            tuple(parameters),
        ).fetchall()
        opportunity_ids = [int(row["id"]) for row in rows]
        types_by_opportunity: dict[int, list[OpportunityType]] = {
            opportunity_id: [] for opportunity_id in opportunity_ids
        }
        if opportunity_ids:
            placeholders = ", ".join("?" for _ in opportunity_ids)
            type_rows = self.connection.execute(
                f"""SELECT opportunity_id, opportunity_type FROM opportunity_types
                    WHERE opportunity_id IN ({placeholders})
                    ORDER BY opportunity_id, opportunity_type""",
                tuple(opportunity_ids),
            ).fetchall()
            for type_row in type_rows:
                types_by_opportunity[int(type_row["opportunity_id"])].append(
                    OpportunityType(type_row["opportunity_type"])
                )
        return tuple(
            OpportunityRecord(
                opportunity_id=int(row["id"]),
                case_id=int(row["case_id"]),
                title=str(row["title"]),
                status=OpportunityStatus(row["status"]),
                evidence_state=EvidenceState(row["evidence_state"]),
                opportunity_types=tuple(types_by_opportunity[int(row["id"])]),
            )
            for row in rows
        )

    def save_opportunity(
        self, opportunity_id: int, *, note: str | None = None
    ) -> SavedOpportunity:
        opportunity = self.opportunity(opportunity_id)
        if opportunity.status is not OpportunityStatus.REPORT_READY:
            raise IntegrityError("only report-ready opportunities can be saved")
        clean_note = note.strip() if note and note.strip() else None
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO saved_opportunities (opportunity_id, note)
                   VALUES (?, ?)
                   ON CONFLICT(opportunity_id) DO UPDATE SET
                       note = excluded.note,
                       updated_at = CURRENT_TIMESTAMP""",
                (opportunity_id, clean_note),
            )
        return self.saved_opportunity(opportunity_id)

    def saved_opportunity(self, opportunity_id: int) -> SavedOpportunity:
        row = self.connection.execute(
            """SELECT note, saved_at, updated_at FROM saved_opportunities
               WHERE opportunity_id = ?""",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            raise ValueError("opportunity is not saved")
        return SavedOpportunity(
            opportunity=self.opportunity(opportunity_id),
            note=row["note"],
            saved_at=str(row["saved_at"]),
            updated_at=str(row["updated_at"]),
        )

    def saved_opportunities(self) -> tuple[SavedOpportunity, ...]:
        rows = self.connection.execute(
            """SELECT opportunity_id FROM saved_opportunities
               ORDER BY saved_at DESC, opportunity_id DESC"""
        ).fetchall()
        return tuple(
            self.saved_opportunity(int(row["opportunity_id"])) for row in rows
        )

    def unsave_opportunity(self, opportunity_id: int) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM saved_opportunities WHERE opportunity_id = ?",
                (opportunity_id,),
            )
        return cursor.rowcount == 1

    def upsert_dach_assessment(
        self,
        *,
        case_id: int,
        actor_equivalence: ActorEquivalence,
        actor_rationale: str,
        workflow_equivalence: WorkflowEquivalence,
        workflow_rationale: str,
        transfer_type: DachTransferType,
        transfer_rationale: str,
        local_evidence_state: LocalEvidenceState,
        dach_observation_count: int,
        dach_unique_author_count: int,
        dach_source_count: int,
        buyer_structure: str | None = None,
        ecosystem_dependencies: Sequence[str] = (),
        regulatory_dependencies: Sequence[str] = (),
        switching_barriers: Sequence[str] = (),
        localization_gaps: Sequence[str] = (),
    ) -> None:
        rationales = (actor_rationale, workflow_rationale, transfer_rationale)
        if any(not rationale.strip() for rationale in rationales):
            raise ValueError("DACH assessment rationales must not be empty")
        _validate_dach_evidence_counts(
            local_evidence_state=local_evidence_state,
            dach_observation_count=dach_observation_count,
            dach_unique_author_count=dach_unique_author_count,
            dach_source_count=dach_source_count,
        )

        def encode(values: Sequence[str]) -> str:
            cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
            return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO dach_assessments (
                       case_id, actor_equivalence, actor_rationale,
                       workflow_equivalence, workflow_rationale,
                       transfer_type, transfer_rationale, local_evidence_state,
                       dach_observation_count, dach_unique_author_count,
                       dach_source_count, buyer_structure,
                       ecosystem_dependencies_json, regulatory_dependencies_json,
                       switching_barriers_json, localization_gaps_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(case_id) DO UPDATE SET
                       actor_equivalence = excluded.actor_equivalence,
                       actor_rationale = excluded.actor_rationale,
                       workflow_equivalence = excluded.workflow_equivalence,
                       workflow_rationale = excluded.workflow_rationale,
                       transfer_type = excluded.transfer_type,
                       transfer_rationale = excluded.transfer_rationale,
                       local_evidence_state = excluded.local_evidence_state,
                       dach_observation_count = excluded.dach_observation_count,
                       dach_unique_author_count = excluded.dach_unique_author_count,
                       dach_source_count = excluded.dach_source_count,
                       buyer_structure = excluded.buyer_structure,
                       ecosystem_dependencies_json = excluded.ecosystem_dependencies_json,
                       regulatory_dependencies_json = excluded.regulatory_dependencies_json,
                       switching_barriers_json = excluded.switching_barriers_json,
                       localization_gaps_json = excluded.localization_gaps_json,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    case_id,
                    actor_equivalence.value,
                    actor_rationale.strip(),
                    workflow_equivalence.value,
                    workflow_rationale.strip(),
                    transfer_type.value,
                    transfer_rationale.strip(),
                    local_evidence_state.value,
                    dach_observation_count,
                    dach_unique_author_count,
                    dach_source_count,
                    (
                        buyer_structure.strip()
                        if buyer_structure and buyer_structure.strip()
                        else None
                    ),
                    encode(ecosystem_dependencies),
                    encode(regulatory_dependencies),
                    encode(switching_barriers),
                    encode(localization_gaps),
                ),
            )

    def dach_assessment(self, case_id: int) -> DachAssessment | None:
        row = self.connection.execute(
            "SELECT * FROM dach_assessments WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None

        return DachAssessment(
            actor_equivalence=ActorEquivalence(row["actor_equivalence"]),
            actor_rationale=str(row["actor_rationale"]),
            workflow_equivalence=WorkflowEquivalence(row["workflow_equivalence"]),
            workflow_rationale=str(row["workflow_rationale"]),
            transfer_type=DachTransferType(row["transfer_type"]),
            transfer_rationale=str(row["transfer_rationale"]),
            local_evidence_state=LocalEvidenceState(row["local_evidence_state"]),
            dach_observation_count=int(row["dach_observation_count"]),
            dach_unique_author_count=int(row["dach_unique_author_count"]),
            dach_source_count=int(row["dach_source_count"]),
            buyer_structure=row["buyer_structure"],
            ecosystem_dependencies=_decode_string_list(
                str(row["ecosystem_dependencies_json"]), "ecosystem_dependencies_json"
            ),
            regulatory_dependencies=_decode_string_list(
                str(row["regulatory_dependencies_json"]), "regulatory_dependencies_json"
            ),
            switching_barriers=_decode_string_list(
                str(row["switching_barriers_json"]), "switching_barriers_json"
            ),
            localization_gaps=_decode_string_list(
                str(row["localization_gaps_json"]), "localization_gaps_json"
            ),
        )

    def upsert_case_stakeholder(
        self,
        *,
        case_id: int,
        role: StakeholderRole,
        knowledge: StakeholderKnowledge,
        note: str,
        party: str | None = None,
        factual_claim_id: int | None = None,
    ) -> None:
        clean_note = note.strip()
        if not clean_note:
            raise ValueError("stakeholder note must not be empty")
        clean_party = party.strip() if party and party.strip() else None
        if knowledge is StakeholderKnowledge.KNOWN:
            if clean_party is None or factual_claim_id is None:
                raise ValueError("known stakeholder requires party and factual claim")
            claim = self.connection.execute(
                "SELECT claim_kind FROM claims WHERE id = ?", (factual_claim_id,)
            ).fetchone()
            if claim is None or claim["claim_kind"] != ClaimKind.FACT.value:
                raise IntegrityError("known stakeholder requires a factual claim")
        elif clean_party is not None or factual_claim_id is not None:
            raise ValueError("unknown stakeholder cannot contain party or factual claim")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO case_stakeholders (
                       case_id, role, knowledge, party, note, factual_claim_id
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(case_id, role) DO UPDATE SET
                       knowledge = excluded.knowledge,
                       party = excluded.party,
                       note = excluded.note,
                       factual_claim_id = excluded.factual_claim_id,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    case_id,
                    role.value,
                    knowledge.value,
                    clean_party,
                    clean_note,
                    factual_claim_id,
                ),
            )

    def case_stakeholders(self, case_id: int) -> tuple[CaseStakeholder, ...]:
        rows = self.connection.execute(
            """SELECT role, knowledge, party, note, factual_claim_id
               FROM case_stakeholders WHERE case_id = ?
               ORDER BY CASE role
                   WHEN 'END_USER' THEN 1
                   WHEN 'BUYER' THEN 2
                   WHEN 'DECISION_MAKER' THEN 3
                   WHEN 'GATEKEEPER' THEN 4
                   WHEN 'INFLUENCER' THEN 5
               END""",
            (case_id,),
        ).fetchall()
        return tuple(
            CaseStakeholder(
                role=StakeholderRole(row["role"]),
                knowledge=StakeholderKnowledge(row["knowledge"]),
                party=row["party"],
                note=str(row["note"]),
                factual_claim_id=(
                    int(row["factual_claim_id"])
                    if row["factual_claim_id"] is not None
                    else None
                ),
            )
            for row in rows
        )

    def satisfy_research_requirement(
        self,
        *,
        case_id: int,
        requirement: ResearchRequirement,
        factual_claim_id: int,
        note: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE research_passes
                   SET status = 'SATISFIED', outcome = 'EVIDENCE_FOUND',
                       summary_claim_id = ?, note = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE case_id = ? AND pass_type = ?""",
                (factual_claim_id, note, case_id, requirement.value),
            )
            if cursor.rowcount != 1:
                raise ValueError("research case or requirement does not exist")

    def complete_research_requirement_without_evidence(
        self,
        *,
        case_id: int,
        requirement: ResearchRequirement,
        note: str,
    ) -> None:
        if not note.strip():
            raise ValueError("no-evidence research outcome requires a note")
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE research_passes
                   SET status = 'SATISFIED', outcome = 'NO_EVIDENCE_FOUND',
                       summary_claim_id = NULL, note = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE case_id = ? AND pass_type = ?""",
                (note, case_id, requirement.value),
            )
            if cursor.rowcount != 1:
                raise ValueError("research case or requirement does not exist")

    def add_research_unknown(self, *, case_id: int, statement: str) -> int:
        if not statement.strip():
            raise ValueError("research unknown must not be empty")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO research_unknowns (case_id, statement)
                   VALUES (?, ?)
                   ON CONFLICT(case_id, statement) DO NOTHING""",
                (case_id, statement),
            )
            row = connection.execute(
                """SELECT id FROM research_unknowns
                   WHERE case_id = ? AND statement = ?""",
                (case_id, statement),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def transition_research_case(
        self, case_id: int, status: ResearchCaseStatus
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE research_cases
                   SET status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (status.value, case_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("research case does not exist")

    def add_validation_question(
        self, *, case_id: int, question: str, rationale: str | None = None
    ) -> int:
        if not question.strip():
            raise ValueError("validation question must not be empty")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO validation_questions (case_id, question, rationale)
                   VALUES (?, ?, ?)
                   ON CONFLICT(case_id, question) DO UPDATE SET
                       rationale = excluded.rationale""",
                (case_id, question, rationale),
            )
            row = connection.execute(
                """SELECT id FROM validation_questions
                   WHERE case_id = ? AND question = ?""",
                (case_id, question),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def research_case_report_data(self, case_id: int) -> ResearchCaseReportData:
        case = self.connection.execute(
            "SELECT id, title, status FROM research_cases WHERE id = ?", (case_id,)
        ).fetchone()
        if case is None:
            raise ValueError("research case does not exist")

        cluster_citations = self.connection.execute(
            """SELECT DISTINCT es.id, es.observation_id, es.source_item_id,
                              si.source_id, s.name AS source_name, si.url, es.excerpt,
                              es.evidence_scope, s.commercial_use_status,
                              s.quoting_rules, s.rights_reviewed_at,
                              si.country_code, si.published_at
               FROM research_cases AS rc
               JOIN cluster_members AS cm ON cm.cluster_id = rc.cluster_id
               JOIN evidence_spans AS es ON es.observation_id = cm.observation_id
               JOIN source_items AS si ON si.id = es.source_item_id
               JOIN sources AS s ON s.id = si.source_id
               WHERE rc.id = ? ORDER BY es.id""",
            (case_id,),
        ).fetchall()
        requirement_citations = self.connection.execute(
            """SELECT DISTINCT es.id, es.observation_id, es.source_item_id,
                              si.source_id, s.name AS source_name, si.url, es.excerpt,
                              es.evidence_scope, s.commercial_use_status,
                              s.quoting_rules, s.rights_reviewed_at,
                              si.country_code, si.published_at
               FROM research_passes AS rr
               JOIN claim_evidence AS ce ON ce.claim_id = rr.summary_claim_id
               JOIN evidence_spans AS es ON es.id = ce.evidence_span_id
               JOIN source_items AS si ON si.id = es.source_item_id
               JOIN sources AS s ON s.id = si.source_id
               WHERE rr.case_id = ? AND rr.status = 'SATISFIED'
               ORDER BY es.id""",
            (case_id,),
        ).fetchall()
        citation_rows_by_id = {
            int(row["id"]): row
            for row in (*cluster_citations, *requirement_citations)
        }
        citations_by_id = {
            int(row["id"]): EvidenceCitation(
                evidence_span_id=int(row["id"]),
                source_name=str(row["source_name"]),
                source_url=row["url"],
                excerpt=str(row["excerpt"]),
                evidence_scope=EvidenceScope(row["evidence_scope"]),
                commercial_use_status=row["commercial_use_status"],
                quoting_rules=row["quoting_rules"],
                rights_reviewed_at=row["rights_reviewed_at"],
            )
            for row in citation_rows_by_id.values()
        }

        def evidence_summary(scope: EvidenceScope) -> EvidenceScopeSummary:
            rows = tuple(
                row
                for row in citation_rows_by_id.values()
                if row["evidence_scope"] == scope.value
            )
            source_names = tuple(
                sorted(
                    {str(row["source_name"]) for row in rows},
                    key=str.casefold,
                )
            )
            countries = tuple(
                sorted(
                    {
                        str(row["country_code"]).upper()
                        for row in rows
                        if row["country_code"] is not None
                        and str(row["country_code"]).strip()
                    }
                )
            )
            published_by_item = {
                int(row["source_item_id"]): str(row["published_at"])
                for row in rows
                if row["published_at"] is not None
                and str(row["published_at"]).strip()
            }
            published_values = tuple(published_by_item.values())
            return EvidenceScopeSummary(
                evidence_scope=scope,
                problem_observation_count=len(
                    {
                        int(row["observation_id"])
                        for row in rows
                        if row["observation_id"] is not None
                    }
                ),
                evidence_span_count=len(rows),
                cited_item_count=len(
                    {int(row["source_item_id"]) for row in rows}
                ),
                source_count=len({int(row["source_id"]) for row in rows}),
                source_names=source_names,
                country_codes=countries,
                dated_item_count=len(published_by_item),
                earliest_published_at=(
                    min(published_values) if published_values else None
                ),
                latest_published_at=(
                    max(published_values) if published_values else None
                ),
            )
        finding_rows = self.connection.execute(
            """SELECT rr.pass_type, rr.outcome, c.text, rr.note
               FROM research_passes AS rr
               LEFT JOIN claims AS c ON c.id = rr.summary_claim_id
               WHERE rr.case_id = ? AND rr.status = 'SATISFIED'
               ORDER BY rr.pass_type""",
            (case_id,),
        ).fetchall()
        question_rows = self.connection.execute(
            """SELECT question, rationale FROM validation_questions
               WHERE case_id = ? ORDER BY id""",
            (case_id,),
        ).fetchall()
        unknown_rows = self.connection.execute(
            """SELECT statement FROM research_unknowns
               WHERE case_id = ? ORDER BY id""",
            (case_id,),
        ).fetchall()
        profile_rows = self.connection.execute(
            """SELECT po.problem, po.actor, po.job_to_be_done, po.context,
                      po.tools_used, po.current_workaround
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN problem_observations po ON po.id = cm.observation_id
               WHERE rc.id = ? ORDER BY po.id""",
            (case_id,),
        ).fetchall()
        workaround_rows = self.connection.execute(
            """SELECT w.workaround_type, w.description
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN workarounds w ON w.observation_id = cm.observation_id
               WHERE rc.id = ? ORDER BY w.workaround_type, w.description""",
            (case_id,),
        ).fetchall()
        impact_rows = self.connection.execute(
            """SELECT i.impact_type, i.quantified, i.value, i.unit, i.frequency
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN impact_signals i ON i.observation_id = cm.observation_id
               WHERE rc.id = ? ORDER BY i.impact_type, i.id""",
            (case_id,),
        ).fetchall()
        payment_rows = self.connection.execute(
            """SELECT p.payment_type, p.amount, p.currency, p.frequency
               FROM research_cases rc
               JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
               JOIN payment_signals p ON p.observation_id = cm.observation_id
               WHERE rc.id = ? ORDER BY p.payment_type, p.id""",
            (case_id,),
        ).fetchall()

        def distinct(column: str) -> tuple[str, ...]:
            return tuple(
                dict.fromkeys(
                    str(row[column]).strip()
                    for row in profile_rows
                    if row[column] is not None and str(row[column]).strip()
                )
            )

        structured_workarounds = tuple(
            dict.fromkeys(
                f"{row['workaround_type']}: {row['description']}"
                for row in workaround_rows
            )
        )
        fallback_workarounds = distinct("current_workaround")
        impacts = tuple(
            dict.fromkeys(_format_impact_signal(row) for row in impact_rows)
        )
        payments = tuple(
            dict.fromkeys(_format_payment_signal(row) for row in payment_rows)
        )
        return ResearchCaseReportData(
            opportunity_id=None,
            case_id=int(case["id"]),
            title=str(case["title"]),
            status=ResearchCaseStatus(case["status"]),
            opportunity_status=None,
            opportunity_types=(),
            evidence_state=self.case_evidence_state(case_id),
            problem_profile=ProblemProfile(
                problems=distinct("problem"),
                actors=distinct("actor"),
                jobs_to_be_done=distinct("job_to_be_done"),
                contexts=distinct("context"),
                tools_used=distinct("tools_used"),
                workarounds=structured_workarounds or fallback_workarounds,
                impacts=impacts,
                payment_evidence=payments,
            ),
            global_evidence_summary=evidence_summary(EvidenceScope.GLOBAL),
            dach_evidence_summary=evidence_summary(EvidenceScope.DACH),
            citations=tuple(citations_by_id.values()),
            findings=tuple(
                RequirementFinding(
                    requirement=ResearchRequirement(row["pass_type"]),
                    outcome=ResearchOutcome(row["outcome"]),
                    claim_text=(str(row["text"]) if row["text"] is not None else None),
                    note=row["note"],
                )
                for row in finding_rows
            ),
            competitors=self.competition_inventory(case_id),
            counter_evidence=self.counter_evidence_for_case(case_id),
            dach_assessment=self.dach_assessment(case_id),
            stakeholders=self.case_stakeholders(case_id),
            unknowns=tuple(str(row["statement"]) for row in unknown_rows),
            validation_questions=tuple(
                ValidationQuestion(question=str(row["question"]), rationale=row["rationale"])
                for row in question_rows
            ),
        )

    def opportunity_report_data(self, opportunity_id: int) -> ResearchCaseReportData:
        opportunity = self.opportunity(opportunity_id)
        data = self.research_case_report_data(opportunity.case_id)
        return replace(
            data,
            opportunity_id=opportunity.opportunity_id,
            title=opportunity.title,
            opportunity_status=opportunity.status,
            opportunity_types=opportunity.opportunity_types,
            evidence_state=opportunity.evidence_state,
        )

    def research_case_summary(self, case_id: int) -> ResearchCaseSummary:
        case = self.connection.execute(
            """SELECT id, cluster_id, title, status,
                      (SELECT COUNT(*) FROM validation_questions WHERE case_id = rc.id)
                          AS validation_question_count,
                      (SELECT COUNT(*) FROM research_unknowns WHERE case_id = rc.id)
                          AS unknown_count
               FROM research_cases AS rc WHERE id = ?""",
            (case_id,),
        ).fetchone()
        if case is None:
            raise ValueError("research case does not exist")
        requirement_rows = self.connection.execute(
            """SELECT pass_type, status, outcome, summary_claim_id, note
               FROM research_passes WHERE case_id = ?
               ORDER BY pass_type""",
            (case_id,),
        ).fetchall()
        return ResearchCaseSummary(
            case_id=int(case["id"]),
            cluster_id=int(case["cluster_id"]),
            title=str(case["title"]),
            status=ResearchCaseStatus(case["status"]),
            requirements=tuple(
                RequirementProgress(
                    requirement=ResearchRequirement(row["pass_type"]),
                    status=RequirementStatus(row["status"]),
                    outcome=(
                        ResearchOutcome(row["outcome"])
                        if row["outcome"] is not None
                        else None
                    ),
                    factual_claim_id=(
                        int(row["summary_claim_id"])
                        if row["summary_claim_id"] is not None
                        else None
                    ),
                    note=row["note"],
                )
                for row in requirement_rows
            ),
            validation_question_count=int(case["validation_question_count"]),
            unknown_count=int(case["unknown_count"]),
        )

    def add_evidence_span(
        self,
        *,
        source_item_id: int,
        evidence_range: EvidenceRange,
        evidence_scope: EvidenceScope,
        observation_id: int | None = None,
    ) -> int:
        row = self.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (source_item_id,)
        ).fetchone()
        if row is None:
            raise ValueError("source item does not exist")
        excerpt = evidence_range.excerpt_from(str(row["raw_text"]))
        if observation_id is not None:
            observation = self.connection.execute(
                "SELECT source_item_id, evidence_scope FROM problem_observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
            if observation is None:
                raise ValueError("observation does not exist")
            if int(observation["source_item_id"]) != source_item_id:
                raise IntegrityError("evidence and observation must reference the same source item")
            if observation["evidence_scope"] != evidence_scope.value:
                raise IntegrityError("evidence and observation scopes must match")
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO evidence_spans (
                       source_item_id, observation_id, start_offset, end_offset,
                       excerpt, evidence_scope
                   )
                   SELECT ?, ?, ?, ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM evidence_spans
                       WHERE source_item_id = ?
                         AND observation_id IS ?
                         AND start_offset = ? AND end_offset = ?
                         AND evidence_scope = ?
                   )""",
                (
                    source_item_id,
                    observation_id,
                    evidence_range.start,
                    evidence_range.end,
                    excerpt,
                    evidence_scope.value,
                    source_item_id,
                    observation_id,
                    evidence_range.start,
                    evidence_range.end,
                    evidence_scope.value,
                ),
            )
            if cursor.rowcount == 1:
                evidence_id = _last_insert_id(cursor)
            else:
                existing = connection.execute(
                    """SELECT id FROM evidence_spans
                       WHERE source_item_id = ? AND observation_id IS ?
                         AND start_offset = ? AND end_offset = ?
                         AND evidence_scope = ?""",
                    (
                        source_item_id,
                        observation_id,
                        evidence_range.start,
                        evidence_range.end,
                        evidence_scope.value,
                    ),
                ).fetchone()
                assert existing is not None
                evidence_id = int(existing["id"])
        return evidence_id

    def create_claim(
        self,
        *,
        claim_kind: ClaimKind,
        text: str,
        observation_id: int | None = None,
        evidence_span_ids: Sequence[int] = (),
    ) -> int:
        if not text.strip():
            raise ValueError("claim text must not be empty")
        if claim_kind is ClaimKind.FACT and not evidence_span_ids:
            raise IntegrityError("factual claims require at least one evidence span")

        with self.transaction() as connection:
            if claim_kind is ClaimKind.FACT:
                cursor = connection.execute(
                    """INSERT INTO claims (observation_id, claim_kind, text)
                       VALUES (?, 'ANALYSIS', ?)""",
                    (observation_id, text),
                )
            else:
                cursor = connection.execute(
                    "INSERT INTO claims (observation_id, claim_kind, text) VALUES (?, ?, ?)",
                    (observation_id, claim_kind.value, text),
                )
            claim_id = _last_insert_id(cursor)
            for evidence_span_id in dict.fromkeys(evidence_span_ids):
                connection.execute(
                    "INSERT INTO claim_evidence (claim_id, evidence_span_id) VALUES (?, ?)",
                    (claim_id, evidence_span_id),
                )
            if claim_kind is ClaimKind.FACT:
                connection.execute(
                    "UPDATE claims SET claim_kind = 'FACT' WHERE id = ?", (claim_id,)
                )
        return claim_id

    def stats(self) -> dict[str, int]:
        tables = (
            "sources",
            "source_registry_profiles",
            "source_metrics",
            "source_problem_family_metrics",
            "source_items",
            "discovery_runs",
            "discovery_records",
            "acquisition_records",
            "pipeline_runs",
            "model_runs",
            "cost_events",
            "problem_observations",
            "evidence_spans",
            "observation_revisions",
            "workarounds",
            "impact_signals",
            "payment_signals",
            "claims",
            "problem_clusters",
            "research_cases",
            "opportunities",
            "saved_opportunities",
            "competitors",
            "competitor_complaints",
            "counter_evidence",
            "dach_assessments",
            "case_stakeholders",
            "research_passes",
            "research_unknowns",
            "validation_questions",
        )
        return {
            table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }

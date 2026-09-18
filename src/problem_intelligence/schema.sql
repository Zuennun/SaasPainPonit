PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_key TEXT NOT NULL UNIQUE,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('CANDIDATE','EXPLORATION','CORE','LOW_VALUE','EXCLUDED')),
    access_method TEXT,
    commercial_use_status TEXT,
    retention_rules TEXT,
    attribution_requirements TEXT,
    quoting_rules TEXT,
    deletion_requirements TEXT,
    rate_limit_notes TEXT,
    rights_reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_items (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    normalized_external_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    raw_text TEXT NOT NULL,
    author_external_id TEXT,
    published_at TEXT,
    country_code TEXT,
    language_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, normalized_external_id)
);

CREATE TABLE IF NOT EXISTS source_registry_metadata (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_id, namespace)
);

CREATE TABLE IF NOT EXISTS source_registry_profiles (
    source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    canonical_url TEXT,
    external_id TEXT,
    primary_industry TEXT,
    secondary_industries_json TEXT NOT NULL DEFAULT '[]',
    professions_json TEXT NOT NULL DEFAULT '[]',
    audience_type TEXT NOT NULL DEFAULT 'GENERAL'
        CHECK (audience_type IN (
            'PRACTITIONER','OWNER','BUYER','CONSUMER','FOUNDER',
            'VENDOR','JOBSEEKER','GENERAL','MIXED'
        )),
    audience_segments_json TEXT NOT NULL DEFAULT '[]',
    languages_json TEXT NOT NULL DEFAULT '[]',
    country_focus_json TEXT NOT NULL DEFAULT '[]',
    market_scope TEXT NOT NULL DEFAULT 'UNKNOWN',
    curation_decision TEXT,
    curation_priority TEXT,
    research_role TEXT,
    scan_directive TEXT,
    scan_now INTEGER CHECK (scan_now IN (0,1) OR scan_now IS NULL),
    recommended_action TEXT,
    strict_relevance TEXT,
    activity_status TEXT,
    activity_confidence TEXT,
    activity_basis TEXT,
    dach_transfer TEXT,
    sensitive_data_risk TEXT,
    research_angle TEXT,
    rationale TEXT,
    pilot_posts INTEGER CHECK (pilot_posts >= 0 OR pilot_posts IS NULL),
    strict_pilot_posts INTEGER
        CHECK (strict_pilot_posts >= 0 OR strict_pilot_posts IS NULL),
    registry_verified_at TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_metrics (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    measurement_key TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    measurement_start TEXT,
    measurement_end TEXT,
    items_scanned INTEGER NOT NULL CHECK (items_scanned >= 0),
    items_after_prefilter INTEGER CHECK (
        items_after_prefilter >= 0 OR items_after_prefilter IS NULL
    ),
    pain_observations INTEGER NOT NULL CHECK (pain_observations >= 0),
    strong_single_signals INTEGER NOT NULL CHECK (strong_single_signals >= 0),
    active_search_signals INTEGER NOT NULL CHECK (active_search_signals >= 0),
    quantified_impact_signals INTEGER CHECK (
        quantified_impact_signals >= 0 OR quantified_impact_signals IS NULL
    ),
    payment_signals INTEGER NOT NULL CHECK (payment_signals >= 0),
    problem_clusters_contributed INTEGER NOT NULL
        CHECK (problem_clusters_contributed >= 0),
    cross_source_confirmations INTEGER NOT NULL
        CHECK (cross_source_confirmations >= 0),
    promo_items INTEGER CHECK (promo_items >= 0 OR promo_items IS NULL),
    duplicate_items INTEGER CHECK (duplicate_items >= 0 OR duplicate_items IS NULL),
    temporary_incidents INTEGER NOT NULL CHECK (temporary_incidents >= 0),
    support_questions INTEGER NOT NULL CHECK (support_questions >= 0),
    known_processing_cost_usd REAL CHECK (
        known_processing_cost_usd >= 0 OR known_processing_cost_usd IS NULL
    ),
    processing_cost_complete INTEGER NOT NULL
        CHECK (processing_cost_complete IN (0,1)),
    measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, measurement_key)
);

CREATE TABLE IF NOT EXISTS source_problem_family_metrics (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    measurement_key TEXT NOT NULL,
    problem_family TEXT NOT NULL CHECK (problem_family IN (
        'MANUAL_DATA_ENTRY','RECONCILIATION','INTEGRATION','DOCUMENT_COLLECTION',
        'REPORTING','SCHEDULING','APPROVAL','COMMUNICATION','MIGRATION','COMPLIANCE',
        'HANDOVER','ERROR_CORRECTION','SEARCH_RETRIEVAL','MONITORING','PROCUREMENT',
        'PAYMENTS','INVENTORY','CUSTOMER_MANAGEMENT','WORKFORCE','OTHER'
    )),
    metric_version TEXT NOT NULL,
    observation_count INTEGER NOT NULL CHECK (observation_count >= 0),
    strong_signal_count INTEGER NOT NULL CHECK (strong_signal_count >= 0),
    active_search_count INTEGER NOT NULL CHECK (active_search_count >= 0),
    payment_signal_count INTEGER NOT NULL CHECK (payment_signal_count >= 0),
    cluster_count INTEGER NOT NULL CHECK (cluster_count >= 0),
    first_seen TEXT,
    last_seen TEXT,
    measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_id, measurement_key, problem_family)
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    availability TEXT NOT NULL
        CHECK (availability IN ('RESULTS','NO_RESULTS','SOURCE_UNAVAILABLE')),
    search_requests INTEGER NOT NULL DEFAULT 1 CHECK (search_requests >= 0),
    results_returned INTEGER NOT NULL DEFAULT 0 CHECK (results_returned >= 0),
    reddit_urls_discovered INTEGER NOT NULL DEFAULT 0 CHECK (reddit_urls_discovered >= 0),
    latency_ms INTEGER CHECK (latency_ms >= 0),
    cost_usd REAL CHECK (cost_usd >= 0),
    error TEXT,
    provider_capabilities_json TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discovery_records (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    comment_id TEXT,
    title TEXT,
    snippet TEXT,
    state TEXT NOT NULL DEFAULT 'DISCOVERED'
        CHECK (state IN ('DISCOVERED','CONTENT_PARTIAL','CONTENT_COMPLETE',
                         'ACQUISITION_FAILED','POLICY_BLOCKED')),
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, canonical_url)
);

CREATE TABLE IF NOT EXISTS acquisition_records (
    id INTEGER PRIMARY KEY,
    discovery_id INTEGER NOT NULL REFERENCES discovery_records(id) ON DELETE CASCADE,
    source_item_id INTEGER REFERENCES source_items(id),
    provider TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('CONTENT_PARTIAL','CONTENT_COMPLETE',
                         'ACQUISITION_FAILED','POLICY_BLOCKED')),
    completeness TEXT CHECK (completeness IN ('FULL','PARTIAL','METADATA_ONLY')),
    latency_ms INTEGER CHECK (latency_ms >= 0),
    cost_usd REAL CHECK (cost_usd >= 0),
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (discovery_id, provider)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    stage TEXT NOT NULL CHECK (stage IN ('EXTRACTION')),
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    input_count INTEGER NOT NULL CHECK (input_count >= 0),
    output_count INTEGER NOT NULL DEFAULT 0 CHECK (output_count >= 0),
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS completed_pipeline_signatures (
    run_id TEXT PRIMARY KEY REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('EXTRACTION')),
    version TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    UNIQUE (stage, version, input_signature)
);

CREATE TABLE IF NOT EXISTS model_runs (
    id TEXT PRIMARY KEY,
    operation_key TEXT NOT NULL UNIQUE,
    pipeline_run_id TEXT REFERENCES pipeline_runs(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    pipeline_stage TEXT NOT NULL,
    template_version TEXT NOT NULL,
    external_run_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED','FAILED')),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    items_processed INTEGER NOT NULL CHECK (items_processed >= 0),
    error TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, external_run_id)
);

CREATE TABLE IF NOT EXISTS cost_events (
    id INTEGER PRIMARY KEY,
    model_run_id TEXT NOT NULL UNIQUE REFERENCES model_runs(id) ON DELETE CASCADE,
    amount_decimal TEXT NOT NULL,
    currency TEXT NOT NULL,
    measurement_source TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS problem_observations (
    id INTEGER PRIMARY KEY,
    source_item_id INTEGER NOT NULL REFERENCES source_items(id),
    problem_type TEXT NOT NULL,
    problem_family TEXT CHECK (problem_family IN (
        'MANUAL_DATA_ENTRY','RECONCILIATION','INTEGRATION','DOCUMENT_COLLECTION',
        'REPORTING','SCHEDULING','APPROVAL','COMMUNICATION','MIGRATION','COMPLIANCE',
        'HANDOVER','ERROR_CORRECTION','SEARCH_RETRIEVAL','MONITORING','PROCUREMENT',
        'PAYMENTS','INVENTORY','CUSTOMER_MANAGEMENT','WORKFORCE','OTHER'
    ) OR problem_family IS NULL),
    ontology_version TEXT,
    evidence_scope TEXT NOT NULL CHECK (evidence_scope IN ('GLOBAL','DACH')),
    actor TEXT,
    actor_role TEXT,
    industry TEXT,
    job_to_be_done TEXT,
    context TEXT,
    problem TEXT NOT NULL,
    root_cause TEXT,
    current_workaround TEXT,
    tools_used TEXT,
    frequency TEXT,
    time_impact TEXT,
    financial_impact TEXT,
    revenue_impact TEXT,
    error_impact TEXT,
    delay_impact TEXT,
    risk_impact TEXT,
    active_solution_search INTEGER CHECK (active_solution_search IN (0,1) OR active_solution_search IS NULL),
    switching_intent INTEGER CHECK (switching_intent IN (0,1) OR switching_intent IS NULL),
    existing_solution TEXT,
    existing_spend TEXT,
    paid_workaround TEXT,
    country_code TEXT,
    language_code TEXT,
    extraction_version TEXT NOT NULL,
    pipeline_run_id TEXT REFERENCES pipeline_runs(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence_spans (
    id INTEGER PRIMARY KEY,
    source_item_id INTEGER NOT NULL REFERENCES source_items(id),
    observation_id INTEGER REFERENCES problem_observations(id),
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    excerpt TEXT NOT NULL,
    evidence_scope TEXT NOT NULL CHECK (evidence_scope IN ('GLOBAL','DACH')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observation_revisions (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL CHECK (field_name IN (
        'actor','actor_role','industry','job_to_be_done','context','root_cause',
        'current_workaround','tools_used','frequency','time_impact','financial_impact',
        'revenue_impact','error_impact','delay_impact','risk_impact',
        'active_solution_search','switching_intent','existing_solution','existing_spend',
        'paid_workaround','country_code','language_code'
    )),
    old_value_json TEXT NOT NULL CHECK (json_valid(old_value_json)),
    new_value_json TEXT NOT NULL CHECK (json_valid(new_value_json)),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    evidence_span_id INTEGER NOT NULL REFERENCES evidence_spans(id),
    revision_version TEXT NOT NULL CHECK (length(trim(revision_version)) > 0),
    revised_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (observation_id, field_name, revision_version)
);

CREATE TABLE IF NOT EXISTS workarounds (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id) ON DELETE CASCADE,
    workaround_type TEXT NOT NULL CHECK (workaround_type IN (
        'SPREADSHEET','CSV','EMAIL','WHATSAPP','PAPER','MANUAL_ENTRY','EMPLOYEE',
        'FREELANCER','AGENCY','VIRTUAL_ASSISTANT','INTERNAL_SCRIPT','CUSTOM_SOFTWARE',
        'MULTIPLE_TOOLS','EXISTING_SAAS','OTHER'
    )),
    description TEXT NOT NULL,
    evidence_span_id INTEGER NOT NULL REFERENCES evidence_spans(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (observation_id, workaround_type, description, evidence_span_id)
);

CREATE TABLE IF NOT EXISTS impact_signals (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id) ON DELETE CASCADE,
    impact_type TEXT NOT NULL CHECK (impact_type IN (
        'TIME','MONEY','REVENUE','ERRORS','CUSTOMER_LOSS','COMPLIANCE','RISK',
        'STRESS','DELAY','OTHER'
    )),
    quantified INTEGER NOT NULL CHECK (quantified IN (0,1)),
    value TEXT,
    unit TEXT,
    frequency TEXT,
    evidence_span_id INTEGER NOT NULL REFERENCES evidence_spans(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (quantified = 0 AND value IS NULL AND unit IS NULL)
        OR (quantified = 1 AND value IS NOT NULL AND unit IS NOT NULL)
    ),
    UNIQUE (
        observation_id, impact_type, quantified, value, unit, frequency, evidence_span_id
    )
);

CREATE TABLE IF NOT EXISTS payment_signals (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id) ON DELETE CASCADE,
    payment_type TEXT NOT NULL CHECK (payment_type IN (
        'EXISTING_SOFTWARE_SPEND','EMPLOYEE_LABOR','FREELANCER_SPEND','AGENCY_SPEND',
        'EXPLICIT_BUDGET','PURCHASE_SEARCH','SWITCHING_INTENT','PRICE_COMPLAINT',
        'EXPLICIT_WILLINGNESS_TO_PAY'
    )),
    amount TEXT,
    currency TEXT,
    frequency TEXT,
    evidence_span_id INTEGER NOT NULL REFERENCES evidence_spans(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (amount IS NULL AND currency IS NULL)
        OR (amount IS NOT NULL AND currency IS NOT NULL)
    ),
    UNIQUE (
        observation_id, payment_type, amount, currency, frequency, evidence_span_id
    )
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER REFERENCES problem_observations(id),
    claim_kind TEXT NOT NULL CHECK (claim_kind IN ('FACT','ANALYSIS','HYPOTHESIS')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    evidence_span_id INTEGER NOT NULL REFERENCES evidence_spans(id),
    PRIMARY KEY (claim_id, evidence_span_id)
);

CREATE TABLE IF NOT EXISTS observation_fingerprints (
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id),
    fingerprint_version TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (observation_id, fingerprint_version)
);

CREATE TABLE IF NOT EXISTS problem_clusters (
    id INTEGER PRIMARY KEY,
    algorithm_version TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (algorithm_version, fingerprint)
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES problem_clusters(id) ON DELETE CASCADE,
    observation_id INTEGER NOT NULL REFERENCES problem_observations(id),
    PRIMARY KEY (cluster_id, observation_id)
);

CREATE TABLE IF NOT EXISTS research_cases (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL REFERENCES problem_clusters(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN','INVESTIGATING','REVIEW','COMPLETE','REJECTED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS competitors (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    url TEXT,
    solution_type TEXT NOT NULL CHECK (solution_type IN (
        'DIRECT_SOFTWARE','INDIRECT_SOFTWARE','LEGACY_SOFTWARE','INTERNAL_TOOL',
        'MANUAL_PROCESS','FREELANCER','AGENCY','SERVICE_PROVIDER','DIY_SCRIPT',
        'NO_SOLUTION_FOUND'
    )),
    target_customer TEXT,
    market TEXT,
    pricing TEXT,
    pricing_model TEXT,
    features_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(features_json) AND json_type(features_json) = 'array'),
    integrations_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(integrations_json) AND json_type(integrations_json) = 'array'),
    dach_available INTEGER CHECK (dach_available IN (0, 1) OR dach_available IS NULL),
    dach_specific INTEGER CHECK (dach_specific IN (0, 1) OR dach_specific IS NULL),
    incumbent_fix_risk INTEGER
        CHECK (incumbent_fix_risk IN (0, 1) OR incumbent_fix_risk IS NULL),
    incumbent_fix_rationale TEXT,
    profile_claim_id INTEGER NOT NULL REFERENCES claims(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_id, name),
    CHECK (
        (incumbent_fix_risk IS NULL AND incumbent_fix_rationale IS NULL)
        OR (incumbent_fix_risk IS NOT NULL
            AND incumbent_fix_rationale IS NOT NULL
            AND length(trim(incumbent_fix_rationale)) > 0)
    )
);

CREATE TABLE IF NOT EXISTS competitor_evidence (
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    evidence_role TEXT NOT NULL CHECK (evidence_role IN (
        'PROFILE','PRICING','FEATURE','INTEGRATION','AVAILABILITY','INCUMBENT_FIX_RISK'
    )),
    PRIMARY KEY (competitor_id, claim_id, evidence_role)
);

CREATE TABLE IF NOT EXISTS competitor_complaints (
    id INTEGER PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    complaint_type TEXT NOT NULL CHECK (length(trim(complaint_type)) > 0),
    complaint_statement TEXT NOT NULL CHECK (length(trim(complaint_statement)) > 0),
    affected_segment TEXT,
    frequency_observed TEXT,
    summary_claim_id INTEGER NOT NULL REFERENCES claims(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (competitor_id, complaint_type, complaint_statement)
);

CREATE TABLE IF NOT EXISTS competitor_complaint_evidence (
    complaint_id INTEGER NOT NULL REFERENCES competitor_complaints(id) ON DELETE CASCADE,
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    PRIMARY KEY (complaint_id, claim_id)
);

CREATE TABLE IF NOT EXISTS counter_evidence (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN (
        'TEMPORARY_PROBLEM','FEATURE_ALREADY_EXISTS','FEATURE_ANNOUNCED',
        'FREE_WORKAROUND','SATISFIED_WITH_WORKAROUND','LOW_FREQUENCY','LOW_IMPACT',
        'VERY_SMALL_SEGMENT','NO_PAYMENT_SIGNAL','HIGH_SWITCHING_COST',
        'INCUMBENT_FIX_RISK','REGULATORY_BARRIER','DISTRIBUTION_DIFFICULTY',
        'DEPENDENCY_RISK','WEAK_DACH_TRANSFER','CONTRADICTING_USERS','OTHER'
    )),
    statement TEXT NOT NULL CHECK (length(trim(statement)) > 0),
    factual_claim_id INTEGER NOT NULL REFERENCES claims(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_id, evidence_type, statement)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL UNIQUE REFERENCES research_cases(id),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','REPORT_READY')),
    evidence_state TEXT NOT NULL CHECK (evidence_state IN (
        'SINGLE_SIGNAL','EMERGING','RECURRING','MULTI_SOURCE','CROSS_MARKET'
    )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunity_types (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    opportunity_type TEXT NOT NULL CHECK (opportunity_type IN (
        'RECURRING_PROBLEM','STRONG_SINGLE_SIGNAL','WORKFLOW_GAP','INTEGRATION_GAP',
        'INCUMBENT_GAP','UNDERSERVED_SEGMENT','LOCALIZATION_GAP','REGULATION_GAP',
        'EMERGING_PROBLEM'
    )),
    PRIMARY KEY (opportunity_id, opportunity_type)
);

CREATE TABLE IF NOT EXISTS opportunity_claims (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    claim_role TEXT NOT NULL CHECK (claim_role IN (
        'PROBLEM','SUPPORTING','CONTEXT','CONTRADICTING'
    )),
    PRIMARY KEY (opportunity_id, claim_id, claim_role)
);

CREATE TABLE IF NOT EXISTS saved_opportunities (
    opportunity_id INTEGER PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
    note TEXT CHECK (note IS NULL OR length(trim(note)) > 0),
    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dach_assessments (
    case_id INTEGER PRIMARY KEY REFERENCES research_cases(id) ON DELETE CASCADE,
    actor_equivalence TEXT NOT NULL CHECK (actor_equivalence IN (
        'DIRECT','SIMILAR','DIFFERENT','UNCLEAR'
    )),
    actor_rationale TEXT NOT NULL CHECK (length(trim(actor_rationale)) > 0),
    workflow_equivalence TEXT NOT NULL CHECK (workflow_equivalence IN (
        'DIRECT','LOCALIZED','MATERIALLY_DIFFERENT','UNKNOWN'
    )),
    workflow_rationale TEXT NOT NULL CHECK (length(trim(workflow_rationale)) > 0),
    transfer_type TEXT NOT NULL CHECK (transfer_type IN (
        'DIRECT_TRANSFER','LOCALIZATION_REQUIRED','LOCAL_FRICTION',
        'WEAK_LOCAL_EVIDENCE','MATERIAL_DIFFERENCE','UNKNOWN'
    )),
    transfer_rationale TEXT NOT NULL CHECK (length(trim(transfer_rationale)) > 0),
    local_evidence_state TEXT NOT NULL CHECK (local_evidence_state IN (
        'NONE_FOUND','SINGLE_LOCAL_SIGNAL','MULTIPLE_LOCAL_SIGNALS',
        'MULTI_SOURCE_LOCAL_SIGNALS'
    )),
    dach_observation_count INTEGER NOT NULL CHECK (dach_observation_count >= 0),
    dach_unique_author_count INTEGER NOT NULL CHECK (dach_unique_author_count >= 0),
    dach_source_count INTEGER NOT NULL CHECK (dach_source_count >= 0),
    buyer_structure TEXT,
    ecosystem_dependencies_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(ecosystem_dependencies_json)
               AND json_type(ecosystem_dependencies_json) = 'array'),
    regulatory_dependencies_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(regulatory_dependencies_json)
               AND json_type(regulatory_dependencies_json) = 'array'),
    switching_barriers_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(switching_barriers_json)
               AND json_type(switching_barriers_json) = 'array'),
    localization_gaps_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(localization_gaps_json)
               AND json_type(localization_gaps_json) = 'array'),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (local_evidence_state = 'NONE_FOUND'
         AND dach_observation_count = 0
         AND dach_unique_author_count = 0
         AND dach_source_count = 0)
        OR (local_evidence_state = 'SINGLE_LOCAL_SIGNAL'
            AND dach_observation_count >= 1
            AND dach_unique_author_count >= 1
            AND dach_source_count >= 1)
        OR (local_evidence_state = 'MULTIPLE_LOCAL_SIGNALS'
            AND dach_observation_count >= 2
            AND dach_unique_author_count >= 1
            AND dach_source_count >= 1)
        OR (local_evidence_state = 'MULTI_SOURCE_LOCAL_SIGNALS'
            AND dach_observation_count >= 2
            AND dach_unique_author_count >= 1
            AND dach_source_count >= 2)
    )
);

CREATE TABLE IF NOT EXISTS case_stakeholders (
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN (
        'END_USER','BUYER','DECISION_MAKER','GATEKEEPER','INFLUENCER'
    )),
    knowledge TEXT NOT NULL CHECK (knowledge IN ('KNOWN','UNKNOWN')),
    party TEXT,
    note TEXT NOT NULL CHECK (length(trim(note)) > 0),
    factual_claim_id INTEGER REFERENCES claims(id),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, role),
    CHECK (
        (knowledge = 'KNOWN' AND party IS NOT NULL
         AND length(trim(party)) > 0 AND factual_claim_id IS NOT NULL)
        OR (knowledge = 'UNKNOWN' AND party IS NULL AND factual_claim_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS research_requirements (
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    requirement_type TEXT NOT NULL
        CHECK (requirement_type IN ('COMPETITION','COUNTER_EVIDENCE')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SATISFIED')),
    satisfied_by_claim_id INTEGER REFERENCES claims(id),
    note TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, requirement_type),
    CHECK (
        (status = 'PENDING' AND satisfied_by_claim_id IS NULL)
        OR (status = 'SATISFIED' AND satisfied_by_claim_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS research_passes (
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    pass_type TEXT NOT NULL CHECK (pass_type IN (
        'WORKAROUND_RESEARCH','COMPETITION','DACH_TRANSFER','COUNTER_EVIDENCE'
    )),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SATISFIED')),
    outcome TEXT CHECK (outcome IN ('EVIDENCE_FOUND','NO_EVIDENCE_FOUND')),
    summary_claim_id INTEGER REFERENCES claims(id),
    note TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, pass_type),
    CHECK (
        (status = 'PENDING' AND outcome IS NULL AND summary_claim_id IS NULL)
        OR (
            status = 'SATISFIED'
            AND outcome = 'EVIDENCE_FOUND'
            AND summary_claim_id IS NOT NULL
        )
        OR (
            status = 'SATISFIED'
            AND outcome = 'NO_EVIDENCE_FOUND'
            AND summary_claim_id IS NULL
            AND note IS NOT NULL
            AND length(trim(note)) > 0
        )
    )
);

CREATE TABLE IF NOT EXISTS research_unknowns (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    statement TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_id, statement)
);

CREATE TABLE IF NOT EXISTS validation_questions (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES research_cases(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    rationale TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_id, question)
);

CREATE TRIGGER IF NOT EXISTS fact_requires_evidence_on_claim_insert
BEFORE INSERT ON claims
WHEN NEW.claim_kind = 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'FACT claims must be created atomically with evidence');
END;

CREATE TRIGGER IF NOT EXISTS source_text_immutable_after_evidence
BEFORE UPDATE OF raw_text ON source_items
WHEN NEW.raw_text <> OLD.raw_text
 AND EXISTS (
    SELECT 1 FROM evidence_spans WHERE source_item_id = OLD.id
 )
BEGIN
    SELECT RAISE(ABORT, 'cannot change source text after evidence has been recorded');
END;

CREATE TRIGGER IF NOT EXISTS evidence_excerpt_matches_source_on_insert
BEFORE INSERT ON evidence_spans
WHEN NEW.end_offset > COALESCE(
    (SELECT length(raw_text) FROM source_items WHERE id = NEW.source_item_id),
    -1
 )
 OR NEW.excerpt <> COALESCE(
    (
        SELECT substr(raw_text, NEW.start_offset + 1, NEW.end_offset - NEW.start_offset)
        FROM source_items WHERE id = NEW.source_item_id
    ),
    ''
 )
BEGIN
    SELECT RAISE(ABORT, 'evidence excerpt must match source text');
END;

CREATE TRIGGER IF NOT EXISTS evidence_excerpt_matches_source_on_update
BEFORE UPDATE OF source_item_id, start_offset, end_offset, excerpt ON evidence_spans
WHEN NEW.end_offset > COALESCE(
    (SELECT length(raw_text) FROM source_items WHERE id = NEW.source_item_id),
    -1
 )
 OR NEW.excerpt <> COALESCE(
    (
        SELECT substr(raw_text, NEW.start_offset + 1, NEW.end_offset - NEW.start_offset)
        FROM source_items WHERE id = NEW.source_item_id
    ),
    ''
 )
BEGIN
    SELECT RAISE(ABORT, 'evidence excerpt must match source text');
END;

CREATE TRIGGER IF NOT EXISTS evidence_observation_matches_on_insert
BEFORE INSERT ON evidence_spans
WHEN NEW.observation_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM problem_observations
    WHERE id = NEW.observation_id
      AND source_item_id = NEW.source_item_id
      AND evidence_scope = NEW.evidence_scope
 )
BEGIN
    SELECT RAISE(ABORT, 'evidence must match observation source and scope');
END;

CREATE TRIGGER IF NOT EXISTS evidence_observation_matches_on_update
BEFORE UPDATE OF source_item_id, observation_id, evidence_scope ON evidence_spans
WHEN NEW.observation_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM problem_observations
    WHERE id = NEW.observation_id
      AND source_item_id = NEW.source_item_id
      AND evidence_scope = NEW.evidence_scope
 )
BEGIN
    SELECT RAISE(ABORT, 'evidence must match observation source and scope');
END;

CREATE TRIGGER IF NOT EXISTS observation_revision_evidence_matches
BEFORE INSERT ON observation_revisions
WHEN NOT EXISTS (
    SELECT 1 FROM evidence_spans
    WHERE id = NEW.evidence_span_id AND observation_id = NEW.observation_id
)
BEGIN
    SELECT RAISE(ABORT, 'revision evidence must belong to the observation');
END;

CREATE TRIGGER IF NOT EXISTS claim_evidence_observation_matches
BEFORE INSERT ON claim_evidence
WHEN (SELECT observation_id FROM claims WHERE id = NEW.claim_id) IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM claims AS c
    JOIN evidence_spans AS es ON es.id = NEW.evidence_span_id
    WHERE c.id = NEW.claim_id AND es.observation_id = c.observation_id
 )
BEGIN
    SELECT RAISE(ABORT, 'claim evidence must belong to the claim observation');
END;

CREATE TRIGGER IF NOT EXISTS claim_evidence_observation_matches_on_update
BEFORE UPDATE OF claim_id, evidence_span_id ON claim_evidence
WHEN (SELECT observation_id FROM claims WHERE id = NEW.claim_id) IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM claims AS c
    JOIN evidence_spans AS es ON es.id = NEW.evidence_span_id
    WHERE c.id = NEW.claim_id AND es.observation_id = c.observation_id
 )
BEGIN
    SELECT RAISE(ABORT, 'claim evidence must belong to the claim observation');
END;

CREATE TRIGGER IF NOT EXISTS workaround_evidence_observation_matches
BEFORE INSERT ON workarounds
WHEN NOT EXISTS (
    SELECT 1 FROM evidence_spans
    WHERE id = NEW.evidence_span_id AND observation_id = NEW.observation_id
)
BEGIN
    SELECT RAISE(ABORT, 'workaround evidence must belong to the observation');
END;

CREATE TRIGGER IF NOT EXISTS impact_evidence_observation_matches
BEFORE INSERT ON impact_signals
WHEN NOT EXISTS (
    SELECT 1 FROM evidence_spans
    WHERE id = NEW.evidence_span_id AND observation_id = NEW.observation_id
)
BEGIN
    SELECT RAISE(ABORT, 'impact evidence must belong to the observation');
END;

CREATE TRIGGER IF NOT EXISTS payment_evidence_observation_matches
BEFORE INSERT ON payment_signals
WHEN NOT EXISTS (
    SELECT 1 FROM evidence_spans
    WHERE id = NEW.evidence_span_id AND observation_id = NEW.observation_id
)
BEGIN
    SELECT RAISE(ABORT, 'payment evidence must belong to the observation');
END;

CREATE TRIGGER IF NOT EXISTS fact_requires_evidence_on_claim_update
BEFORE UPDATE OF claim_kind ON claims
WHEN NEW.claim_kind = 'FACT'
 AND NOT EXISTS (
     SELECT 1 FROM claim_evidence WHERE claim_id = NEW.id
 )
BEGIN
    SELECT RAISE(ABORT, 'FACT claims require evidence');
END;

CREATE TRIGGER IF NOT EXISTS fact_keeps_at_least_one_evidence_link
BEFORE DELETE ON claim_evidence
WHEN (SELECT claim_kind FROM claims WHERE id = OLD.claim_id) = 'FACT'
 AND (SELECT COUNT(*) FROM claim_evidence WHERE claim_id = OLD.claim_id) <= 1
BEGIN
    SELECT RAISE(ABORT, 'cannot remove the final evidence link from a FACT claim');
END;

CREATE TRIGGER IF NOT EXISTS research_case_transition_guard
BEFORE UPDATE OF status ON research_cases
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'OPEN' AND NEW.status IN ('INVESTIGATING','REJECTED'))
    OR (OLD.status = 'INVESTIGATING' AND NEW.status IN ('REVIEW','REJECTED'))
    OR (OLD.status = 'REVIEW' AND NEW.status IN ('INVESTIGATING','COMPLETE','REJECTED'))
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid research case transition');
END;

CREATE TRIGGER IF NOT EXISTS research_case_insert_guard
BEFORE INSERT ON research_cases
WHEN NEW.status <> 'OPEN'
BEGIN
    SELECT RAISE(ABORT, 'research cases must start OPEN');
END;

CREATE TRIGGER IF NOT EXISTS opportunity_insert_guard
BEFORE INSERT ON opportunities
WHEN NEW.status <> 'DRAFT'
 OR COALESCE((SELECT status FROM research_cases WHERE id = NEW.case_id), '') <> 'COMPLETE'
BEGIN
    SELECT RAISE(ABORT, 'opportunities must start DRAFT from a completed research case');
END;

CREATE TRIGGER IF NOT EXISTS opportunity_transition_guard
BEFORE UPDATE OF status ON opportunities
WHEN NEW.status <> OLD.status
 AND NOT (OLD.status = 'DRAFT' AND NEW.status = 'REPORT_READY')
BEGIN
    SELECT RAISE(ABORT, 'invalid opportunity transition');
END;

CREATE TRIGGER IF NOT EXISTS saved_opportunity_insert_guard
BEFORE INSERT ON saved_opportunities
WHEN COALESCE(
    (SELECT status FROM opportunities WHERE id = NEW.opportunity_id), ''
) <> 'REPORT_READY'
BEGIN
    SELECT RAISE(ABORT, 'only report-ready opportunities can be saved');
END;

CREATE TRIGGER IF NOT EXISTS opportunity_report_ready_guard
BEFORE UPDATE OF status ON opportunities
WHEN NEW.status = 'REPORT_READY'
 AND (
    COALESCE((SELECT status FROM research_cases WHERE id = NEW.case_id), '') <> 'COMPLETE'
    OR NOT EXISTS (
        SELECT 1 FROM opportunity_types WHERE opportunity_id = NEW.id
    )
    OR NOT EXISTS (
        SELECT 1 FROM opportunity_claims
        WHERE opportunity_id = NEW.id AND claim_role = 'PROBLEM'
    )
    OR NEW.evidence_state <> (
        SELECT CASE
            WHEN EXISTS (
                SELECT 1
                FROM research_cases rc
                JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                JOIN evidence_spans es ON es.observation_id = cm.observation_id
                WHERE rc.id = NEW.case_id AND es.evidence_scope = 'GLOBAL'
            ) AND EXISTS (
                SELECT 1
                FROM research_cases rc
                JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                JOIN evidence_spans es ON es.observation_id = cm.observation_id
                WHERE rc.id = NEW.case_id AND es.evidence_scope = 'DACH'
            ) THEN 'CROSS_MARKET'
            WHEN (
                SELECT COUNT(DISTINCT si.source_id)
                FROM research_cases rc
                JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                JOIN problem_observations po ON po.id = cm.observation_id
                JOIN source_items si ON si.id = po.source_item_id
                WHERE rc.id = NEW.case_id
            ) >= 2 THEN 'MULTI_SOURCE'
            WHEN (
                SELECT COUNT(DISTINCT po.source_item_id)
                FROM research_cases rc
                JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                JOIN problem_observations po ON po.id = cm.observation_id
                WHERE rc.id = NEW.case_id
            ) >= 3 THEN 'RECURRING'
            WHEN (
                SELECT COUNT(DISTINCT po.source_item_id)
                FROM research_cases rc
                JOIN cluster_members cm ON cm.cluster_id = rc.cluster_id
                JOIN problem_observations po ON po.id = cm.observation_id
                WHERE rc.id = NEW.case_id
            ) >= 2 THEN 'EMERGING'
            ELSE 'SINGLE_SIGNAL'
        END
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'opportunity does not satisfy REPORT_READY eligibility');
END;

CREATE TRIGGER IF NOT EXISTS research_case_completion_guard
BEFORE UPDATE OF status ON research_cases
WHEN NEW.status = 'COMPLETE'
 AND (
    (SELECT COUNT(*) FROM research_passes WHERE case_id = NEW.id) <> 4
    OR EXISTS (
        SELECT 1 FROM research_passes
        WHERE case_id = NEW.id AND status <> 'SATISFIED'
    )
    OR NOT EXISTS (
        SELECT 1 FROM dach_assessments WHERE case_id = NEW.id
    )
    OR EXISTS (
        SELECT 1 FROM research_passes rp
        WHERE rp.case_id = NEW.id
          AND rp.pass_type = 'COMPETITION'
          AND rp.outcome = 'EVIDENCE_FOUND'
          AND NOT EXISTS (SELECT 1 FROM competitors c WHERE c.case_id = NEW.id)
    )
    OR EXISTS (
        SELECT 1 FROM research_passes rp
        WHERE rp.case_id = NEW.id
          AND rp.pass_type = 'COUNTER_EVIDENCE'
          AND rp.outcome = 'EVIDENCE_FOUND'
          AND NOT EXISTS (SELECT 1 FROM counter_evidence ce WHERE ce.case_id = NEW.id)
    )
    OR NOT EXISTS (
        SELECT 1
        FROM cluster_members cm
        JOIN problem_observations po ON po.id = cm.observation_id
        WHERE cm.cluster_id = NEW.cluster_id
          AND (
              length(trim(COALESCE(po.actor, ''))) > 0
              OR length(trim(COALESCE(po.actor_role, ''))) > 0
          )
          AND length(trim(COALESCE(po.job_to_be_done, ''))) > 0
          AND length(trim(COALESCE(po.context, ''))) > 0
          AND EXISTS (
              SELECT 1 FROM evidence_spans es WHERE es.observation_id = po.id
          )
    )
    OR NOT EXISTS (
        SELECT 1 FROM research_unknowns WHERE case_id = NEW.id
    )
    OR NOT EXISTS (
        SELECT 1 FROM validation_questions WHERE case_id = NEW.id
    )
 )
BEGIN
    SELECT RAISE(
        ABORT,
        'clear evidenced problem context, four research passes, unknowns, and validation questions are required before completion'
    );
END;

CREATE TRIGGER IF NOT EXISTS research_pass_fact_guard
BEFORE UPDATE OF status, outcome, summary_claim_id, pass_type ON research_passes
WHEN NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND COALESCE(
     (SELECT claim_kind FROM claims WHERE id = NEW.summary_claim_id), ''
 ) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'an evidence-found research pass requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_fact_insert_guard
BEFORE INSERT ON research_passes
WHEN NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND COALESCE(
     (SELECT claim_kind FROM claims WHERE id = NEW.summary_claim_id), ''
 ) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'an evidence-found research pass requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_dach_assessment_guard
BEFORE UPDATE OF status, pass_type ON research_passes
WHEN NEW.pass_type = 'DACH_TRANSFER'
 AND NEW.status = 'SATISFIED'
 AND NOT EXISTS (SELECT 1 FROM dach_assessments WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'DACH transfer pass requires a structured DACH assessment');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_dach_assessment_insert_guard
BEFORE INSERT ON research_passes
WHEN NEW.pass_type = 'DACH_TRANSFER'
 AND NEW.status = 'SATISFIED'
 AND NOT EXISTS (SELECT 1 FROM dach_assessments WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'DACH transfer pass requires a structured DACH assessment');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_competition_inventory_guard
BEFORE UPDATE OF status, outcome, pass_type ON research_passes
WHEN NEW.pass_type = 'COMPETITION'
 AND NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND NOT EXISTS (SELECT 1 FROM competitors WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'evidence-found competition pass requires a competitor record');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_competition_inventory_insert_guard
BEFORE INSERT ON research_passes
WHEN NEW.pass_type = 'COMPETITION'
 AND NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND NOT EXISTS (SELECT 1 FROM competitors WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'evidence-found competition pass requires a competitor record');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_counter_evidence_guard
BEFORE UPDATE OF status, outcome, pass_type ON research_passes
WHEN NEW.pass_type = 'COUNTER_EVIDENCE'
 AND NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND NOT EXISTS (SELECT 1 FROM counter_evidence WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'evidence-found counter pass requires structured counter-evidence');
END;

CREATE TRIGGER IF NOT EXISTS research_pass_counter_evidence_insert_guard
BEFORE INSERT ON research_passes
WHEN NEW.pass_type = 'COUNTER_EVIDENCE'
 AND NEW.status = 'SATISFIED'
 AND NEW.outcome = 'EVIDENCE_FOUND'
 AND NOT EXISTS (SELECT 1 FROM counter_evidence WHERE case_id = NEW.case_id)
BEGIN
    SELECT RAISE(ABORT, 'evidence-found counter pass requires structured counter-evidence');
END;

CREATE TRIGGER IF NOT EXISTS counter_evidence_fact_guard
BEFORE INSERT ON counter_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.factual_claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'counter-evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS counter_evidence_fact_update_guard
BEFORE UPDATE OF factual_claim_id ON counter_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.factual_claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'counter-evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS case_stakeholder_fact_guard
BEFORE INSERT ON case_stakeholders
WHEN NEW.knowledge = 'KNOWN'
 AND COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.factual_claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'known stakeholder requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS case_stakeholder_fact_update_guard
BEFORE UPDATE OF knowledge, factual_claim_id ON case_stakeholders
WHEN NEW.knowledge = 'KNOWN'
 AND COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.factual_claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'known stakeholder requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_profile_fact_guard
BEFORE INSERT ON competitors
WHEN COALESCE(
    (SELECT claim_kind FROM claims WHERE id = NEW.profile_claim_id), ''
) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor profile requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_profile_fact_update_guard
BEFORE UPDATE OF profile_claim_id ON competitors
WHEN COALESCE(
    (SELECT claim_kind FROM claims WHERE id = NEW.profile_claim_id), ''
) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor profile requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_evidence_fact_guard
BEFORE INSERT ON competitor_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_evidence_fact_update_guard
BEFORE UPDATE OF claim_id ON competitor_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_complaint_fact_guard
BEFORE INSERT ON competitor_complaints
WHEN COALESCE(
    (SELECT claim_kind FROM claims WHERE id = NEW.summary_claim_id), ''
) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor complaint requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_complaint_fact_update_guard
BEFORE UPDATE OF summary_claim_id ON competitor_complaints
WHEN COALESCE(
    (SELECT claim_kind FROM claims WHERE id = NEW.summary_claim_id), ''
) <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor complaint requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_complaint_evidence_fact_guard
BEFORE INSERT ON competitor_complaint_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor complaint evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS competitor_complaint_evidence_fact_update_guard
BEFORE UPDATE OF claim_id ON competitor_complaint_evidence
WHEN COALESCE((SELECT claim_kind FROM claims WHERE id = NEW.claim_id), '') <> 'FACT'
BEGIN
    SELECT RAISE(ABORT, 'competitor complaint evidence requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS completed_case_keeps_dach_assessment
BEFORE DELETE ON dach_assessments
WHEN (SELECT status FROM research_cases WHERE id = OLD.case_id) = 'COMPLETE'
BEGIN
    SELECT RAISE(ABORT, 'completed research case must retain its DACH assessment');
END;

CREATE TRIGGER IF NOT EXISTS research_requirement_fact_guard
BEFORE UPDATE OF status, satisfied_by_claim_id ON research_requirements
WHEN NEW.status = 'SATISFIED'
 AND (
    NEW.satisfied_by_claim_id IS NULL
    OR COALESCE(
        (SELECT claim_kind FROM claims WHERE id = NEW.satisfied_by_claim_id), ''
    ) <> 'FACT'
 )
BEGIN
    SELECT RAISE(ABORT, 'a satisfied research requirement requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS research_requirement_fact_insert_guard
BEFORE INSERT ON research_requirements
WHEN NEW.status = 'SATISFIED'
 AND (
    NEW.satisfied_by_claim_id IS NULL
    OR COALESCE(
        (SELECT claim_kind FROM claims WHERE id = NEW.satisfied_by_claim_id), ''
    ) <> 'FACT'
 )
BEGIN
    SELECT RAISE(ABORT, 'a satisfied research requirement requires a factual claim');
END;

CREATE TRIGGER IF NOT EXISTS research_requirement_keeps_fact
BEFORE UPDATE OF claim_kind ON claims
WHEN OLD.claim_kind = 'FACT'
 AND NEW.claim_kind <> 'FACT'
 AND (
    EXISTS (
        SELECT 1 FROM research_requirements
        WHERE satisfied_by_claim_id = OLD.id AND status = 'SATISFIED'
    )
    OR EXISTS (
        SELECT 1 FROM research_passes
        WHERE summary_claim_id = OLD.id AND status = 'SATISFIED'
    )
    OR EXISTS (SELECT 1 FROM competitors WHERE profile_claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM competitor_evidence WHERE claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM competitor_complaints WHERE summary_claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM competitor_complaint_evidence WHERE claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM counter_evidence WHERE factual_claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM opportunity_claims WHERE claim_id = OLD.id)
    OR EXISTS (SELECT 1 FROM case_stakeholders WHERE factual_claim_id = OLD.id)
 )
BEGIN
    SELECT RAISE(ABORT, 'cannot downgrade a claim that satisfies a research requirement');
END;

CREATE INDEX IF NOT EXISTS idx_source_items_source ON source_items(source_id);
CREATE INDEX IF NOT EXISTS idx_source_registry_industry
    ON source_registry_profiles(primary_industry);
CREATE INDEX IF NOT EXISTS idx_source_registry_scan
    ON source_registry_profiles(scan_now, curation_priority);
CREATE INDEX IF NOT EXISTS idx_source_metrics_source
    ON source_metrics(source_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_source_problem_family
    ON source_problem_family_metrics(problem_family, measurement_key);
CREATE INDEX IF NOT EXISTS idx_discovery_records_canonical
    ON discovery_records(canonical_url);
CREATE INDEX IF NOT EXISTS idx_discovery_records_source ON discovery_records(source_id);
CREATE INDEX IF NOT EXISTS idx_acquisition_records_item ON acquisition_records(source_item_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage_status ON pipeline_runs(stage, status);
CREATE INDEX IF NOT EXISTS idx_completed_pipeline_signature
    ON completed_pipeline_signatures(stage, version, input_signature);
CREATE INDEX IF NOT EXISTS idx_observations_item ON problem_observations(source_item_id);
CREATE INDEX IF NOT EXISTS idx_observations_scope ON problem_observations(evidence_scope);
CREATE INDEX IF NOT EXISTS idx_evidence_observation ON evidence_spans(observation_id);
CREATE INDEX IF NOT EXISTS idx_observation_revisions_observation
    ON observation_revisions(observation_id);
CREATE INDEX IF NOT EXISTS idx_workarounds_observation ON workarounds(observation_id);
CREATE INDEX IF NOT EXISTS idx_impact_signals_observation ON impact_signals(observation_id);
CREATE INDEX IF NOT EXISTS idx_payment_signals_observation ON payment_signals(observation_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_impact_signal_semantics
    ON impact_signals (
        observation_id, impact_type, quantified,
        COALESCE(value, ''), COALESCE(unit, ''), COALESCE(frequency, ''), evidence_span_id
    );
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_signal_semantics
    ON payment_signals (
        observation_id, payment_type, COALESCE(amount, ''), COALESCE(currency, ''),
        COALESCE(frequency, ''), evidence_span_id
    );
CREATE INDEX IF NOT EXISTS idx_fingerprints_value
    ON observation_fingerprints(fingerprint_version, fingerprint);
CREATE INDEX IF NOT EXISTS idx_cluster_members_observation ON cluster_members(observation_id);
CREATE INDEX IF NOT EXISTS idx_research_cases_cluster ON research_cases(cluster_id);
CREATE INDEX IF NOT EXISTS idx_competitors_case ON competitors(case_id);
CREATE INDEX IF NOT EXISTS idx_competitor_evidence_claim ON competitor_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_competitor_complaints_competitor
    ON competitor_complaints(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_complaint_evidence_claim
    ON competitor_complaint_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_counter_evidence_case ON counter_evidence(case_id);
CREATE INDEX IF NOT EXISTS idx_counter_evidence_claim ON counter_evidence(factual_claim_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_claims_claim ON opportunity_claims(claim_id);
CREATE INDEX IF NOT EXISTS idx_research_requirements_claim
    ON research_requirements(satisfied_by_claim_id);
CREATE INDEX IF NOT EXISTS idx_research_passes_claim
    ON research_passes(summary_claim_id);
CREATE INDEX IF NOT EXISTS idx_research_unknowns_case
    ON research_unknowns(case_id);
CREATE INDEX IF NOT EXISTS idx_validation_questions_case ON validation_questions(case_id);
CREATE INDEX IF NOT EXISTS idx_case_stakeholders_claim
    ON case_stakeholders(factual_claim_id);
CREATE INDEX IF NOT EXISTS idx_model_runs_pipeline_run ON model_runs(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_model_runs_stage ON model_runs(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_cost_events_model_run ON cost_events(model_run_id);
CREATE INDEX IF NOT EXISTS idx_saved_opportunities_saved_at
    ON saved_opportunities(saved_at);

PRAGMA user_version = 21;

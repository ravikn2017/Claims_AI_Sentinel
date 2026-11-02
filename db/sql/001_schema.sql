-- Recreate the application schemas. Does not drop other databases.
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claims_owner') THEN
        CREATE ROLE claims_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'payer_app') THEN
        CREATE ROLE payer_app LOGIN;
    END IF;
END
$$;

DROP SCHEMA IF EXISTS chatbot CASCADE;
DROP SCHEMA IF EXISTS fraud CASCADE;
DROP SCHEMA IF EXISTS adjudication CASCADE;
DROP SCHEMA IF EXISTS claims CASCADE;
DROP SCHEMA IF EXISTS portal CASCADE;

CREATE SCHEMA portal AUTHORIZATION claims_owner;
CREATE SCHEMA claims AUTHORIZATION claims_owner;
CREATE SCHEMA adjudication AUTHORIZATION claims_owner;
CREATE SCHEMA fraud AUTHORIZATION claims_owner;
CREATE SCHEMA chatbot AUTHORIZATION claims_owner;

SET ROLE claims_owner;

CREATE TABLE portal.submission_log (
    submission_id text PRIMARY KEY,
    channel text NOT NULL,
    submitter_type text NOT NULL,
    submitter_id text NOT NULL,
    payload_sha256 text NOT NULL,
    publish_status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    CONSTRAINT submission_log_publish_status CHECK (publish_status IN ('pending', 'published', 'failed'))
);

CREATE TABLE portal.app_user (
    user_id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL,
    actor_type text NOT NULL,
    submitter_id text,
    CONSTRAINT app_user_role CHECK (role IN ('provider', 'member', 'reviewer', 'investigator', 'ops')),
    CONSTRAINT app_user_actor_type CHECK (actor_type IN ('user', 'operator'))
);

CREATE TABLE portal.login_session (
    token text PRIMARY KEY,
    user_id text NOT NULL REFERENCES portal.app_user (user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE claims.member (
    member_id text PRIMARY KEY,
    first_name text NOT NULL,
    last_name text NOT NULL,
    dob date NOT NULL,
    gender text
);

CREATE TABLE claims.policy (
    policy_id text PRIMARY KEY,
    member_id text NOT NULL REFERENCES claims.member (member_id),
    plan_code text NOT NULL,
    group_number text,
    effective_date date NOT NULL,
    termination_date date,
    status text NOT NULL
);

CREATE TABLE claims.provider (
    provider_id text PRIMARY KEY,
    npi text NOT NULL UNIQUE,
    name text NOT NULL,
    taxonomy_code text,
    network_status text,
    quality_rating integer,
    city text,
    state text,
    CONSTRAINT provider_network_status CHECK (network_status IS NULL OR network_status IN ('in', 'out')),
    CONSTRAINT provider_quality_rating CHECK (quality_rating IS NULL OR quality_rating BETWEEN 1 AND 5)
);

CREATE TABLE claims.plan_benefit (
    plan_code text NOT NULL,
    cpt_code text NOT NULL,
    benefit_category text,
    is_covered boolean NOT NULL,
    requires_prior_auth boolean NOT NULL DEFAULT false,
    policy_section text,
    PRIMARY KEY (plan_code, cpt_code)
);

CREATE TABLE claims.ref_cpt (
    code text PRIMARY KEY,
    description text NOT NULL,
    active boolean NOT NULL
);

CREATE TABLE claims.ref_icd10 (
    code text PRIMARY KEY,
    description text NOT NULL,
    billable boolean NOT NULL
);

CREATE TABLE claims.claim (
    claim_id text PRIMARY KEY,
    submission_id text NOT NULL UNIQUE REFERENCES portal.submission_log (submission_id),
    member_id text REFERENCES claims.member (member_id),
    policy_id text REFERENCES claims.policy (policy_id),
    billing_provider_id text REFERENCES claims.provider (provider_id),
    rendering_npi text,
    place_of_service text,
    diagnosis_codes text[],
    service_from date,
    service_to date,
    total_billed numeric(12, 2),
    status text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    draft jsonb NOT NULL,
    source_message jsonb NOT NULL,
    channel text NOT NULL,
    submitter_type text NOT NULL,
    submitter_id text NOT NULL,
    flags text[] NOT NULL DEFAULT '{}',
    respond_by timestamptz,
    version integer NOT NULL DEFAULT 0,
    reference_snapshot jsonb,
    CONSTRAINT claim_validated_columns_present CHECK (
        status IN ('RECEIVED', 'PENDING_INFO', 'REJECTED')
        OR (
            member_id IS NOT NULL
            AND policy_id IS NOT NULL
            AND billing_provider_id IS NOT NULL
            AND service_from IS NOT NULL
            AND service_to IS NOT NULL
            AND total_billed IS NOT NULL
            AND diagnosis_codes IS NOT NULL
        )
    )
);

CREATE TABLE claims.claim_line (
    claim_id text NOT NULL REFERENCES claims.claim (claim_id),
    line_no integer NOT NULL,
    cpt_code text,
    modifiers text[],
    units integer,
    billed_amount numeric(12, 2),
    service_date date,
    diagnosis_pointers integer[],
    prior_auth_number text,
    PRIMARY KEY (claim_id, line_no)
);

CREATE TABLE claims.claim_document (
    document_id text PRIMARY KEY,
    claim_id text NOT NULL REFERENCES claims.claim (claim_id),
    doc_type text NOT NULL,
    storage_uri text NOT NULL,
    sha256 text NOT NULL,
    uploaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE claims.claim_issue (
    issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL REFERENCES claims.claim (claim_id),
    field_path text NOT NULL,
    issue_code text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE TABLE claims.claim_amendment (
    amendment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL REFERENCES claims.claim (claim_id),
    issue_id bigint NOT NULL REFERENCES claims.claim_issue (issue_id),
    field_path text NOT NULL,
    old_value jsonb,
    new_value jsonb,
    source text NOT NULL,
    conversation_id text,
    claimant_text text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Saved before the claim row exists, so this does not reference claim_document.
CREATE TABLE claims.document_extraction (
    document_id text NOT NULL,
    sha256 text NOT NULL,
    extractor_version text NOT NULL,
    doc_class text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, sha256, extractor_version)
);

CREATE TABLE claims.claim_status_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL REFERENCES claims.claim (claim_id),
    from_status text,
    to_status text NOT NULL,
    actor text NOT NULL,
    reason_code text,
    reason text,
    details jsonb,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE claims.outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id uuid NOT NULL UNIQUE,
    routing_key text NOT NULL,
    claim_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);

CREATE INDEX outbox_unpublished ON claims.outbox (id) WHERE published_at IS NULL;

CREATE TABLE claims.intake_error (
    message_id uuid PRIMARY KEY,
    submission_id text,
    error_class text NOT NULL,
    error text NOT NULL,
    attempts integer NOT NULL,
    dead_lettered_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE TABLE claims.audit_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    actor_role text NOT NULL,
    action text NOT NULL,
    claim_id text,
    submission_id text,
    correlation_id text,
    reason text,
    details jsonb
);

CREATE FUNCTION claims.reject_append_only_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER claim_status_history_append_only
    BEFORE UPDATE OR DELETE ON claims.claim_status_history
    FOR EACH ROW EXECUTE FUNCTION claims.reject_append_only_change();

CREATE TRIGGER claim_amendment_append_only
    BEFORE UPDATE OR DELETE ON claims.claim_amendment
    FOR EACH ROW EXECUTE FUNCTION claims.reject_append_only_change();

CREATE TRIGGER document_extraction_append_only
    BEFORE UPDATE OR DELETE ON claims.document_extraction
    FOR EACH ROW EXECUTE FUNCTION claims.reject_append_only_change();

CREATE TRIGGER audit_event_append_only
    BEFORE UPDATE OR DELETE ON claims.audit_event
    FOR EACH ROW EXECUTE FUNCTION claims.reject_append_only_change();

CREATE FUNCTION claims.reject_source_message_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_message IS DISTINCT FROM OLD.source_message THEN
        RAISE EXCEPTION 'source_message cannot change';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER claim_source_message_immutable
    BEFORE UPDATE ON claims.claim
    FOR EACH ROW EXECUTE FUNCTION claims.reject_source_message_change();

CREATE VIEW claims.claim_audit_trail AS
    SELECT claim_id, changed_at AS occurred_at, 'claim_status_history'::text AS source,
           concat_ws(' -> ', from_status, to_status) AS summary
    FROM claims.claim_status_history
    UNION ALL
    SELECT claim_id, created_at, 'claim_amendment', field_path
    FROM claims.claim_amendment
    UNION ALL
    SELECT claim_id, created_at, 'claim_issue', issue_code
    FROM claims.claim_issue
    UNION ALL
    SELECT d.claim_id, e.created_at, 'document_extraction', e.doc_class
    FROM claims.document_extraction AS e
    JOIN claims.claim_document AS d ON d.document_id = e.document_id
    UNION ALL
    SELECT claim_id, created_at, 'outbox', routing_key
    FROM claims.outbox
    WHERE claim_id IS NOT NULL
    UNION ALL
    SELECT claim_id, occurred_at, 'audit_event', action
    FROM claims.audit_event
    WHERE claim_id IS NOT NULL;

CREATE TABLE adjudication.payer_doc_chunk (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_type text NOT NULL,
    doc_id text NOT NULL,
    plan_code text,
    cpt_codes text[],
    section text,
    heading text,
    text text NOT NULL,
    embedding vector(768),
    CONSTRAINT payer_doc_chunk_doc_type CHECK (doc_type IN ('eoc', 'medical_policy'))
);

CREATE TABLE adjudication.review_tasks (
    task_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL,
    summary jsonb NOT NULL,
    risk_score numeric,
    status text NOT NULL,
    task_type text NOT NULL,
    assignee text,
    picked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_tasks_status CHECK (status IN ('OPEN', 'IN_REVIEW', 'DONE')),
    CONSTRAINT review_tasks_task_type CHECK (task_type IN ('REVIEW', 'INVESTIGATION'))
);

CREATE TABLE adjudication.adjudication_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL,
    adjudication_attempt integer NOT NULL,
    correlation_id text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    versions jsonb
);

CREATE FUNCTION adjudication.reject_append_only_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER adjudication_event_append_only
    BEFORE UPDATE OR DELETE ON adjudication.adjudication_event
    FOR EACH ROW EXECUTE FUNCTION adjudication.reject_append_only_change();

CREATE TABLE adjudication.outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id text NOT NULL UNIQUE,
    routing_key text NOT NULL,
    claim_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);

CREATE INDEX adjudication_outbox_unpublished ON adjudication.outbox (id) WHERE published_at IS NULL;

CREATE TABLE fraud.fraud_assessment (
    assessment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL,
    model_version text NOT NULL,
    risk_score numeric,
    band text,
    verdict text,
    confidence numeric,
    fact_sheet jsonb,
    narrative jsonb,
    narrative_source text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fraud.provider_stats (
    npi text NOT NULL,
    as_of date NOT NULL,
    specialty text,
    features jsonb NOT NULL DEFAULT '{}',
    provider_risk numeric,
    PRIMARY KEY (npi, as_of)
);

CREATE TABLE fraud.cpt_stats (
    cpt_code text NOT NULL,
    as_of date NOT NULL,
    p50_units numeric,
    p99_units numeric,
    p50_billed numeric,
    p99_billed numeric,
    PRIMARY KEY (cpt_code, as_of)
);

CREATE TABLE fraud.dx_cpt_cooccurrence (
    icd10 text NOT NULL,
    cpt_code text NOT NULL,
    prob numeric NOT NULL,
    PRIMARY KEY (icd10, cpt_code)
);

CREATE TABLE fraud.excluded_provider (
    npi text PRIMARY KEY,
    excluded_from date NOT NULL,
    reason text NOT NULL
);

CREATE TABLE fraud.fraud_label (
    label_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL,
    outcome text NOT NULL,
    scheme text,
    source text NOT NULL,
    labelled_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fraud.referral_memo (
    memo_id text PRIMARY KEY,
    claim_id text NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fraud.assistant_log (
    log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL,
    question text NOT NULL,
    answer text NOT NULL,
    tools_used jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chatbot.conversation (
    claim_id text PRIMARY KEY,
    submitter_id text NOT NULL,
    conversation_id text NOT NULL,
    respond_by timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chatbot.message (
    message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL REFERENCES chatbot.conversation (claim_id),
    role text NOT NULL,
    text text NOT NULL,
    issue_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT message_role CHECK (role IN ('assistant', 'user'))
);

CREATE INDEX message_claim_id_idx ON chatbot.message (claim_id, message_id);

CREATE TABLE chatbot.inquiry_conversation (
    member_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chatbot.inquiry_message (
    message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id text NOT NULL REFERENCES chatbot.inquiry_conversation (member_id),
    role text NOT NULL,
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT inquiry_message_role CHECK (role IN ('assistant', 'user'))
);

CREATE INDEX inquiry_message_member_id_idx ON chatbot.inquiry_message (member_id, message_id);

RESET ROLE;

GRANT CONNECT ON DATABASE claimsai TO payer_app;
GRANT USAGE ON SCHEMA claims TO payer_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA claims TO payer_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA claims TO payer_app;

REVOKE UPDATE, DELETE ON
    claims.claim_status_history,
    claims.claim_amendment,
    claims.document_extraction,
    claims.audit_event
FROM payer_app;

GRANT SELECT, INSERT ON
    claims.claim_status_history,
    claims.claim_amendment,
    claims.document_extraction,
    claims.audit_event
TO payer_app;

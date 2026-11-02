-- Additive chatbot log. Does not drop the existing schemas.
CREATE SCHEMA IF NOT EXISTS chatbot AUTHORIZATION claims_owner;

SET ROLE claims_owner;

CREATE TABLE IF NOT EXISTS chatbot.conversation (
    claim_id text PRIMARY KEY,
    submitter_id text NOT NULL,
    conversation_id text NOT NULL,
    respond_by timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chatbot.message (
    message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id text NOT NULL REFERENCES chatbot.conversation (claim_id),
    role text NOT NULL,
    text text NOT NULL,
    issue_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT message_role CHECK (role IN ('assistant', 'user'))
);

CREATE INDEX IF NOT EXISTS message_claim_id_idx ON chatbot.message (claim_id, message_id);

RESET ROLE;

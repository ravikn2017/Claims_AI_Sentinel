-- Member inquiry log. Separate from the missing-info conversation, which stays keyed by claim_id.
CREATE SCHEMA IF NOT EXISTS chatbot AUTHORIZATION claims_owner;

SET ROLE claims_owner;

CREATE TABLE IF NOT EXISTS chatbot.inquiry_conversation (
    member_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chatbot.inquiry_message (
    message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id text NOT NULL REFERENCES chatbot.inquiry_conversation (member_id),
    role text NOT NULL,
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT inquiry_message_role CHECK (role IN ('assistant', 'user'))
);

CREATE INDEX IF NOT EXISTS inquiry_message_member_id_idx ON chatbot.inquiry_message (member_id, message_id);

RESET ROLE;

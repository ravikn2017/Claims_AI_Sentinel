-- Adjudicator outbox and append-only adjudication events. Does not drop schemas.
SET ROLE claims_owner;

CREATE OR REPLACE FUNCTION adjudication.reject_append_only_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS adjudication_event_append_only ON adjudication.adjudication_event;
CREATE TRIGGER adjudication_event_append_only
    BEFORE UPDATE OR DELETE ON adjudication.adjudication_event
    FOR EACH ROW EXECUTE FUNCTION adjudication.reject_append_only_change();

CREATE TABLE IF NOT EXISTS adjudication.outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id text NOT NULL UNIQUE,
    routing_key text NOT NULL,
    claim_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);

CREATE INDEX IF NOT EXISTS adjudication_outbox_unpublished ON adjudication.outbox (id) WHERE published_at IS NULL;

RESET ROLE;

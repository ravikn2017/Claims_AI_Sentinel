-- Login accounts. Safe to run on a database that already has the other tables.
SET ROLE claims_owner;

CREATE TABLE IF NOT EXISTS portal.app_user (
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

CREATE TABLE IF NOT EXISTS portal.login_session (
    token text PRIMARY KEY,
    user_id text NOT NULL REFERENCES portal.app_user (user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

RESET ROLE;

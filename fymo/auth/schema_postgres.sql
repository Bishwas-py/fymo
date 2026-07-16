-- Postgres translation of schema.sql: same columns, same semantics. Every
-- object is prefixed fymo_ because this schema lives inside the app's own
-- database, next to app tables. Add columns via app-level migrations; fymo
-- will not destructively touch these tables once created.

CREATE TABLE IF NOT EXISTS fymo_users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT NOT NULL,
    password_hash   TEXT,         -- NULL for OAuth-only users
    email_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TEXT NOT NULL,
    fymo_uid        TEXT,         -- anonymous uid this user claimed on first login
    session_epoch   INTEGER NOT NULL DEFAULT 1, -- bumped to revoke outstanding sessions
    email_verify_token    TEXT,   -- hash of the outstanding verification token, NULL once consumed
    email_verify_sent_at  TEXT,   -- when the last verification email was sent
    password_reset_token  TEXT    -- hash of the outstanding password-reset token, NULL once consumed
);

-- Case-insensitive uniqueness (get_by_email compares lower(email) too).
-- Stricter than SQLite's UNIQUE COLLATE NOCASE: lower() folds per the
-- database locale while NOCASE folds ASCII only, so non-ASCII spellings
-- that coexist in a SQLite auth.db collide here (see the module docstring
-- of postgres_store.py).
CREATE UNIQUE INDEX IF NOT EXISTS fymo_users_email_lower_idx
    ON fymo_users (lower(email));

CREATE TABLE IF NOT EXISTS fymo_user_oauth_identities (
    user_id           BIGINT NOT NULL REFERENCES fymo_users(id),
    provider          TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    email             TEXT,
    linked_at         TEXT NOT NULL,
    PRIMARY KEY (provider, provider_user_id)
);

-- Minimal user schema. Add columns via app-level migrations; fymo will not
-- destructively touch this table once created.

CREATE TABLE IF NOT EXISTS fymo_users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT,         -- NULL for OAuth-only users (PR 3)
    email_verified  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    fymo_uid        TEXT,         -- anonymous uid this user claimed on first login
    session_epoch   INTEGER NOT NULL DEFAULT 1, -- bumped to revoke outstanding sessions
    email_verify_token    TEXT,   -- hash of the outstanding verification token, NULL once consumed
    email_verify_sent_at  TEXT,   -- when the last verification email was sent
    password_reset_token  TEXT    -- hash of the outstanding password-reset token, NULL once consumed
);

CREATE INDEX IF NOT EXISTS idx_fymo_users_email ON fymo_users(email);

-- Created here so the schema migration is one-shot; not populated until PR 3.
CREATE TABLE IF NOT EXISTS fymo_user_oauth_identities (
    user_id           INTEGER NOT NULL REFERENCES fymo_users(id),
    provider          TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    email             TEXT,
    linked_at         TEXT NOT NULL,
    PRIMARY KEY (provider, provider_user_id)
);

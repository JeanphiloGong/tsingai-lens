-- +goose Up
ALTER TABLE users
    ADD COLUMN email_verified_at TIMESTAMPTZ;

CREATE TABLE email_challenges (
    challenge_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('register', 'password_reset')),
    code_digest BYTEA NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'sent', 'consumed', 'failed')),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (email, purpose)
);

CREATE TABLE auth_rate_limits (
    key TEXT PRIMARY KEY,
    used INTEGER NOT NULL,
    reset_at TIMESTAMPTZ NOT NULL
);

-- +goose Down
DROP TABLE auth_rate_limits;
DROP TABLE email_challenges;
ALTER TABLE users
    DROP COLUMN email_verified_at;

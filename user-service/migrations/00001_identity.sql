-- +goose Up
CREATE TABLE users (
    user_id TEXT PRIMARY KEY CHECK (length(user_id) BETWEEN 1 AND 64),
    email TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX sessions_user_idx ON sessions(user_id);

-- +goose Down
DROP TABLE sessions;
DROP TABLE users;

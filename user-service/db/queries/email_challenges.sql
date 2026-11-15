-- name: LockEmail :exec
SELECT pg_advisory_xact_lock(hashtextextended(sqlc.arg(email)::text, 0));

-- name: ReserveRate :one
INSERT INTO auth_rate_limits (
    key,
    used,
    reset_at
)
VALUES (
    sqlc.arg(key),
    1,
    now() + sqlc.arg(seconds)::int * interval '1 second'
)
ON CONFLICT (key) DO UPDATE SET
    used = CASE
        WHEN auth_rate_limits.reset_at <= now() THEN 1
        ELSE auth_rate_limits.used + 1
    END,
    reset_at = CASE
        WHEN auth_rate_limits.reset_at <= now() THEN EXCLUDED.reset_at
        ELSE auth_rate_limits.reset_at
    END
RETURNING
    used,
    reset_at;

-- name: PutChallenge :exec
INSERT INTO email_challenges (
    challenge_id,
    email,
    purpose,
    code_digest,
    state,
    expires_at
)
VALUES (
    $1,
    $2,
    $3,
    $4,
    'pending',
    now() + interval '10 minutes'
)
ON CONFLICT (email, purpose) DO UPDATE SET
    challenge_id = EXCLUDED.challenge_id,
    code_digest = EXCLUDED.code_digest,
    state = 'pending',
    expires_at = EXCLUDED.expires_at,
    attempts = 0,
    created_at = now();

-- name: MarkSent :execrows
UPDATE email_challenges
SET
    state = 'sent',
    expires_at = now() + interval '10 minutes'
WHERE challenge_id = $1
    AND state = 'pending';

-- name: MarkFailed :exec
UPDATE email_challenges
SET state = 'failed'
WHERE challenge_id = $1
    AND state = 'pending';

-- name: ChallengeByEmail :one
SELECT *
FROM email_challenges
WHERE email = $1
    AND purpose = $2
FOR UPDATE;

-- name: WrongAttempt :exec
UPDATE email_challenges
SET attempts = attempts + 1
WHERE challenge_id = $1
    AND attempts < 5;

-- name: ConsumeChallenge :exec
UPDATE email_challenges
SET state = 'consumed'
WHERE challenge_id = $1;

-- name: RegisterUser :exec
INSERT INTO users (
    user_id,
    email,
    display_name,
    password_hash,
    email_verified_at
)
VALUES (
    $1,
    $2,
    $3,
    $4,
    now()
);

-- name: CanResetEmail :one
SELECT EXISTS (
    SELECT 1
    FROM users
    WHERE email = $1
        AND active
        AND email_verified_at IS NOT NULL
);

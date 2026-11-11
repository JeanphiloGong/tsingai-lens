-- name: UserByEmail :one
SELECT * FROM users WHERE email=$1 FOR UPDATE;
-- name: UserByID :one
SELECT * FROM users WHERE user_id=$1 FOR UPDATE;
-- name: AddUser :exec
INSERT INTO users(user_id,email,display_name,password_hash) VALUES($1,$2,$3,$4);
-- name: AddSession :exec
INSERT INTO sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '24 hours');
-- name: SessionByTokenHash :one
SELECT u.user_id,u.email,u.display_name,u.active,s.expires_at,s.revoked_at
FROM users u JOIN sessions s USING(user_id) WHERE s.token_hash=$1;
-- name: Revoke :exec
UPDATE sessions SET revoked_at=now() WHERE token_hash=$1;
-- name: RevokeUser :exec
UPDATE sessions SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL;
-- name: SetActive :exec
UPDATE users SET active=$2 WHERE user_id=$1;
-- name: SetPassword :exec
UPDATE users SET password_hash=$2 WHERE user_id=$1;

-- name: LockBootstrap :exec
SELECT pg_advisory_xact_lock(726103);
-- name: CountUsers :one
SELECT count(*) FROM users;

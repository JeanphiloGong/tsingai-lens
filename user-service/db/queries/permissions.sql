-- name: ListPermissions :many
SELECT DISTINCT p.permission_code
FROM group_permissions p
JOIN user_groups g USING (group_code)
JOIN users u USING (user_id)
WHERE u.user_id = $1
    AND u.active
ORDER BY p.permission_code;

-- name: LockAdministration :exec
SELECT pg_advisory_xact_lock(726103);

-- name: CountAdmins :one
SELECT count(DISTINCT u.user_id)
FROM users u
JOIN user_groups g USING (user_id)
JOIN group_permissions p USING (group_code)
WHERE u.active
    AND p.permission_code = 'users.manage';

-- name: Audit :exec
INSERT INTO auth_audit (
    actor_id,
    target_type,
    target_id,
    action,
    details
)
VALUES (
    $1,
    $2,
    $3,
    $4,
    $5
);

-- name: UsersPage :many
SELECT
    user_id,
    email,
    display_name,
    active
FROM users
ORDER BY email
LIMIT sqlc.arg(page_limit)::bigint
OFFSET sqlc.arg(page_offset)::bigint;

-- name: UserGroupsPage :many
SELECT g.*
FROM groups g
JOIN user_groups u ON u.group_code = g.code
WHERE u.user_id = sqlc.arg(user_id)
ORDER BY g.code
LIMIT sqlc.arg(page_limit)::bigint
OFFSET sqlc.arg(page_offset)::bigint;

-- name: CountUserGroups :one
SELECT count(*)
FROM user_groups
WHERE user_id = $1;

-- name: GrantGroup :exec
INSERT INTO user_groups (
    user_id,
    group_code
)
VALUES (
    $1,
    $2
)
ON CONFLICT DO NOTHING;

-- name: RevokeGroup :exec
DELETE FROM user_groups
WHERE user_id = $1
    AND group_code = $2;

-- name: GroupPermissionsPage :many
SELECT p.*
FROM permissions p
JOIN group_permissions g ON g.permission_code = p.code
WHERE g.group_code = sqlc.arg(group_code)
ORDER BY p.code
LIMIT sqlc.arg(page_limit)::bigint
OFFSET sqlc.arg(page_offset)::bigint;

-- name: CountGroupPermissions :one
SELECT count(*)
FROM group_permissions
WHERE group_code = $1;

-- name: GrantPermission :exec
INSERT INTO group_permissions (
    group_code,
    permission_code
)
VALUES (
    $1,
    $2
)
ON CONFLICT DO NOTHING;

-- name: RevokePermission :exec
DELETE FROM group_permissions
WHERE group_code = $1
    AND permission_code = $2;

-- name: CountGroupUsers :one
SELECT count(*)
FROM user_groups
WHERE group_code = $1;

-- name: CountPermissionGroups :one
SELECT count(*)
FROM group_permissions
WHERE permission_code = $1;

-- name: RemoveGroupPermissions :exec
DELETE FROM group_permissions
WHERE group_code = $1;

-- name: GroupByCode :one
SELECT *
FROM groups
WHERE code = $1;

-- name: GroupsPage :many
SELECT *
FROM groups
ORDER BY code
LIMIT sqlc.arg(page_limit)::bigint
OFFSET sqlc.arg(page_offset)::bigint;

-- name: CountGroups :one
SELECT count(*)
FROM groups;

-- name: AddGroup :one
INSERT INTO groups (
    code,
    name,
    description
)
VALUES (
    $1,
    $2,
    $3
)
RETURNING *;

-- name: UpdateGroup :one
UPDATE groups
SET name = $2,
    description = $3
WHERE code = $1
RETURNING *;

-- name: DeleteGroup :exec
DELETE FROM groups
WHERE code = $1;

-- name: PermissionByCode :one
SELECT *
FROM permissions
WHERE code = $1;

-- name: PermissionsPage :many
SELECT *
FROM permissions
ORDER BY code
LIMIT sqlc.arg(page_limit)::bigint
OFFSET sqlc.arg(page_offset)::bigint;

-- name: CountPermissions :one
SELECT count(*)
FROM permissions;

-- name: AddPermission :one
INSERT INTO permissions (
    code,
    name,
    description
)
VALUES (
    $1,
    $2,
    $3
)
RETURNING *;

-- name: UpdatePermission :one
UPDATE permissions
SET name = $2,
    description = $3
WHERE code = $1
RETURNING *;

-- name: DeletePermission :exec
DELETE FROM permissions
WHERE code = $1;

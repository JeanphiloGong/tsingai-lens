-- +goose Up
ALTER TABLE groups
    ADD COLUMN name TEXT NOT NULL DEFAULT '',
    ADD COLUMN description TEXT NOT NULL DEFAULT '',
    ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE permissions
    ADD COLUMN name TEXT NOT NULL DEFAULT '',
    ADD COLUMN description TEXT NOT NULL DEFAULT '',
    ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT false;
UPDATE groups
SET name = code;
UPDATE permissions
SET name = code;
UPDATE groups
SET is_system = true,
    name = CASE code
        WHEN 'admin' THEN 'System administrator'
        WHEN 'annotator' THEN 'Annotator'
        WHEN 'reviewer' THEN 'Reviewer'
        WHEN 'publisher' THEN 'Publisher'
    END
WHERE code IN ('admin', 'annotator', 'reviewer', 'publisher');
UPDATE permissions
SET is_system = true
WHERE code IN (
    'users.manage',
    'research.read_all',
    'annotation.annotate',
    'annotation.review',
    'dataset.publish',
    'dataset.download'
);
ALTER TABLE groups
    ADD CONSTRAINT groups_code_format CHECK (length(code) BETWEEN 1 AND 64 AND code ~ '^[a-z][a-z0-9_]*$'),
    ADD CONSTRAINT groups_name_length CHECK (length(trim(name)) BETWEEN 1 AND 100),
    ADD CONSTRAINT groups_description_length CHECK (length(description) <= 1000);
ALTER TABLE permissions
    ADD CONSTRAINT permissions_code_format CHECK (length(code) BETWEEN 1 AND 128 AND code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
    ADD CONSTRAINT permissions_name_length CHECK (length(trim(name)) BETWEEN 1 AND 100),
    ADD CONSTRAINT permissions_description_length CHECK (length(description) <= 1000);
CREATE INDEX ix_group_permissions_permission ON group_permissions (permission_code);
CREATE INDEX ix_user_groups_group ON user_groups (group_code);
ALTER TABLE auth_audit
    ADD COLUMN target_type TEXT NOT NULL DEFAULT 'user',
    ADD COLUMN details JSONB NOT NULL DEFAULT '{}',
    ADD CONSTRAINT auth_audit_target_type CHECK (target_type IN ('user', 'group', 'permission'));
-- +goose Down
ALTER TABLE auth_audit DROP CONSTRAINT auth_audit_target_type,
    DROP COLUMN details, DROP COLUMN target_type;
DROP INDEX ix_user_groups_group;
DROP INDEX ix_group_permissions_permission;
ALTER TABLE permissions DROP CONSTRAINT permissions_description_length,
    DROP CONSTRAINT permissions_name_length, DROP CONSTRAINT permissions_code_format,
    DROP COLUMN is_system, DROP COLUMN description, DROP COLUMN name;
ALTER TABLE groups DROP CONSTRAINT groups_description_length,
    DROP CONSTRAINT groups_name_length, DROP CONSTRAINT groups_code_format,
    DROP COLUMN is_system, DROP COLUMN description, DROP COLUMN name;

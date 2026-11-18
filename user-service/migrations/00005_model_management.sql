-- +goose Up
INSERT INTO permissions (code, name, description, is_system)
VALUES ('models.manage', 'Model administration', 'Manage shared model connections and provider credentials', true);
INSERT INTO group_permissions (group_code, permission_code)
VALUES ('admin', 'models.manage');

-- +goose Down
-- +goose StatementBegin
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM group_permissions
        WHERE permission_code = 'models.manage' AND group_code <> 'admin'
    ) THEN
        RAISE EXCEPTION 'Remove custom model permission assignments explicitly before downgrade';
    END IF;
END $$;
-- +goose StatementEnd
DELETE FROM group_permissions WHERE group_code = 'admin' AND permission_code = 'models.manage';
DELETE FROM permissions WHERE code = 'models.manage';

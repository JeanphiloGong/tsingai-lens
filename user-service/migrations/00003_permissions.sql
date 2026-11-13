-- +goose Up
CREATE TABLE permissions (
    code TEXT PRIMARY KEY
);

CREATE TABLE groups (
    code TEXT PRIMARY KEY
);

CREATE TABLE group_permissions (
    group_code TEXT REFERENCES groups(code),
    permission_code TEXT REFERENCES permissions(code),
    PRIMARY KEY (group_code, permission_code)
);

CREATE TABLE user_groups (
    user_id TEXT REFERENCES users(user_id),
    group_code TEXT REFERENCES groups(code),
    PRIMARY KEY (user_id, group_code)
);

CREATE TABLE auth_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO permissions
VALUES
    ('users.manage'),
    ('research.read_all'),
    ('annotation.annotate'),
    ('annotation.review'),
    ('dataset.publish'),
    ('dataset.download');

INSERT INTO groups
VALUES
    ('admin'),
    ('annotator'),
    ('reviewer'),
    ('publisher');

INSERT INTO group_permissions
VALUES
    ('admin', 'users.manage'),
    ('annotator', 'research.read_all'),
    ('annotator', 'annotation.annotate'),
    ('reviewer', 'research.read_all'),
    ('reviewer', 'annotation.review'),
    ('publisher', 'research.read_all'),
    ('publisher', 'dataset.publish'),
    ('publisher', 'dataset.download');

-- +goose Down
DROP TABLE auth_audit;
DROP TABLE user_groups;
DROP TABLE group_permissions;
DROP TABLE groups;
DROP TABLE permissions;

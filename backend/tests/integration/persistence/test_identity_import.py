from pathlib import Path
import os
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from scripts.import_legacy_users import import_users


@pytest.fixture
def identity_databases():
    url = os.environ.get("LENS_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    options = conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://", 1))
    assert options["dbname"].endswith("_test"), "Only disposable test databases are allowed"
    names = [f"lens_import_{uuid.uuid4().hex[:10]}_{kind}_test" for kind in ("source", "target")]
    admin_url = make_conninfo(**(options | {"dbname": "postgres"}))
    created = []
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            for name in names:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
        source_url, target_url = [make_conninfo(**(options | {"dbname": name})) for name in names]
        with psycopg.connect(source_url) as source:
            source.execute("""CREATE TABLE auth_users (
                user_id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT,
                password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL
            ); CREATE TABLE auth_sessions (token_hash TEXT, user_id TEXT);""")
            source.execute("""INSERT INTO auth_users VALUES
                ('original-owner', 'owner@example.test', NULL, 'fixture-hash-owner', '2026-01-01T00:00:00Z'),
                ('original-reader', 'reader@example.test', 'Reader', 'fixture-hash-reader', '2026-01-02T00:00:00Z');
                INSERT INTO auth_sessions VALUES ('old-session', 'original-owner');""")
        with psycopg.connect(target_url) as target:
            migrations = Path(__file__).resolve().parents[4] / "user-service/migrations"
            for migration in sorted(migrations.glob("*.sql")):
                target.execute(migration.read_text().split("-- +goose Down")[0])
        yield source_url, target_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            for name in created:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_import_preserves_credentials_and_identity_without_reviving_sessions(identity_databases):
    source_url, target_url = identity_databases
    assert import_users(source_url, target_url) == 2
    with psycopg.connect(target_url) as target:
        assert target.execute("SELECT user_id, password_hash FROM users ORDER BY user_id").fetchall() == [
            ("original-owner", "fixture-hash-owner"), ("original-reader", "fixture-hash-reader")
        ]
        assert target.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert target.execute("SELECT count(*) FROM users WHERE email_verified_at IS NOT NULL").fetchone()[0] == 0
        assert target.execute("SELECT count(*) FROM user_groups").fetchone()[0] == 0
    with psycopg.connect(source_url) as source:
        assert source.execute("SELECT count(*) FROM auth_users").fetchone()[0] == 2
        assert source.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == 1


def test_import_refuses_an_initialized_target(identity_databases):
    source_url, target_url = identity_databases
    assert import_users(source_url, target_url) == 2
    with pytest.raises(RuntimeError, match="empty"):
        import_users(source_url, target_url)
    with psycopg.connect(target_url) as target:
        assert target.execute("SELECT count(*) FROM users").fetchone()[0] == 2


def test_invalid_source_rolls_back_the_entire_import(identity_databases):
    source_url, target_url = identity_databases
    with psycopg.connect(source_url) as source:
        source.execute("UPDATE auth_users SET email='Invalid@example.test' WHERE user_id='original-reader'")
    with pytest.raises(psycopg.errors.CheckViolation):
        import_users(source_url, target_url)
    with psycopg.connect(target_url) as target:
        assert target.execute("SELECT count(*) FROM users").fetchone()[0] == 0

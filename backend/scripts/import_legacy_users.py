"""One-time import after stopping every legacy Web/worker write source."""

import os

import psycopg
from psycopg.rows import dict_row


def import_users(source_url: str, target_url: str) -> int:
    with psycopg.connect(source_url, row_factory=dict_row) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        users = source.execute(
            "SELECT user_id, email, display_name, password_hash, created_at "
            "FROM auth_users ORDER BY user_id"
        ).fetchall()

    with psycopg.connect(target_url, row_factory=dict_row) as target:
        target.execute("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
        if target.execute("SELECT count(*) AS count FROM users").fetchone()["count"]:
            raise RuntimeError("Import requires an empty user-service account table.")
        for user in users:
            target.execute(
                "INSERT INTO users(user_id, email, display_name, password_hash, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user["user_id"], user["email"], user["display_name"] or "",
                 user["password_hash"], user["created_at"]),
            )
        actual = target.execute(
            "SELECT user_id, email, display_name, password_hash, created_at "
            "FROM users ORDER BY user_id"
        ).fetchall()
        expected = [{**user, "display_name": user["display_name"] or ""} for user in users]
        if actual != expected:
            raise RuntimeError("Imported account verification failed; transaction rolled back.")
    return len(users)


if __name__ == "__main__":
    try:
        count = import_users(os.environ["OLD_IDENTITY_DATABASE_URL"], os.environ["USER_DATABASE_URL"])
    except psycopg.Error:
        # Database diagnostics can include password hashes or account details.
        raise SystemExit("Import failed; the target transaction was rolled back.") from None
    print(f"Imported and verified {count} accounts; no sessions or email-verification claims copied.")

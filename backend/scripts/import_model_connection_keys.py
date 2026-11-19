"""Explicit offline import between Alembic 0100 and 0101; never used by HTTP."""
import asyncio
from math import isfinite
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import inspect, text
from infra.llm.model_credentials import decrypt_api_key, encrypt_api_key, load_master_key
from infra.persistence.database import DatabaseSettings, build_database_engine


async def import_keys(engine, master_key: bytes) -> int:
    async with engine.begin() as connection:
        await connection.execute(text("LOCK TABLE model_connections IN ACCESS EXCLUSIVE MODE"))
        columns = await connection.run_sync(lambda sync: {item["name"] for item in inspect(sync).get_columns("model_connections")})
        if "api_key_ref" not in columns:
            return 0
        rows = (await connection.execute(text("SELECT * FROM model_connections ORDER BY connection_id FOR UPDATE"))).mappings().all()
        imported = 0
        for row in rows:
            try:
                url = httpx.URL(row["base_url"])
                valid = (url.scheme in {"http", "https"} and url.host and not url.userinfo and not url.query and not url.fragment
                         and not any(char.isspace() for char in row["base_url"]) and len(row["base_url"]) <= 2048
                         and 1 <= len(row["display_name"].strip()) <= 100 and 1 <= len(row["model"].strip()) <= 200)
                for field in ("context_window_tokens", "max_output_tokens", "request_timeout_seconds"):
                    value = row[field]
                    valid = valid and (value is None or (value > 0 and isfinite(value)))
                if not valid:
                    raise ValueError("invalid configuration")
                reference = row["api_key_ref"]
                if reference is None:
                    if row["api_key_ciphertext"] is not None:
                        raise ValueError("unexpected key on a no-key connection")
                    continue
                if not reference.startswith("env:") or not reference[4:]:
                    raise ValueError("unknown key reference")
                key = os.environ[reference[4:]]
                if not 1 <= len(key.encode()) <= 8192 or "\r" in key or "\n" in key:
                    raise ValueError("invalid provider key")
                if row["api_key_ciphertext"] is not None:
                    if decrypt_api_key(master_key, row["connection_id"], row["api_key_ciphertext"]) != key:
                        raise ValueError("existing encrypted key differs")
                    continue
                ciphertext = encrypt_api_key(master_key, row["connection_id"], key)
                if decrypt_api_key(master_key, row["connection_id"], ciphertext) != key:
                    raise ValueError("credential verification failed")
            except (KeyError, ValueError, httpx.InvalidURL):
                raise RuntimeError("Provider key import failed; no credentials were changed") from None
            await connection.execute(text("""
                UPDATE model_connections SET api_key_ciphertext=:ciphertext
                WHERE connection_id=:connection_id
            """), {"ciphertext": ciphertext, "connection_id": row["connection_id"]})
            imported += 1
        return imported


async def main():
    engine = build_database_engine(DatabaseSettings())
    try:
        count = await import_keys(engine, load_master_key())
        print(f"Imported {count} provider credentials; run the final migration next.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

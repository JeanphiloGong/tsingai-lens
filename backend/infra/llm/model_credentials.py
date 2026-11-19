"""Authenticated provider credentials, bound to one connection ID."""
from functools import lru_cache
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from exceptions import ServiceUnavailableException

# Reads the master-key file once per process after a successful load.
@lru_cache(maxsize=1)
def load_master_key() -> bytes:
    try:
        key = Path(os.environ["LENS_MODEL_KEY_FILE"]).read_bytes()

        # checks that the file contains exactly 32 bytes before allowing the key to be returned
        if len(key) != 32:
            # Reject a key of the wrong length before use.
            raise ValueError("invalid master key length")
    # selects the error path for a file access error, missing environment variable, or invalid key length
    except (OSError, KeyError, ValueError):
        # replaces any of those covered failures with a consistent service-level error
        raise ServiceUnavailableException(
            "Model credentials are unavailable.",
            data={"code": "model_credentials_unavailable"},
        ) from None

    # returns the file contents after both the read and the 32-byte check succeed
    return key


# uses that key to encrypt an API key, binding the ciphertext to a particular `connection_id`
def encrypt_api_key(master_key: bytes, connection_id: str, api_key: str) -> bytes:
    # generates a fresh 12-byte nonce for the AES-GCM operation
    nonce = os.urandom(12)

    # constructs the additional authenticated data (AAD) that binds the encrypted API key to its connection and purpose
    aad = f"lens:model-connection:{connection_id}:api-key:v1".encode()

    # encrypts the API key and assembles the stored byte format
    return b"\x01" + nonce + AESGCM(master_key).encrypt(nonce, api_key.encode(), aad)


# Checks and decrypts the stored bytes, returning the original string on success.
def decrypt_api_key(master_key: bytes, connection_id: str, ciphertext: bytes) -> str:
    try:
        # checks the outer byte format before extracting the nonce and encrypted payload
        if not 30 <= len(ciphertext) <= 8221 or ciphertext[0] != 1:
            raise ValueError("invalid ciphertext format")

        # reconstructs the AAD used during encryption
        aad = f"lens:model-connection:{connection_id}:api-key:v1".encode()

        # authenticates and decrypts the payload
        return AESGCM(master_key).decrypt(ciphertext[1:13], ciphertext[13:], aad).decode()
    except (InvalidTag, ValueError, UnicodeError):
        raise ServiceUnavailableException(
            "Model credentials are unavailable.",
            data={"code": "model_credentials_unavailable"},
        ) from None


def provider_api_key(connection_id: str, ciphertext: bytes | None) -> str:
    if ciphertext is None:
        return "not-needed"
    return decrypt_api_key(load_master_key(), connection_id, ciphertext)


def provider_options(connection, *, default_timeout: float = 180.0) -> dict:
    return {
        "api_key": provider_api_key(connection.connection_id, connection.api_key_ciphertext),
        "base_url": connection.base_url,
        "timeout": connection.request_timeout_seconds or default_timeout,
        "max_retries": 0,
    }

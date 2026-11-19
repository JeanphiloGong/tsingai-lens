from pathlib import Path
import pytest
from exceptions import ServiceUnavailableException
from infra.llm.model_credentials import decrypt_api_key, encrypt_api_key, load_master_key


def test_authenticated_credentials_are_random_and_connection_bound():
    key = bytes(range(32))
    first = encrypt_api_key(key, "lab-a", "synthetic-provider-token")
    second = encrypt_api_key(key, "lab-a", "synthetic-provider-token")
    assert first != second
    assert decrypt_api_key(key, "lab-a", first) == "synthetic-provider-token"
    for wrong_key, identity, value in [
        (bytes(reversed(range(32))), "lab-a", first),
        (key, "lab-b", first),
        (key, "lab-a", first[:-1] + bytes([first[-1] ^ 1])),
        (key, "lab-a", b"broken"),
    ]:
        with pytest.raises(ServiceUnavailableException) as error:
            decrypt_api_key(wrong_key, identity, value)
        assert error.value.data["code"] == "model_credentials_unavailable"
        assert "synthetic-provider-token" not in str(error.value)


def test_master_key_must_exist_and_contain_32_raw_bytes(tmp_path, monkeypatch):
    path = tmp_path / "master-key"
    monkeypatch.setenv("LENS_MODEL_KEY_FILE", str(path))
    for value in (None, b"wrong-length", bytes(range(32))):
        load_master_key.cache_clear()
        if value is not None:
            path.write_bytes(value)
        if value is None or len(value) != 32:
            with pytest.raises(ServiceUnavailableException):
                load_master_key()
        else:
            assert load_master_key() == value
    load_master_key.cache_clear()

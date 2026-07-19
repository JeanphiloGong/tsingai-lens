from __future__ import annotations

from hashlib import sha256

import pytest

from infra.persistence.file.object_store import FileObjectStore


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def test_file_object_store_round_trips_verified_bytes(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    payload = b"immutable paper bytes"
    storage_key = "col_demo/input/paper.pdf"
    digest = _digest(payload)

    store.write(storage_key, payload, digest)

    assert store.read(storage_key, digest) == payload
    assert (tmp_path / "objects" / storage_key).read_bytes() == payload


def test_file_object_store_allows_an_idempotent_write(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    payload = b"same bytes"
    digest = _digest(payload)

    store.write("col_demo/input/paper.pdf", payload, digest)
    store.write("col_demo/input/paper.pdf", payload, digest)

    assert store.read("col_demo/input/paper.pdf", digest) == payload


def test_file_object_store_rejects_overwriting_immutable_bytes(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    original = b"original bytes"
    replacement = b"replacement bytes"
    storage_key = "col_demo/input/paper.pdf"
    store.write(storage_key, original, _digest(original))

    with pytest.raises(FileExistsError, match="immutable object already exists"):
        store.write(storage_key, replacement, _digest(replacement))

    assert store.read(storage_key, _digest(original)) == original


def test_file_object_store_rejects_a_write_hash_mismatch(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    storage_key = "col_demo/input/paper.pdf"

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.write(storage_key, b"paper bytes", "0" * 64)

    assert not (tmp_path / "objects" / storage_key).exists()


def test_file_object_store_detects_corrupt_bytes_on_read(tmp_path):
    root = tmp_path / "objects"
    store = FileObjectStore(root)
    payload = b"paper bytes"
    storage_key = "col_demo/input/paper.pdf"
    digest = _digest(payload)
    store.write(storage_key, payload, digest)
    (root / storage_key).write_bytes(b"tampered bytes")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.read(storage_key, digest)


def test_file_object_store_delete_is_idempotent(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    payload = b"paper bytes"
    storage_key = "col_demo/input/paper.pdf"
    digest = _digest(payload)
    store.write(storage_key, payload, digest)

    store.delete(storage_key)
    store.delete(storage_key)

    with pytest.raises(FileNotFoundError):
        store.read(storage_key, digest)


@pytest.mark.parametrize(
    "storage_key",
    [
        "",
        ".",
        "../outside.pdf",
        "/tmp/outside.pdf",
        "col_demo/../outside.pdf",
        "col_demo/./input/paper.pdf",
        "col_demo//input/paper.pdf",
        "col_demo\\input\\paper.pdf",
    ],
)
def test_file_object_store_rejects_invalid_storage_keys(tmp_path, storage_key):
    store = FileObjectStore(tmp_path / "objects")
    payload = b"paper bytes"

    with pytest.raises(ValueError, match="invalid storage key"):
        store.write(storage_key, payload, _digest(payload))


def test_file_object_store_rejects_symlink_escape(tmp_path):
    root = tmp_path / "objects"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = FileObjectStore(root)
    payload = b"paper bytes"

    with pytest.raises(ValueError, match="invalid storage key"):
        store.write("linked/paper.pdf", payload, _digest(payload))

    assert not (outside / "paper.pdf").exists()


def test_file_object_store_rejects_symlink_alias_inside_root(tmp_path):
    root = tmp_path / "objects"
    store = FileObjectStore(root)
    payload = b"paper bytes"
    digest = _digest(payload)
    store.write("real/paper.pdf", payload, digest)
    (root / "alias").symlink_to(root / "real", target_is_directory=True)

    with pytest.raises(ValueError, match="invalid storage key"):
        store.read("alias/paper.pdf", digest)


@pytest.mark.parametrize("digest", ["", "abc", "A" * 64, "g" * 64])
def test_file_object_store_rejects_invalid_sha256(tmp_path, digest):
    store = FileObjectStore(tmp_path / "objects")

    with pytest.raises(ValueError, match="invalid SHA-256"):
        store.write("col_demo/input/paper.pdf", b"paper bytes", digest)

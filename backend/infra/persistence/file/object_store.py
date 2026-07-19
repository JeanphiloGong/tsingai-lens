from __future__ import annotations

from hashlib import sha256 as hash_sha256
from pathlib import Path, PurePosixPath


class FileObjectStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def write(self, storage_key: str, payload: bytes, sha256: str) -> None:
        target = self._resolve(storage_key)
        self._verify(payload, sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            if target.read_bytes() == payload:
                return
            raise FileExistsError(
                f"immutable object already exists: {storage_key}"
            ) from None

    def read(self, storage_key: str, sha256: str) -> bytes:
        payload = self._resolve(storage_key).read_bytes()
        self._verify(payload, sha256)
        return payload

    def delete(self, storage_key: str) -> None:
        self._resolve(storage_key).unlink(missing_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        if not isinstance(storage_key, str) or not storage_key or "\\" in storage_key:
            raise ValueError("invalid storage key")
        key = PurePosixPath(storage_key)
        if key.is_absolute() or str(key) != storage_key or ".." in key.parts:
            raise ValueError("invalid storage key")
        candidate = self.root_dir / Path(*key.parts)
        target = candidate.resolve()
        try:
            target.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("invalid storage key") from exc
        if target == self.root_dir or target != candidate:
            raise ValueError("invalid storage key")
        return target

    def _verify(self, payload: bytes, expected_sha256: str) -> None:
        if (
            len(expected_sha256) != 64
            or expected_sha256.lower() != expected_sha256
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise ValueError("invalid SHA-256")
        if hash_sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("object SHA-256 mismatch")

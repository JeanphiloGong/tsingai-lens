from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def read_json(path: Path, default: T) -> T:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)

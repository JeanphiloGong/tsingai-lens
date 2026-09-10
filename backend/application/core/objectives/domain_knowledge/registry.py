"""Load recall vocabulary without making it a scientific decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


class MaterialMatchQuality(StrEnum):
    """How strongly two material labels can be related without Source proof."""

    EXACT = "exact"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class MaterialMatch:
    quality: MaterialMatchQuality
    left_key: str | None
    right_key: str | None
    matched_alias: str | None = None
    registry_version: str = "unknown"
    basis: str = "unregistered"


@dataclass(frozen=True)
class _MaterialEntry:
    entry_id: str
    canonical: str
    specificity: str
    aliases: tuple[str, ...]
    covers: tuple[str, ...]


@dataclass(frozen=True)
class _Registry:
    version: str
    entries: tuple[_MaterialEntry, ...]
    aliases: dict[str, _MaterialEntry]
    missing_values: frozenset[str]


_REGISTRY_PATH = Path(__file__).with_name("registry.json")


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text).casefold()
    text = "".join(
        character if character.isalnum() or character in "%+./-" else " "
        for character in text
    )
    return " ".join(text.split()).strip(" -./")


def _load_registry() -> _Registry:
    payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("objective domain registry must be a JSON object")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise RuntimeError("objective domain registry has no version")
    if payload.get("purpose") != "recall_only":
        raise RuntimeError("objective domain registry must be recall_only")
    raw_entries = payload.get("materials")
    if not isinstance(raw_entries, list):
        raise RuntimeError("objective domain registry materials must be a list")
    raw_missing_values = payload.get("missing_values")
    if not isinstance(raw_missing_values, list):
        raise RuntimeError("objective domain registry missing_values must be a list")
    missing_values = frozenset(_normalise(value) for value in raw_missing_values)
    if "" not in missing_values:
        raise RuntimeError("objective domain registry missing_values must include empty")
    entries: list[_MaterialEntry] = []
    aliases: dict[str, _MaterialEntry] = {}
    ids: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise RuntimeError("objective domain registry entry must be an object")
        entry_id = _normalise(raw_entry.get("id"))
        canonical = " ".join(str(raw_entry.get("canonical") or "").split()).strip()
        specificity = str(raw_entry.get("specificity") or "").strip().casefold()
        raw_aliases = raw_entry.get("aliases")
        if not entry_id or not canonical or specificity not in {"exact", "broad"}:
            raise RuntimeError("objective domain registry entry is incomplete")
        if entry_id in ids:
            raise RuntimeError(f"duplicate objective domain registry id: {entry_id}")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise RuntimeError(f"registry entry has no aliases: {entry_id}")
        entry = _MaterialEntry(
            entry_id=entry_id,
            canonical=canonical,
            specificity=specificity,
            aliases=tuple(
                alias
                for raw_alias in raw_aliases
                if (alias := _normalise(raw_alias))
            ),
            covers=tuple(
                cover
                for raw_cover in raw_entry.get("covers") or ()
                if (cover := _normalise(raw_cover))
            ),
        )
        if not entry.aliases:
            raise RuntimeError(f"registry entry has no usable aliases: {entry_id}")
        ids.add(entry_id)
        entries.append(entry)
        for alias in entry.aliases:
            previous = aliases.get(alias)
            if previous is not None and previous.entry_id != entry_id:
                raise RuntimeError(f"duplicate objective domain alias: {alias}")
            aliases[alias] = entry
    return _Registry(
        version=version,
        entries=tuple(entries),
        aliases=aliases,
        missing_values=missing_values,
    )


_REGISTRY = _load_registry()


def material_registry_version() -> str:
    return _REGISTRY.version


def material_identity_key(value: Any, *, include_broad: bool = True) -> str | None:
    """Return a stable registry key, or a literal key for unknown labels.

    Unknown labels are retained as literals so a new scientific domain is not
    silently discarded. Broad labels are omitted when callers need an exact
    identity for comparison/grouping.
    """

    normalised = _normalise(value)
    if normalised in _REGISTRY.missing_values:
        return None
    entry = _REGISTRY.aliases.get(normalised)
    if entry is not None:
        if entry.specificity == "broad" and not include_broad:
            return None
        return f"registry:{entry.entry_id}"
    return f"literal:{normalised}"


def material_match(left: Any, right: Any) -> MaterialMatch:
    left_normalised = _normalise(left)
    right_normalised = _normalise(right)
    left_key = material_identity_key(left)
    right_key = material_identity_key(right)
    if left_key is None or right_key is None:
        return MaterialMatch(
            MaterialMatchQuality.UNKNOWN,
            left_key,
            right_key,
            registry_version=_REGISTRY.version,
            basis="missing",
        )
    left_entry = _entry_for(left)
    right_entry = _entry_for(right)
    if left_normalised == right_normalised and left_entry is not None:
        quality = (
            MaterialMatchQuality.POSSIBLE
            if left_entry.specificity == "broad"
            else MaterialMatchQuality.EXACT
        )
        return MaterialMatch(
            quality,
            left_key,
            right_key,
            matched_alias=left_normalised,
            registry_version=_REGISTRY.version,
            basis="registered_literal",
        )
    if left_entry is not None and right_entry is not None:
        if left_entry.entry_id == right_entry.entry_id:
            quality = (
                MaterialMatchQuality.EXACT
                if left_entry.specificity == right_entry.specificity == "exact"
                else MaterialMatchQuality.POSSIBLE
            )
            return MaterialMatch(
                quality,
                left_key,
                right_key,
                matched_alias=left_entry.canonical,
                registry_version=_REGISTRY.version,
                basis="registered_alias",
            )
        if (
            left_entry.entry_id in right_entry.covers
            or right_entry.entry_id in left_entry.covers
        ):
            return MaterialMatch(
                MaterialMatchQuality.POSSIBLE,
                left_key,
                right_key,
                matched_alias=left_entry.canonical,
                registry_version=_REGISTRY.version,
                basis="registered_cover",
            )
        if left_entry.specificity == right_entry.specificity == "exact":
            return MaterialMatch(
                MaterialMatchQuality.CONFLICT,
                left_key,
                right_key,
                registry_version=_REGISTRY.version,
                basis="known_disjoint",
            )
    return MaterialMatch(
        MaterialMatchQuality.UNKNOWN,
        left_key,
        right_key,
        registry_version=_REGISTRY.version,
        basis="unregistered",
    )


def material_text_mentions(text: Any, target: Any) -> bool:
    """Return whether *text* explicitly contains a registered material label.

    This is a lexical recall helper only. It does not infer a material from a
    process, title, or objective; callers still need a source-local binding
    before treating the mention as evidence.
    """

    text_normalised = _normalise(text)
    target_normalised = _normalise(target)
    if not text_normalised or not target_normalised:
        return False
    entry = _entry_for(target)
    aliases = entry.aliases if entry is not None else (target_normalised,)
    for alias in aliases:
        alias_normalised = _normalise(alias)
        if not alias_normalised:
            continue
        if re.search(
            rf"(?<!\w){re.escape(alias_normalised)}(?!\w)",
            text_normalised,
        ):
            return True
    return False


def _entry_for(value: Any) -> _MaterialEntry | None:
    return _REGISTRY.aliases.get(_normalise(value))


__all__ = [
    "MaterialMatch",
    "MaterialMatchQuality",
    "material_identity_key",
    "material_match",
    "material_text_mentions",
    "material_registry_version",
]

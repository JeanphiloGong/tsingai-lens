from __future__ import annotations

from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher
import re
from typing import Any

from domain.core import ResearchObjective


# Materials-science outcome hints used to match broad Objectives to measurements.
_BROAD_OUTCOME_EXPANSIONS = {
    "densification": ("relative density",),
    "mechanical properties": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "mechanical property": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "corrosion properties": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passivation behavior",
    ),
    "corrosion property": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passivation behavior",
    ),
    "corrosion resistance": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passivation behavior",
    ),
    "pitting corrosion behavior": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passive film resistance",
        "passivation behavior",
    ),
    "pitting corrosion": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passive film resistance",
        "passivation behavior",
    ),
    "defect structure": (
        "defect complexity",
        "defect density",
        "defect diameter",
        "defect distribution",
        "max defect length",
        "max defect diameter",
        "max defect size",
        "defect length",
        "defect shape",
        "defect size",
        "porosity",
    ),
    "microstructure": (
        "cellular structure",
        "cellular-dendritic microstructure",
        "crystallographic texture",
        "grain morphology",
        "grain structure",
    ),
    "fatigue strength": (
        "fatigue limit",
        "fatigue strength at 10 4 cycles",
    ),
}

# Source labels include abbreviations, scientific symbols, and observed OCR forms.
_PROPERTY_LABEL_ALIASES = {
    "ductility": "elongation",
    "el": "elongation",
    "el%": "elongation",
    "elongation to failure": "elongation",
    "e corr": "corrosion potential",
    "ecorr": "corrosion potential",
    "e p": "pitting potential",
    "ep": "pitting potential",
    "fat 50": "fatigue limit",
    "fat 50 %": "fatigue limit",
    "fat50": "fatigue limit",
    "fat50 %": "fatigue limit",
    "fat at 10 4 cycles": "fatigue strength",
    "i corr": "corrosion current density",
    "icorr": "corrosion current density",
    "current density": "corrosion current density",
    "r film": "passive film resistance",
    "rfilm": "passive film resistance",
    "film resistance": "passive film resistance",
    "i u": "ultimate tensile strength",
    "iu": "ultimate tensile strength",
    "sigma u": "ultimate tensile strength",
    "ultimate tensile": "ultimate tensile strength",
    "uts": "ultimate tensile strength",
    "\u0131 u": "ultimate tensile strength",
    "\u0131u": "ultimate tensile strength",
    "\u03c3 u": "ultimate tensile strength",
    "\u03c3u": "ultimate tensile strength",
    "i y": "yield strength",
    "iy": "yield strength",
    "max. defect length": "max defect length",
    "max defect length lcsm": "max defect length",
    "max. defect diameter": "max defect diameter",
    "maximum defect diameter": "max defect diameter",
    "maximum defect size": "max defect size",
    "maximum defect length": "max defect length",
    "sigma y": "yield strength",
    "\u0131 y": "yield strength",
    "\u0131y": "yield strength",
    "\u03c3 y": "yield strength",
    "\u03c3y": "yield strength",
}

# These are contextual process-axis hints, not universal meanings for symbols.
_PROCESS_SYMBOL_AXIS_HINTS = {
    "alpha": ("build orientation alpha angle",),
    "\u03b1": ("build orientation alpha angle",),
    "beta": ("build orientation beta angle",),
    "\u03b2": ("build orientation beta angle",),
    "theta": ("scan strategy rotation angle",),
    "\u03b8": ("scan strategy rotation angle",),
    "\u0275": ("scan strategy rotation angle",),
    "ved": ("volumetric energy density", "energy density"),
}

_EXPLICIT_AXIS_SYNONYMS = {
    "base plate preheating temperature": (
        "base plate preheating",
        "baseplate preheating",
        "baseplate preheating temperature",
        "build platform preheating temperature",
        "preheating",
        "preheating temperature",
    ),
    "crack formation": (
        "cracking",
        "cracking behavior",
        "microcrack formation",
    ),
    "scan strategy": ("scanning strategy",),
    "scanning strategy": ("scan strategy",),
}
_STRUCTURAL_TARGET_AXES = frozenset(
    {"densification", "relative density", "microstructure"}
)
_DENSITY_PROPERTIES = frozenset({"density", "relative density"})
_GENERIC_RESULT_ROLE_TOKENS = frozenset(
    {
        "current",
        "evidence",
        "experimental",
        "measurement",
        "predicted",
        "prediction",
        "property",
        "result",
        "target",
    }
)
_GENERIC_PROCESS_ROLE_TOKENS = frozenset(
    {"axis", "context", "parameter", "process", "variable"}
)
_PRESERVED_PROPERTY_QUALIFIERS = frozenset(
    {"experiment", "experimental", "model", "predicted", "prediction"}
)
_SINGLE_TOKEN_PROPERTY_QUALIFIERS = frozenset(
    {"average", "material", "relative", "surface", "total", "uniform"}
)
_TENSILE_METHOD_PROPERTIES = frozenset(
    {
        "yield strength",
        "ultimate tensile strength",
        "tensile strength",
        "strength",
        "elongation",
        "modulus",
    }
)
_MICROHARDNESS_METHOD_PROPERTIES = frozenset({"hardness", "microhardness"})
_CHARACTERIZATION_METHOD_PROPERTIES = frozenset(
    {
        "density",
        "relative density",
        "densification",
        "porosity",
        "defect length",
        "defect structure",
        "grain size",
        "max defect length",
        "microstructure",
        "grain size primary dendrite spacing",
    }
)


def normalize_property_label(value: Any) -> str | None:
    text = _label_without_unit_suffix(value)
    text = text.replace("_", " ").replace("-", " ").strip()
    normalized = " ".join(text.split()).casefold()
    if not normalized:
        return None
    return _PROPERTY_LABEL_ALIASES.get(normalized, normalized)


def broad_outcome_expansions(value: Any) -> tuple[str, ...]:
    normalized = normalize_property_label(value)
    if not normalized:
        return ()
    return _BROAD_OUTCOME_EXPANSIONS.get(normalized, ())


def outcome_label_requires_resolution(value: Any) -> bool:
    outcome = " ".join(str(value or "").strip().casefold().split())
    if not outcome:
        return False
    if re.search(r"\b(?:and|versus)\b|\s[&/]\s", outcome):
        return True
    if re.search(r"\([^)]*(?:,|;|\band\b)[^)]*\)", outcome):
        return True
    words = outcome.split()
    return words[-1] in {
        "combination",
        "performance",
        "properties",
        "property",
    } or words[0] in {"combined", "comprehensive", "overall"}


def objective_outcomes(objective: ResearchObjective) -> tuple[str, ...]:
    axes: list[str] = []
    seen: set[str] = set()
    for axis in objective.outcomes:
        normalized = normalize_property_label(axis)
        if normalized:
            _append_unique_axis(axes, seen, normalized)
            for expanded in broad_outcome_expansions(normalized):
                _append_unique_axis(axes, seen, expanded)
        else:
            _append_unique_axis(axes, seen, axis)
    return tuple(axes)


def property_matches_target_axes(
    property_name: Any,
    *,
    target_axes: tuple[str, ...],
) -> bool:
    normalized = normalize_property_label(property_name)
    if not normalized:
        return False
    if property_label_matches_target(normalized, target_axes=target_axes):
        return True
    return any(
        property_label_matches_target(expanded_axis, target_axes=target_axes)
        for expanded_axis in broad_outcome_expansions(normalized)
    )


def property_label_matches_target(
    property_name: Any,
    *,
    target_axes: tuple[str, ...],
) -> bool:
    normalized = normalize_property_label(property_name)
    if not normalized:
        return False
    if any(axis_values_match(normalized, candidate) for candidate in target_axes):
        return True
    return _contextual_property_variant_match(
        normalized,
        target_axes=target_axes,
    ) is not None


def normalize_objective_unit_property(
    value: Any,
    *,
    objective_context: ResearchObjective | None,
) -> str | None:
    normalized = normalize_property_label(value)
    if not normalized:
        return None
    if objective_context is None:
        return normalized
    for target_axis in objective_context.outcomes:
        if axis_values_match(normalized, target_axis):
            return normalize_property_label(target_axis)
    target_axes = objective_outcomes(objective_context)
    if normalized in target_axes:
        return normalized
    variant_match = _contextual_property_variant_match(
        normalized,
        target_axes=target_axes,
    )
    if variant_match is not None:
        target_axis, extra_tokens = variant_match
        if extra_tokens & _PRESERVED_PROPERTY_QUALIFIERS:
            return normalized
        return normalize_property_label(target_axis) or normalized
    return normalized


def objective_method_families(
    objective: ResearchObjective | None,
) -> tuple[str, ...]:
    if objective is None:
        return ()
    families: list[str] = []
    for axis in objective.outcomes:
        normalized = normalize_property_label(axis)
        if not normalized:
            continue
        for property_name in (normalized, *broad_outcome_expansions(normalized)):
            family = _method_family_for_property(property_name)
            if family is not None:
                families.append(family)
    return tuple(dict.fromkeys(families))


def process_role_is_specific(role_label: str) -> bool:
    role_tokens = axis_tokens(role_label)
    return bool(role_tokens) and not role_tokens.issubset(
        _GENERIC_PROCESS_ROLE_TOKENS
    )


def result_role_is_specific_property(role_label: str) -> bool:
    role_tokens = axis_tokens(role_label)
    return bool(role_tokens) and not role_tokens.issubset(
        _GENERIC_RESULT_ROLE_TOKENS
    )


def process_column_axis_keys(value: Any) -> set[str]:
    column = _label_without_unit_suffix(value)
    column = " ".join(column.split()).casefold()
    if not column:
        return set()
    return {
        axis_key
        for alias in _PROCESS_SYMBOL_AXIS_HINTS.get(column, ())
        if (axis_key := normalize_property_label(alias))
    }


def density_property_matches_structural_target(
    property_name: str,
    *,
    target_axes: tuple[str, ...],
) -> bool:
    if property_name not in _DENSITY_PROPERTIES:
        return False
    return any(
        normalize_property_label(target_axis) in _STRUCTURAL_TARGET_AXES
        for target_axis in target_axes
    )


def source_text_mentions_axis(text: str, axis: str) -> bool:
    if _source_text_mentions_single_axis(text, axis):
        return True
    return any(
        _source_text_mentions_single_axis(text, expanded_axis)
        for expanded_axis in broad_outcome_expansions(axis)
    )


def axis_key_set(*values: Any) -> set[str]:
    return {axis_key(value) for value in values if axis_key(value)}


def axis_key(value: Any) -> str:
    text = _label_without_unit_suffix(value).casefold()
    if text.endswith(")") and "(" in text:
        base, _, suffix = text.rpartition("(")
        acronym = suffix[:-1].strip()
        if base.strip() and acronym.isalpha() and len(acronym) <= 8:
            text = base.strip()
    return " ".join(text.split())


def axis_alias_matches_canonical(alias: str, canonical: str) -> bool:
    alias_key = axis_key(alias)
    canonical_key = axis_key(canonical)
    if alias_key == canonical_key:
        return True
    if _is_acronym_match(alias_key, canonical_key):
        return True
    alias_tokens = axis_tokens(alias_key)
    canonical_tokens = axis_tokens(canonical_key)
    if not alias_tokens or not canonical_tokens:
        return False
    overlap = alias_tokens & canonical_tokens
    if len(overlap) / max(len(alias_tokens), len(canonical_tokens)) >= 0.75:
        return True
    if len(alias_tokens) != len(canonical_tokens):
        return False
    return all(
        any(
            _axis_token_is_close(alias_token, canonical_token)
            for canonical_token in canonical_tokens
        )
        for alias_token in alias_tokens
    ) and all(
        any(
            _axis_token_is_close(canonical_token, alias_token)
            for alias_token in alias_tokens
        )
        for canonical_token in canonical_tokens
    )


def axis_values_match(left: str, right: str) -> bool:
    if axis_alias_matches_canonical(left, right):
        return True
    left_key = normalize_property_label(left) or axis_key(left)
    right_key = normalize_property_label(right) or axis_key(right)
    return right_key in _EXPLICIT_AXIS_SYNONYMS.get(left_key, ()) or (
        left_key in _EXPLICIT_AXIS_SYNONYMS.get(right_key, ())
    )


def resolve_objective_axis(
    value: Any,
    objective_axes: Iterable[str],
) -> str | None:
    """Return the one confirmed Objective axis represented by a source label."""

    source = str(value or "").strip()
    if not source:
        return None
    axes = tuple(str(axis).strip() for axis in objective_axes if str(axis).strip())
    source_key = axis_key(source)
    exact_matches = tuple(axis for axis in axes if axis_key(axis) == source_key)
    if len(exact_matches) == 1:
        return exact_matches[0]
    matches = tuple(axis for axis in axes if axis_values_match(source, axis))
    if len(matches) == 1:
        return matches[0]
    return None


def axis_collections_are_equivalent(
    left: Iterable[str],
    right: Iterable[str],
) -> bool:
    unmatched = [str(value) for value in right]
    left_values = [str(value) for value in left]
    if len(left_values) != len(unmatched):
        return False
    for left_value in left_values:
        match_position = next(
            (
                position
                for position, right_value in enumerate(unmatched)
                if axis_values_match(left_value, right_value)
            ),
            None,
        )
        if match_position is None:
            return False
        unmatched.pop(match_position)
    return True


def paper_signal_context_conflicts(
    signals: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    signal_values = tuple(signals)
    conflicts: list[str] = []
    for field_name in (
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
    ):
        contexts = [
            tuple(str(value) for value in signal.get(field_name) or ())
            for signal in signal_values
            if signal.get(field_name)
        ]
        if any(
            not axis_collections_are_equivalent(left, right)
            for position, left in enumerate(contexts)
            for right in contexts[position + 1 :]
        ):
            conflicts.append(field_name)
    for field_name in ("experiment_label", "comparator"):
        values = {
            axis_key(signal.get(field_name))
            for signal in signal_values
            if signal.get(field_name)
        }
        if len(values) > 1:
            conflicts.append(field_name)
    for field_name in ("design_type", "claim_scope"):
        values = {
            str(signal.get(field_name))
            for signal in signal_values
            if signal.get(field_name) not in (None, "", "uncertain")
        }
        if len(values) > 1:
            conflicts.append(field_name)
    return tuple(conflicts)


def axis_label_is_mentioned(text: str, axis: str) -> bool:
    text_tokens = axis_tokens(axis_key(text))
    axis_token_values = axis_tokens(axis_key(axis))
    return bool(axis_token_values and axis_token_values.issubset(text_tokens))


def axis_tokens(value: str) -> set[str]:
    return {
        _normalize_axis_token(token)
        for token in (
            value.replace("_", " ").replace("-", " ").replace("/", " ").split()
        )
        if _normalize_axis_token(token)
    }


def _contextual_property_variant_match(
    property_name: str,
    *,
    target_axes: tuple[str, ...],
) -> tuple[str, set[str]] | None:
    property_tokens = axis_tokens(axis_key(property_name))
    if not property_tokens:
        return None
    for target_axis in target_axes:
        target_key = normalize_property_label(target_axis)
        if not target_key:
            continue
        target_tokens = axis_tokens(axis_key(target_key))
        if (
            not target_tokens
            or target_tokens == property_tokens
            or not target_tokens.issubset(property_tokens)
        ):
            continue
        extra_tokens = property_tokens - target_tokens
        if len(target_tokens) >= 2:
            return target_key, extra_tokens
        if target_tokens == {"density"}:
            if extra_tokens.issubset(
                {"archimede", "archimedes", "material", "method", "relative"}
            ):
                return target_key, extra_tokens
            continue
        if extra_tokens and extra_tokens.issubset(_SINGLE_TOKEN_PROPERTY_QUALIFIERS):
            return target_key, extra_tokens
    return None


def _source_text_mentions_single_axis(text: str, axis: str) -> bool:
    normalized_axis = normalize_property_label(axis)
    if normalized_axis in _DENSITY_PROPERTIES:
        text = re.sub(
            r"\b(?:(?:laser|volumetric)\s+)?energy\s+densit(?:y|ies)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
    text_tokens = axis_tokens(axis_key(text))
    axis_token_values = axis_tokens(axis_key(axis))
    if not axis_token_values or not text_tokens:
        return False
    if normalized_axis:
        for alias, canonical_axes in _PROCESS_SYMBOL_AXIS_HINTS.items():
            alias_tokens = axis_tokens(alias)
            if alias_tokens and alias_tokens.issubset(text_tokens) and any(
                axis_values_match(normalized_axis, canonical_axis)
                for canonical_axis in canonical_axes
            ):
                return True
        for alias, canonical in _PROPERTY_LABEL_ALIASES.items():
            if canonical != normalized_axis:
                continue
            alias_tokens = axis_tokens(alias)
            if alias_tokens and alias_tokens.issubset(text_tokens):
                return True
    return all(
        any(
            axis_token == text_token
            or _is_acronym_match(axis_token, text_token)
            or _axis_token_is_close(axis_token, text_token)
            for text_token in text_tokens
        )
        for axis_token in axis_token_values
    )


def _method_family_for_property(property_name: Any) -> str | None:
    normalized = normalize_property_label(property_name)
    if not normalized:
        return None
    if normalized in _TENSILE_METHOD_PROPERTIES:
        return "tensile_mechanics"
    if normalized in _MICROHARDNESS_METHOD_PROPERTIES:
        return "microhardness"
    if normalized in _CHARACTERIZATION_METHOD_PROPERTIES:
        return "density_porosity_microstructure"
    return None


def _label_without_unit_suffix(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
    text = re.sub(r"\s*\((?:LCSM|EBSD)\)\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s*(?:\[[^\]]*\]|\([^)]*\))\s*$", "", text).strip()


def _axis_token_is_close(left: str, right: str) -> bool:
    if left == right:
        return True
    if left.startswith("dens") and right.startswith("dens"):
        return True
    if abs(len(left) - len(right)) > 2:
        return False
    if len(left) < 6 or len(right) < 6:
        return False
    return SequenceMatcher(a=left, b=right).ratio() >= 0.88


def _is_acronym_match(left: str, right: str) -> bool:
    for short, long in ((left, right), (right, left)):
        if len(short) < 2 or len(short) > 8 or not short.isalpha():
            continue
        acronym = "".join(token[0] for token in long.split() if token)
        if acronym and short == acronym:
            return True
    return False


def _normalize_axis_token(token: str) -> str:
    normalized = "".join(char for char in token.casefold() if char.isalnum())
    if len(normalized) > 5 and normalized.endswith("ing"):
        normalized = normalized[:-3]
        if len(normalized) >= 2 and normalized[-1] == normalized[-2]:
            normalized = normalized[:-1]
    if len(normalized) > 4 and normalized.endswith("ies"):
        normalized = f"{normalized[:-3]}y"
    elif len(normalized) > 3 and normalized.endswith("s"):
        normalized = normalized[:-1]
    return normalized


def _append_unique_axis(target: list[str], seen: set[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    key = axis_key(text)
    if key in seen:
        return
    seen.add(key)
    target.append(text)

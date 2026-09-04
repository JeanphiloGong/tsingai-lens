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
    "tensile properties": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
    ),
    "tensile property": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
    ),
    "anisotropic mechanical properties": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "anisotropic mechanical property": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "mechanical property anisotropy": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "microstructural anisotropy": (
        "cellular structure",
        "grain morphology",
        "grain orientation",
        "grain structure",
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
        "grain arrangement",
        "grain morphology",
        "grain orientation",
        "grain size",
        "grain structure",
        "lamellae width",
        "lamellar structure",
        "martensite decomposition",
        "martensite lamellae thickness",
        "phase composition",
        "phase fraction",
        "phase transformation",
    ),
    "fatigue strength": (
        "fatigue limit",
        "fatigue strength at 10 4 cycles",
    ),
}

# These labels describe multiple scientifically distinct measurements or
# observations. They are useful for screening, but not precise outcome axes.
_MULTI_MEASUREMENT_OUTCOME_FAMILIES = frozenset(
    {
        "mechanical properties",
        "mechanical property",
        "tensile properties",
        "tensile property",
        "anisotropic mechanical properties",
        "anisotropic mechanical property",
        "corrosion properties",
        "corrosion property",
        "corrosion resistance",
        "pitting corrosion behavior",
        "pitting corrosion",
        "defect structure",
        "microstructure",
    }
)

# These are linguistic umbrella heads, not scientific outcome names.  A
# question such as "fatigue behaviour" may be answered only by preserving the
# paper's concrete result (for example, fatigue life or fatigue strength).
# The source label remains the published result; this helper only decides
# whether it belongs in the paper-scoped review set.
_OUTCOME_UMBRELLA_HEADS = frozenset(
    {
        "behavior",
        "behaviour",
        "performance",
        "response",
        "property",
        "properties",
    }
)

# Source labels include abbreviations, scientific symbols, and observed OCR forms.
_PROPERTY_LABEL_ALIASES = {
    "ductility": "elongation",
    "el": "elongation",
    "el%": "elongation",
    "elongation to failure": "elongation",
    "te": "total elongation",
    "te%": "total elongation",
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
    "porosity volume fraction": "porosity",
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

# Fatigue strength is commonly reported with the cycle regime in the prose
# ("high-cycle fatigue strength") but with an operational cycle count in a
# table header ("fatigue strength at 10^4 cycles").  Keep the regime qualifier
# when it is explicit; an unqualified measurement is a family match only and
# must retain its source label for later context validation.
_FATIGUE_STRENGTH_VARIANT_RE = re.compile(
    r"^(?:(?P<regime>low|high|very\s+high|ultra\s+high)\s+cycle\s+)?"
    r"fatigue\s+strength(?:\s+at\s+.+?\s+cycles?)?$",
    re.IGNORECASE,
)
_FATIGUE_STRENGTH_TEXT_RE = re.compile(
    r"\b(?:(?P<regime>low|high|very\s+high|ultra\s+high)[-\s]+cycle\s+)?"
    r"fatigue\s+strength(?:\s+at\s+[^.;,|\n]+?\s+cycles?)?\b"
    r"|\bFAT\s+at\s+[^.;,|\n]+?\s+cycles?\b",
    re.IGNORECASE,
)

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

# A paper may expose a broad experimental axis through symbol-qualified
# columns.  These aliases are only for deciding whether a Source axis belongs
# to the confirmed Objective; they do not make the underlying variables
# interchangeable for comparison.
_PROCESS_AXIS_SCOPE_ALIASES = {
    "scan strategy rotation angle": (
        "scan strategy",
        "scanning strategy",
    ),
    "build orientation alpha angle": (
        "build orientation",
        "build orientation angle",
    ),
    "build orientation beta angle": (
        "build orientation",
        "build orientation angle",
    ),
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

# Objective discovery may use these bounded intervention themes to collect
# related paper-owned experiments. Theme membership is deliberately separate
# from axis equivalence: an annealing temperature and a HIP temperature belong
# to one thermal post-processing question, but remain different variables when
# Evidence is compared.
_VARIABLE_THEME_PATTERNS = (
    (
        "hot isostatic pressing condition",
        re.compile(r"\b(?:hip|hot isostatic press(?:ing|ed)?)\b", re.IGNORECASE),
    ),
    (
        "heat treatment condition",
        re.compile(
            r"\b(?:heat treatment|anneal(?:ing|ed)?|ag(?:e|ed|ing)|"
            r"ageing|solution treatment|solutioniz(?:e|ed|ing)|"
            r"solution (?:temperature|time|duration)|"
            r"solubility (?:temperatures?|time|duration))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "thermal post-processing condition",
        re.compile(
            r"\b(?:thermal post[- ]?process(?:ing)?|hip|"
            r"hot isostatic press(?:ing|ed)?|heat treatment|"
            r"anneal(?:ing|ed)?|ag(?:e|ed|ing)|ageing|solution treatment|"
            r"solutioniz(?:e|ed|ing)|solution (?:temperature|time|duration)|"
            r"solubility (?:temperatures?|time|duration))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "laser exposure condition",
        re.compile(
            r"(?:\b(?:laser (?:power|energy)|scann?ing (?:speed|strateg(?:y|ies)|"
            r"condition(?:s)?)|"
            r"scan speed|hatch spacing|volumetric energy density|"
            r"energy density|exposure time|"
            r"induct(?:ive|ion(?: heating)?) energy|"
            r"induction (?:heater |heating )?input current)\b|"
            r"\binput current\s*\(\s*induction heater\s*\))",
            re.IGNORECASE,
        ),
    ),
    (
        "build preheating condition",
        re.compile(
            r"\b(?:(?:powder bed|base plate|build plate|substrate) "
            r"pre[- ]?heat(?:ing|ed)?|"
            r"pre[- ]?heat(?:ing)? (?:the )?"
            r"(?:powder bed|base plate|build plate|substrate))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "surface treatment condition",
        re.compile(r"\bsurface treatment\b", re.IGNORECASE),
    ),
)
_VARIABLE_THEME_LABELS = frozenset(label for label, _ in _VARIABLE_THEME_PATTERNS)
_OBJECTIVE_VARIABLE_THEME_ALIASES = {
    "energy input": "laser exposure condition",
    "laser energy input": "laser exposure condition",
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
    normalized = normalize_property_label(outcome) or outcome
    if normalized in _MULTI_MEASUREMENT_OUTCOME_FAMILIES:
        return True
    words = set(normalized.split())
    if "mechanical" in words and words & {"property", "properties"}:
        return True
    if any(token.startswith("microstructur") for token in words):
        return True
    if re.search(r"\b(?:and|versus)\b|\s[&/]\s", outcome):
        return True
    if re.search(r"\([^)]*(?:,|;|\band\b)[^)]*\)", outcome):
        return True
    word_list = normalized.split()
    return word_list[-1] in {
        "combination",
        "performance",
        "properties",
        "property",
    } or word_list[0] in {"combined", "comprehensive", "overall"}


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


def outcome_matches_objective_scope(
    source_outcome: Any,
    objective_outcomes: Iterable[Any],
) -> bool:
    """Match a source result to a possibly broad Objective outcome.

    Exact aliases and explicitly declared expansions remain the primary path.
    For an umbrella outcome phrase, a source result is retained only when it
    shares the phrase's scientific subject tokens and the source itself is a
    narrower label.  This preserves the exact Source outcome for display and
    never invents a canonical measurement name.
    """

    source = normalize_property_label(source_outcome)
    if not source:
        return False
    targets: list[str] = []
    for target in objective_outcomes:
        normalized_target = normalize_property_label(target)
        if not normalized_target:
            continue
        targets.append(normalized_target)
        # Callers commonly pass the Objective's original outcome tuple here,
        # while other paths pass ``objective_outcomes(objective)``.  Expand at
        # this boundary so both paths apply the same scope rule.
        targets.extend(
            expanded
            for expanded in (
                normalize_property_label(value)
                for value in broad_outcome_expansions(normalized_target)
            )
            if expanded
        )
    if property_matches_target_axes(source, target_axes=targets):
        return True
    source_tokens = set(source.split())
    for target in targets:
        normalized_target = normalize_property_label(target)
        if not normalized_target:
            continue
        target_words = normalized_target.split()
        if not target_words or target_words[-1] not in _OUTCOME_UMBRELLA_HEADS:
            continue
        subject_tokens = set(target_words[:-1])
        if subject_tokens and subject_tokens <= source_tokens:
            return True
    return False


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
    if any(
        _fatigue_strength_variants_match(normalized, candidate)
        for candidate in target_axes
    ):
        return True
    return _contextual_property_variant_match(
        normalized,
        target_axes=target_axes,
    ) is not None


def _fatigue_strength_variants_match(left: Any, right: Any) -> bool:
    """Match an explicit fatigue-strength measurement to a cycle-qualified axis.

    A bare cycle count is intentionally accepted as a family match because a
    paper may define the regime in a nearby methods/results Source.  Explicit
    low/high qualifiers on both sides must agree, so one regime cannot be
    silently used as evidence for the other.
    """

    left_text = normalize_property_label(left)
    right_text = normalize_property_label(right)
    if not left_text or not right_text:
        return False
    left_regime = _fatigue_strength_variant_regime(left_text)
    right_regime = _fatigue_strength_variant_regime(right_text)
    if left_regime == "invalid" or right_regime == "invalid":
        return False
    return left_regime is None or right_regime is None or left_regime == right_regime


def _fatigue_strength_variant_regime(value: Any) -> str | None:
    normalized = normalize_property_label(value)
    if not normalized:
        return "invalid"
    match = _FATIGUE_STRENGTH_VARIANT_RE.fullmatch(normalized)
    if match is None:
        return "invalid"
    return " ".join(str(match.group("regime") or "").casefold().split()) or None


def _fatigue_strength_variants_conflict(left: Any, right: Any) -> bool:
    left_regime = _fatigue_strength_variant_regime(left)
    right_regime = _fatigue_strength_variant_regime(right)
    return (
        left_regime not in {None, "invalid"}
        and right_regime not in {None, "invalid"}
        and left_regime != right_regime
    )


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


def normalize_objective_result_property(
    value: Any,
    *,
    objective_context: ResearchObjective | None,
) -> str | None:
    """Normalize a table result label without retaining result-kind suffixes.

    ``Yield strength Experiment`` and ``Yield strength Prediction`` are two
    result columns for one scientific outcome.  Their measured/predicted
    distinction is represented by ``result_kind``; keeping the suffix in the
    outcome would split one outcome into unrelated axes during synthesis.
    Other qualifiers, such as a fatigue cycle regime, remain source-defined.
    """

    normalized = normalize_objective_unit_property(
        value,
        objective_context=objective_context,
    )
    if not normalized or objective_context is None:
        return normalized
    target_axes = objective_outcomes(objective_context)
    for target_axis in target_axes:
        target_key = normalize_property_label(target_axis)
        if not target_key:
            continue
        variant = _contextual_property_variant_match(
            normalized,
            target_axes=(target_key,),
        )
        if variant is None:
            continue
        canonical, extra_tokens = variant
        if extra_tokens and extra_tokens.issubset(_PRESERVED_PROPERTY_QUALIFIERS):
            return normalize_property_label(canonical) or canonical
    return normalized


def normalize_source_defined_objective_property(
    value: Any,
    *,
    source_text: str,
    objective_context: ResearchObjective | None,
) -> str | None:
    """Resolve an outcome alias only when the exact Source defines it.

    Researchers routinely read a table heading such as ``DIDX`` together with
    a caption saying ``DIDX means densification index``.  Ordinary property
    normalization cannot safely infer that relationship.  This helper keeps
    the Source as the authority: an alias is accepted only when a nearby
    definition explicitly names exactly one confirmed Objective outcome.
    """

    normalized = normalize_objective_unit_property(
        value,
        objective_context=objective_context,
    )
    if (
        not normalized
        or objective_context is None
        or not str(source_text or "").strip()
    ):
        return normalized
    target_axes = tuple(str(axis).strip() for axis in objective_context.outcomes if str(axis).strip())
    if not target_axes or property_matches_target_axes(
        normalized,
        target_axes=objective_outcomes(objective_context),
    ):
        return normalized
    alias_key = axis_key(str(value or ""))
    if not alias_key:
        return normalized
    matched_axes: list[str] = []
    for alias, definition in _source_defined_axis_aliases(source_text):
        if axis_key(alias) != alias_key:
            continue
        for target_axis in target_axes:
            if source_text_mentions_axis(definition, target_axis):
                if target_axis not in matched_axes:
                    matched_axes.append(target_axis)
    return (
        normalize_property_label(matched_axes[0])
        if len(matched_axes) == 1
        else normalized
    )


def _source_defined_axis_aliases(source_text: str) -> tuple[tuple[str, str], ...]:
    text = str(source_text or "")
    if not text:
        return ()
    aliases: list[tuple[str, str]] = []
    definition_patterns = (
        re.compile(
            r"\b(?P<alias>[A-Z][A-Z0-9]{1,8})\s+"
            r"(?:means|denotes|stands\s+for|refers\s+to|is\s+defined\s+as)\s+"
            r"(?P<definition>[^.;\n]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<definition>[A-Za-z][A-Za-z0-9%/()\[\],\-\s]{2,100}?)\s*"
            r"\(\s*(?P<alias>[A-Z][A-Z0-9]{1,8})\s*\)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<alias>[A-Z][A-Z0-9]{1,8})\s*\(\s*"
            r"(?P<definition>[A-Za-z][A-Za-z0-9%/()\[\],\-\s]{2,100}?)\s*\)",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in definition_patterns:
        for match in pattern.finditer(text):
            alias = str(match.group("alias") or "").strip()
            definition = " ".join(
                str(match.group("definition") or "").split()
            ).strip(" ,:")
            if alias and definition:
                aliases.append((alias, definition))
    return tuple(dict.fromkeys(aliases))


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
    if _fatigue_strength_text_mentions_axis(text, axis):
        return True
    return any(
        _source_text_mentions_single_axis(text, expanded_axis)
        for expanded_axis in broad_outcome_expansions(axis)
    )


def _fatigue_strength_text_mentions_axis(text: Any, axis: Any) -> bool:
    target_regime = _fatigue_strength_variant_regime(axis)
    if target_regime in {"invalid", None}:
        return False
    for match in _FATIGUE_STRENGTH_TEXT_RE.finditer(str(text or "")):
        observed_regime = " ".join(
            str(match.group("regime") or "").casefold().split()
        ) or None
        if observed_regime is None or observed_regime == target_regime:
            return True
    return False


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


def _material_family(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text:
        return None
    if re.search(
        r"(?<![a-z0-9])(?:ti(?:tanium)?|tc4)(?![a-z0-9])|"
        r"(?<![a-z0-9])ti[\s-]*(?:6[\s-]*al[\s-]*4[\s-]*v|"
        r"al[\s-]*6[\s-]*v[\s-]*4|64)(?![a-z0-9])",
        text,
    ):
        return "titanium"
    if re.search(r"\b(?:al(?:uminum|uminium)?)[\s-]*\d|\balumin(?:um|ium)\b", text):
        return "aluminum"
    if re.search(
        r"\b(?:stainless steel|tool steel|maraging steel|carbon steel|"
        r"austenitic stainless|h\d{2}|ss\d{3,4}|aisi[\s-]*\d{3,4})\b",
        text,
    ):
        return "steel"
    if re.search(r"\b(?:nickel|hastelloy|superalloy|hwsa)\b", text):
        return "nickel-superalloy"
    if re.search(r"\b(?:cobalt|cocr)\b", text):
        return "cobalt-alloy"
    if re.search(r"\b(?:tin|sn)\b", text):
        return "tin"
    return None


def _material_is_exact_grade(value: Any) -> bool:
    text = " ".join(str(value or "").strip().casefold().split())
    return bool(
        re.search(
            r"(?<![a-z0-9])(?:tc4|ti[\s-]*(?:6[\s-]*al[\s-]*4[\s-]*v|"
            r"al[\s-]*6[\s-]*v[\s-]*4|64)|al[\s-]*\d{4}|h\d{2}|"
            r"ss\d{3,4}|aisi[\s-]*\d{3,4}|\d{3,4}l|cocr|hastelloy[\s-]*[a-z])"
            r"(?![a-z0-9])",
            text,
        )
    )


def _canonical_material_grade(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().casefold().split())
    if re.search(
        r"(?<![a-z0-9])(?:tc4|ti[\s-]*(?:6[\s-]*al[\s-]*4[\s-]*v|"
        r"al[\s-]*6[\s-]*v[\s-]*4|64))(?![a-z0-9])",
        text,
    ):
        return "titanium:ti-6al-4v"
    if re.search(
        r"(?<![a-z0-9])(?:ss|aisi)?[\s-]*316[\s-]*l(?![a-z0-9])|"
        r"(?<![a-z0-9])316[\s-]*l[\s-]*(?:stainless[\s-]*steel)?",
        text,
    ):
        return "steel:316l"
    if re.search(
        r"(?<![a-z0-9])17[\s-]*4[\s-]*ph(?![a-z0-9])",
        text,
    ):
        return "steel:17-4ph"
    return None


def material_values_match_for_scope(left: Any, right: Any) -> bool:
    """Match material identity only for deciding whether a paper merits inspection."""

    left_key = axis_key(left)
    right_key = axis_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_grade = _canonical_material_grade(left)
    right_grade = _canonical_material_grade(right)
    if left_grade is not None and left_grade == right_grade:
        return True
    left_family = _material_family(left)
    right_family = _material_family(right)
    if not left_family or left_family != right_family:
        return False
    if _material_is_exact_grade(left) and _material_is_exact_grade(right):
        return False
    return True


def material_value_matches_objective_comparison_scope(
    evidence_value: Any,
    objective_value: Any,
) -> bool:
    """Require enough material identity for a direct Objective comparison."""

    evidence_key = axis_key(evidence_value)
    objective_key = axis_key(objective_value)
    if not evidence_key or not objective_key:
        return False
    if evidence_key == objective_key:
        return True
    evidence_grade = _canonical_material_grade(evidence_value)
    objective_grade = _canonical_material_grade(objective_value)
    if evidence_grade is not None or objective_grade is not None:
        return evidence_grade is not None and evidence_grade == objective_grade
    evidence_family = _material_family(evidence_value)
    objective_family = _material_family(objective_value)
    if not evidence_family or evidence_family != objective_family:
        return False
    if _material_is_exact_grade(objective_value):
        return False
    return True


def material_scope_value_is_specific(value: Any) -> bool:
    """Return whether a material label can support a screening exclusion."""

    return (
        _canonical_material_grade(value) is not None
        or _material_family(value) is not None
    )


def material_scope_value_is_broad(value: Any) -> bool:
    """Return whether a label denotes an unresolved broad material population."""

    text = " ".join(str(value or "").strip().casefold().split())
    return bool(
        re.search(r"\b(?:metal|metallic|materials?)\b", text)
        and re.search(r"\b(?:alloys?|materials?|parts?|components?)\b", text)
    )


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
    if _fatigue_strength_variants_conflict(left, right):
        return False
    if axis_alias_matches_canonical(left, right):
        return True
    left_key = normalize_property_label(left) or axis_key(left)
    right_key = normalize_property_label(right) or axis_key(right)
    return right_key in _EXPLICIT_AXIS_SYNONYMS.get(left_key, ()) or (
        left_key in _EXPLICIT_AXIS_SYNONYMS.get(right_key, ())
    )


def variable_theme_labels(value: Any) -> tuple[str, ...]:
    """Return bounded research themes containing one precise intervention."""

    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(
        label
        for label, pattern in _VARIABLE_THEME_PATTERNS
        if label == axis_key(text) or pattern.search(text)
    )


def shared_variable_theme(
    factor_sets: Iterable[Iterable[str]],
) -> str | None:
    """Return the most specific intervention theme shared by every paper fact."""

    groups = tuple(tuple(str(factor) for factor in factors) for factors in factor_sets)
    if not groups or any(not group for group in groups):
        return None
    return next(
        (
            label
            for label, _pattern in _VARIABLE_THEME_PATTERNS
            if all(
                any(label in variable_theme_labels(factor) for factor in group)
                for group in groups
            )
        ),
        None,
    )


def variable_matches_objective_scope(
    source_variable: Any,
    objective_variable: Any,
) -> bool:
    """Match a precise Source variable to an Objective without equating themes."""

    source = str(source_variable or "").strip()
    objective = str(objective_variable or "").strip()
    if not source or not objective:
        return False
    if axis_values_match(source, objective):
        return True
    objective_theme = objective_variable_theme(objective)
    return bool(
        objective_theme and objective_theme in variable_theme_labels(source)
    )


def process_axis_matches_objective_scope(
    source_axis: Any,
    objective_axis: Any,
) -> bool:
    """Match a source-specific process axis to a broad Objective axis.

    This is intentionally separate from :func:`axis_values_match`: a scan
    rotation angle and a build orientation angle remain distinct factors even
    when both are covered by a broad Objective such as ``scanning strategy``
    and ``build orientation``.
    """

    source_key = normalize_property_label(source_axis) or axis_key(source_axis)
    objective_key = normalize_property_label(objective_axis) or axis_key(objective_axis)
    if not source_key or not objective_key:
        return False
    if axis_values_match(source_key, objective_key):
        return True
    if axis_label_is_mentioned(source_key, objective_key):
        return True
    return any(
        axis_values_match(alias, objective_key)
        or axis_label_is_mentioned(alias, objective_key)
        or axis_label_is_mentioned(objective_key, alias)
        for alias in _PROCESS_AXIS_SCOPE_ALIASES.get(source_key, ())
    )


def objective_variable_theme(value: Any) -> str | None:
    """Resolve an explicit umbrella Objective variable to one research theme."""

    key = axis_key(value)
    if key in _VARIABLE_THEME_LABELS:
        return key
    return _OBJECTIVE_VARIABLE_THEME_ALIASES.get(key)


def source_text_mentions_objective_variable(text: str, objective_variable: str) -> bool:
    if source_text_mentions_axis(text, objective_variable):
        return True
    objective_key = axis_key(objective_variable)
    if any(
        source_text_mentions_axis(text, alias)
        for alias in _EXPLICIT_AXIS_SYNONYMS.get(objective_key, ())
    ):
        return True
    # A confirmed Objective may use a specific process axis while a paper
    # names the broader experimental family (for example, ``scanning
    # strategy`` for ``scan strategy rotation angle``).  Keep that source
    # fact discoverable for review without treating the labels as equivalent
    # comparison variables; endpoint binding remains source-local.
    for alias in _PROCESS_AXIS_SCOPE_ALIASES.get(objective_key, ()):
        if source_text_mentions_axis(text, alias):
            return True
    objective_theme = objective_variable_theme(objective_variable)
    if objective_theme is None:
        return False
    return any(
        label == objective_theme and pattern.search(text) is not None
        for label, pattern in _VARIABLE_THEME_PATTERNS
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
    for field_name in ("experiment_label",):
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
    axis_token_values = axis_tokens(axis_key(normalized_axis or axis))
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
        elif normalized.endswith("c"):
            normalized = f"{normalized}e"
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

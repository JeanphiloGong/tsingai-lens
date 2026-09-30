"""Model-output and authoring boundaries for PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from domain.core.paper_experiment import PaperExperimentRevision, SourceReference
from domain.core.research_objective import ResearchObjective


# Drafts may carry only content and local cross-reference keys. Formal
# identity, request ownership, and validation state are assigned after the
# source-grounded content has been checked.
_FORBIDDEN_DRAFT_FIELDS = frozenset(
    {
        "id",
        "ids",
        "experiment_id",
        "experiment_version",
        "revision_id",
        "document_id",
        "source_fingerprint",
        "collection_id",
        "objective_id",
        "variant_id",
        "variant_ids",
        "test_id",
        "test_ids",
        "test_condition_id",
        "test_condition_ids",
        "measurement_id",
        "measurement_ids",
        "result_id",
        "result_ids",
        "comparison_id",
        "comparison_ids",
        "source_id",
        "source_ids",
        "source_ref",
        "source_refs",
        "binding_source_refs",
        "selection_id",
        "selection_ids",
        "comparison_group_id",
        "comparison_group_ids",
        "analysis_version",
        "finding_id",
        "identity_status",
        "binding_status",
        "relation_status",
        "status",
        "direction",
        "basis",
        "attribution_scope",
    }
)


# These names are common scientific identifiers reported by a paper rather than
# Lens-owned identities.  They are accepted only inside the explicit
# ``population_scope.reported_identifiers`` or
# ``measurement_scope.reported_identifiers`` containers.  The container rule
# below also accepts an otherwise unknown domain identifier (for example
# ``stimulus_id`` in a psychology paper) without weakening the formal-ID gate.
SOURCE_REPORTED_IDENTIFIER_FIELDS = frozenset(
    {
        "sample_id",
        "sample_ids",
        "specimen_id",
        "specimen_ids",
        "batch_id",
        "batch_ids",
        "lot_id",
        "lot_ids",
        "run_id",
        "run_ids",
        "replicate_id",
        "replicate_ids",
        "cohort_id",
        "cohort_ids",
        "participant_id",
        "participant_ids",
        "subject_id",
        "subject_ids",
        "patient_id",
        "patient_ids",
        "animal_id",
        "animal_ids",
        "wafer_id",
        "wafer_ids",
        "build_id",
        "build_ids",
        "scan_id",
        "scan_ids",
        "cycle_id",
        "cycle_ids",
    }
)
_PERSISTED_SCIENTIFIC_IDENTIFIER_CONTAINERS = frozenset(
    {"population_scope", "measurement_scope"}
)
_REPORTED_IDENTIFIER_CONTAINER = "reported_identifiers"


def _in_scoped_reported_identifiers(ancestors: tuple[str, ...]) -> bool:
    """Return whether a key is inside a scope's explicit paper-ID map."""

    for index, ancestor in enumerate(ancestors):
        if ancestor != _REPORTED_IDENTIFIER_CONTAINER:
            continue
        if any(
            parent in _PERSISTED_SCIENTIFIC_IDENTIFIER_CONTAINERS
            for parent in ancestors[:index]
        ):
            return True
    return False


def _is_forbidden_field(field: str, *, ancestors: tuple[str, ...] = ()) -> bool:
    """Reject formal identity fields even when a caller invents a new name."""

    normalized = field.strip().lower()
    # Formal Lens-owned names always win, even when nested in a paper-ID map.
    if normalized in _FORBIDDEN_DRAFT_FIELDS:
        return True
    if normalized in SOURCE_REPORTED_IDENTIFIER_FIELDS:
        return not _in_scoped_reported_identifiers(ancestors)
    if _in_scoped_reported_identifiers(ancestors) and (
        normalized.endswith("_id") or normalized.endswith("_ids")
    ):
        # Domain-specific paper identifiers are allowed only in the explicit
        # container.  This keeps the contract useful outside materials science
        # while still rejecting arbitrary IDs everywhere else.
        return False
    return (
        normalized.endswith("_id")
        or normalized.endswith("_ids")
    )


def _first_forbidden_field(
    value: Any,
    path: str = "",
    ancestors: tuple[str, ...] = (),
) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            field = str(key)
            normalized = field.strip().lower()
            current_path = f"{path}.{field}" if path else field
            if _is_forbidden_field(field, ancestors=ancestors):
                return current_path
            found = _first_forbidden_field(
                nested,
                current_path,
                (*ancestors, normalized),
            )
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found = _first_forbidden_field(
                nested,
                f"{path}[{index}]",
                ancestors,
            )
            if found is not None:
                return found
    return None


def _mapping_items(value: Any, *, field: str) -> tuple[Mapping[str, Any], ...]:
    """Validate an optional JSON array instead of silently dropping malformed items."""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} must contain only objects")
    return tuple(value)


def _string_items(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def _dedupe_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep source records once while preserving their first-seen order."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = tuple(sorted((str(name), repr(value)) for name, value in record.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(record))
    return result


def _collect_source_labels(value: Any) -> set[str]:
    labels: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "source_label" and isinstance(nested, str) and nested.strip():
                labels.add(nested.strip())
                continue
            if key in {
                "source_labels",
                "binding_source_labels",
                "variant_binding_source_labels",
                "test_binding_source_labels",
            }:
                values = (
                    nested
                    if isinstance(nested, (list, tuple, set, frozenset))
                    else (nested,)
                )
                labels.update(
                    str(item).strip() for item in values if str(item).strip()
                )
            else:
                labels.update(_collect_source_labels(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            labels.update(_collect_source_labels(nested))
    return labels


@dataclass(frozen=True)
class PaperExperimentDraft:
    """A model-proposed experiment with only local keys and source labels."""

    payload: Mapping[str, Any]
    source_labels: tuple[str, ...] = ()
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("draft payload must be an object")
        if any(not isinstance(item, Mapping) for item in self.unresolved_issues):
            raise ValueError("draft unresolved_issues must contain only objects")
        forbidden_path = _first_forbidden_field(self.payload)
        if forbidden_path is None:
            forbidden_path = _first_forbidden_field(
                self.unresolved_issues, "unresolved_issues"
            )
        if forbidden_path is not None:
            raise ValueError(
                "draft cannot contain formal identity, request ownership, or "
                f"validation fields: {forbidden_path}"
            )
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(
            self,
            "source_labels",
            tuple(str(item).strip() for item in self.source_labels if str(item).strip()),
        )
        object.__setattr__(
            self,
            "unresolved_issues",
            tuple(dict(item) for item in self.unresolved_issues),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentDraft":
        if not isinstance(payload, Mapping):
            raise ValueError("experiments must contain only objects")
        return cls(
            payload={
                key: value
                for key, value in payload.items()
                if key not in {"source_labels", "unresolved_issues"}
            },
            source_labels=_string_items(
                payload.get("source_labels"), field="experiment source_labels"
            ),
            unresolved_issues=_mapping_items(
                payload.get("unresolved_issues"), field="experiment unresolved_issues"
            ),
        )


@dataclass(frozen=True)
class PaperExperimentModelOutput:
    """Application envelope around one bounded model response.

    ``document_id`` and ``source_fingerprint`` are request context attached by
    the application. They are not fields the model is trusted to invent.
    """

    document_id: str
    source_fingerprint: str
    experiments: tuple[PaperExperimentDraft, ...] = ()
    source_labels: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip() or not self.source_fingerprint.strip():
            raise ValueError("model output requires document_id and source_fingerprint")
        if any(not isinstance(item, PaperExperimentDraft) for item in self.experiments):
            raise ValueError("experiments must contain PaperExperimentDraft objects")
        if not isinstance(self.source_labels, Mapping):
            raise ValueError("source_labels must be an object")
        if any(not isinstance(value, Mapping) for value in self.source_labels.values()):
            raise ValueError("source_labels values must be objects")
        if any(not isinstance(item, Mapping) for item in self.unresolved_issues):
            raise ValueError("unresolved_issues must contain only objects")
        forbidden_path = _first_forbidden_field(
            self.unresolved_issues, "unresolved_issues"
        )
        if forbidden_path is not None:
            raise ValueError(
                "model output cannot contain formal identity, request ownership, "
                f"or validation fields: {forbidden_path}"
            )
        object.__setattr__(self, "source_labels", dict(self.source_labels or {}))
        object.__setattr__(
            self,
            "unresolved_issues",
            tuple(dict(item) for item in self.unresolved_issues),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentModelOutput":
        """Parse a trusted application envelope.

        Raw provider JSON should use :meth:`from_model_mapping`, which injects
        the request context and the service-owned source-label catalog.
        """
        if not isinstance(payload, Mapping):
            raise ValueError("model output must be an object")
        forbidden = next(
            (
                str(key)
                for key in payload
                if _is_forbidden_field(str(key))
                and str(key) not in {"document_id", "source_fingerprint"}
            ),
            None,
        )
        if forbidden is not None:
            raise ValueError(
                "model output cannot contain formal identity, request ownership, "
                f"source reference, or validation fields: {forbidden}"
            )
        experiment_items = _mapping_items(payload.get("experiments"), field="experiments")
        source_catalog = payload.get("source_labels")
        if source_catalog is not None and not isinstance(source_catalog, Mapping):
            raise ValueError("source_labels must be an object")
        if isinstance(source_catalog, Mapping) and any(
            not isinstance(value, Mapping) for value in source_catalog.values()
        ):
            raise ValueError("source_labels values must be objects")
        unresolved_items = _mapping_items(
            payload.get("unresolved_issues"), field="unresolved_issues"
        )
        return cls(
            document_id=str(payload.get("document_id") or "").strip(),
            source_fingerprint=str(payload.get("source_fingerprint") or "").strip(),
            experiments=tuple(
                PaperExperimentDraft.from_mapping(item)
                for item in experiment_items
            ),
            source_labels={
                str(key): dict(value)
                for key, value in dict(source_catalog or {}).items()
            },
            unresolved_issues=tuple(dict(item) for item in unresolved_items),
        )

    @classmethod
    def from_model_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        document_id: str,
        source_fingerprint: str,
        source_labels: Mapping[str, Mapping[str, Any]],
    ) -> "PaperExperimentModelOutput":
        """Parse raw model JSON and attach service-owned request context."""

        forbidden_context = next(
            (
                str(key)
                for key in payload
                if str(key)
                in {
                    "document_id",
                    "source_fingerprint",
                    "collection_id",
                    "objective_id",
                }
            ),
            None,
        )
        if forbidden_context is not None:
            raise ValueError(
                "raw model output cannot contain request context fields: "
                f"{forbidden_context}"
            )
        raw_source_labels = payload.get("source_labels")
        if raw_source_labels is not None:
            if not isinstance(raw_source_labels, (list, tuple)) or any(
                not isinstance(item, str) for item in raw_source_labels
            ):
                raise ValueError(
                    "raw model output source_labels must be a list of supplied labels"
                )
            unknown_labels = sorted(set(raw_source_labels) - set(source_labels))
            if unknown_labels:
                raise ValueError(
                    "raw model output referenced unknown source labels: "
                    + ", ".join(unknown_labels)
                )
        experiment_items = _mapping_items(payload.get("experiments"), field="experiments")
        unresolved_items = _mapping_items(
            payload.get("unresolved_issues"), field="unresolved_issues"
        )
        forbidden = _first_forbidden_field(
            {key: value for key, value in payload.items() if key != "source_labels"}
        )
        if forbidden is not None:
            raise ValueError(
                "raw model output cannot contain formal identity, request "
                f"ownership, source reference, or validation fields: {forbidden}"
            )
        return cls(
            document_id=document_id,
            source_fingerprint=source_fingerprint,
            experiments=tuple(
                PaperExperimentDraft.from_mapping(item)
                for item in experiment_items
            ),
            source_labels=source_labels,
            unresolved_issues=tuple(dict(item) for item in unresolved_items),
        )


@dataclass(frozen=True)
class ReconciledPaperExperimentOutput:
    """Service-owned handoff between boundary reconciliation and identity write.

    The provider can propose scopes, but it cannot mark those proposals as
    accepted.  The boundary reconciler creates this wrapper after it has
    selected the final local experiment scopes.  Keeping the wrapper separate
    makes it impossible for a low-level identity adapter to accidentally assign
    one formal identity to each raw boundary proposal.
    """

    output: PaperExperimentModelOutput
    accepted_experiment_keys: tuple[str, ...]
    audit_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if len(self.output.experiments) != len(self.accepted_experiment_keys):
            raise ValueError(
                "reconciled experiment keys must match the accepted draft count"
            )
        if any(not str(key).strip() for key in self.accepted_experiment_keys):
            raise ValueError("reconciled experiment keys must be non-empty")
        if len(set(self.accepted_experiment_keys)) != len(self.accepted_experiment_keys):
            raise ValueError("reconciled experiment keys must be unique")
        object.__setattr__(
            self,
            "accepted_experiment_keys",
            tuple(str(key).strip() for key in self.accepted_experiment_keys),
        )
        object.__setattr__(
            self,
            "audit_issues",
            tuple(
                dict(item)
                for item in self.audit_issues
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class DraftReadiness:
    """Objective-scoped gate result before formal identity allocation."""

    ready: bool
    missing_context: tuple[str, ...] = ()
    selected_measurement_keys: tuple[str, ...] = ()
    selected_comparison_keys: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _draft_items(payload: Mapping[str, Any], *names: str) -> list[dict[str, Any]]:
    present = [name for name in names if payload.get(name) is not None]
    if len(present) > 1:
        raise ValueError("draft cannot provide both " + " and ".join(present))
    for name in present:
        value = payload[name]
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be a list")
        if any(not isinstance(item, Mapping) for item in value):
            raise ValueError(f"{name} must contain only objects")
        return [dict(item) for item in value]
    return []


def _source_labels(value: Any) -> tuple[str, ...]:
    """Normalize source-label fields while merging repeated observations."""

    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _require_unique_local_keys(
    items: Sequence[Mapping[str, Any]],
    *,
    field: str,
    path: str,
) -> tuple[str, ...]:
    keys = tuple(str(item.get(field) or "").strip() for item in items)
    if any(not key for key in keys):
        raise ValueError(f"{path} requires non-empty {field}")
    if len(set(keys)) != len(keys):
        raise ValueError(f"{path} contains duplicate {field}")
    return keys


def _split_conflicting_measurements(
    items: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    Mapping[str, tuple[str, ...]],
]:
    """Retain disagreeing reports instead of choosing or averaging one."""

    result: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    conflicts: dict[str, list[str]] = {}
    seen: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        key = str(item.get("measurement_key") or "").strip()
        if not key or key not in seen:
            result.append(item)
            if key:
                seen[key] = item
            continue
        previous = seen[key]
        compared_fields = (
            "value",
            "unit",
            "result_text",
            "statistics",
            "variant_key",
            "test_key",
            "measurement_scope",
            "reported_sample_label",
            "reported_test_label",
        )
        if all(previous.get(field) == item.get(field) for field in compared_fields):
            # The same source-local fact can arrive from a continuation read.
            # Keep one observation but merge provenance and any fields that the
            # second read supplied, instead of rejecting the whole Draft.
            for name, value in item.items():
                if name in {
                    "source_labels",
                    "binding_source_labels",
                    "variant_binding_source_labels",
                    "test_binding_source_labels",
                }:
                    existing = previous.get(name) or ()
                    incoming = value or ()
                    previous[name] = list(
                        dict.fromkeys(
                            [
                                *_source_labels(existing),
                                *_source_labels(incoming),
                            ]
                        )
                    )
                elif name not in previous or previous.get(name) in (None, "", [], {}):
                    previous[name] = value
            continue
        digest = hashlib.sha1(
            json.dumps(item, ensure_ascii=True, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()[:10]
        conflict_key = f"{key}__conflict_{digest}"
        suffix = 2
        while conflict_key in seen:
            conflict_key = f"{key}__conflict_{digest}_{suffix}"
            suffix += 1
        item["measurement_key"] = conflict_key
        item["conflict_of"] = key
        result.append(item)
        seen[conflict_key] = item
        conflicts.setdefault(key, []).append(conflict_key)
        issues.append(
            {
                "target_ref": f"measurements/{key}",
                "description": (
                    "Conflicting source reports were retained as separate "
                    f"measurements; the additional report is {conflict_key}."
                ),
                "source_labels": list(
                    dict.fromkeys(
                        [
                            *(previous.get("source_labels") or ()),
                            *(item.get("source_labels") or ()),
                        ]
                    )
                ),
            }
        )
    return result, issues, {
        key: tuple(values) for key, values in conflicts.items()
    }


def _reference_keys(
    value: Mapping[str, Any],
    *,
    fields: Sequence[str],
) -> tuple[str, ...]:
    references: list[str] = []
    for field in fields:
        raw = value.get(field)
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple)) else (raw,)
        references.extend(
            str(item).strip()
            for item in values
            if not isinstance(item, Mapping) and str(item).strip()
        )
    return tuple(references)


def _validate_issue_references(
    issues: Sequence[Mapping[str, Any]],
    *,
    source_labels: set[str],
    allowed_targets: set[str],
) -> None:
    """Reject issue references that cannot be replayed after local binding."""

    for index, issue in enumerate(issues):
        target = str(issue.get("target_ref") or "experiment").strip()
        if target not in allowed_targets:
            raise ValueError(
                f"unresolved_issues[{index}] has unknown target_ref: {target}"
            )
        referenced = _collect_source_labels(issue)
        unknown = sorted(referenced - source_labels)
        if unknown:
            raise ValueError(
                f"unresolved_issues[{index}] references unknown source label: "
                + ", ".join(unknown)
            )


def _outcome_tokens(value: Any) -> tuple[str, ...]:
    """Normalize outcome names without dropping non-ASCII scientific terms."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    if not normalized:
        return ()
    return tuple(
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if token
    )


def _outcome_matches(left: Any, candidates: Sequence[str]) -> bool:
    left_tokens = set(_outcome_tokens(left))
    if not left_tokens:
        return False
    for candidate in candidates:
        right_tokens = set(_outcome_tokens(candidate))
        if right_tokens and (
            left_tokens == right_tokens
            or left_tokens <= right_tokens
            or right_tokens <= left_tokens
        ):
            return True
    return False


def _reported_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        str(value if value is not None else ""),
    )
    return float(match.group()) if match else None


def _measurement_number(item: Mapping[str, Any]) -> float | None:
    value = item.get("value")
    if value is not None and not isinstance(value, str):
        return _reported_number(value)
    if isinstance(value, str) and value.strip():
        return _reported_number(value)
    return _reported_number(item.get("result_text"))


def _recompute_comparison_direction(
    comparison: dict[str, Any],
    measurements_by_key: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Set a numeric candidate without inventing an aggregation rule."""

    baseline_keys = _reference_keys(
        comparison, fields=("baseline_measurement_keys",)
    )
    target_keys = _reference_keys(
        comparison, fields=("target_measurement_keys",)
    )
    baseline = [
        measurements_by_key[key]
        for key in baseline_keys
        if key in measurements_by_key
    ]
    target = [
        measurements_by_key[key]
        for key in target_keys
        if key in measurements_by_key
    ]
    if not baseline or not target:
        comparison["direction_candidate"] = "unknown"
        return "comparison requires a report on both sides"
    if len(baseline) != 1 or len(target) != 1:
        comparison["direction_candidate"] = "unknown"
        return (
            "multiple measurements per comparison side require an explicit "
            "aggregation scope"
        )
    values = [
        (_measurement_number(item), str(item.get("unit") or "").strip().casefold())
        for item in (*baseline, *target)
    ]
    units = {unit for _, unit in values}
    if len(units) != 1 or "" in units or any(number is None for number, _ in values):
        comparison["direction_candidate"] = "unknown"
        return "comparison values are not numeric values with one shared unit"
    baseline_value = values[0][0]
    target_value = values[1][0]
    assert baseline_value is not None and target_value is not None
    comparison["direction_candidate"] = (
        "increase"
        if target_value > baseline_value
        else "decrease"
        if target_value < baseline_value
        else "no_change"
    )
    return None


def prepare_model_output(
    output: PaperExperimentModelOutput,
    *,
    objective: ResearchObjective,
) -> ReconciledPaperExperimentOutput:
    """Validate a response-local graph and derive service-owned candidates."""

    if not isinstance(output, PaperExperimentModelOutput):
        raise TypeError("prepare_model_output requires PaperExperimentModelOutput")
    if not isinstance(objective, ResearchObjective):
        raise TypeError("prepare_model_output requires ResearchObjective")

    catalog = set(output.source_labels)
    prepared: list[PaperExperimentDraft] = []
    accepted: list[str] = []
    seen_series_keys: set[str] = set()
    audit: list[dict[str, Any]] = []
    global_issues = [
        dict(issue)
        for issue in output.unresolved_issues
        if isinstance(issue, Mapping)
    ]
    _validate_issue_references(
        global_issues,
        source_labels=catalog,
        allowed_targets={"document", "experiment"},
    )

    supported_scope_kinds = {
        "parent",
        "matrix",
        "selected_stratum",
        "follow_up",
        "physical_split",
        "split",
        "independent",
        "unknown",
    }
    for index, draft in enumerate(output.experiments):
        payload = dict(draft.payload)
        series_key = str(
            payload.get("series_key") or payload.get("experiment_key") or ""
        ).strip()
        if not series_key:
            series_key = _generated_series_key(payload, index=index)
            payload["series_key"] = series_key
        if series_key in seen_series_keys:
            raise ValueError(f"experiments contains duplicate series_key: {series_key}")

        scope_kind = str(payload.get("scope_kind") or "unknown").strip().casefold()
        if scope_kind not in supported_scope_kinds:
            raise ValueError(
                f"experiments[{index}] has unsupported scope_kind: {scope_kind}"
            )
        payload["scope_kind"] = scope_kind
        parent_series_key = str(payload.get("parent_series_key") or "").strip()
        if scope_kind in _OVERLAPPING_SCOPE_KINDS:
            if not parent_series_key or parent_series_key not in seen_series_keys:
                raise ValueError(
                    f"experiments[{index}] scoped Draft must reference a prior "
                    "parent_series_key"
                )
        if scope_kind == "unknown" and parent_series_key:
            raise ValueError(
                f"experiments[{index}] unknown scope cannot claim a parent_series_key"
            )

        variants = _draft_items(payload, "experimental_variants", "variants")
        tests = _draft_items(payload, "test_conditions")
        measurements = _draft_items(payload, "measurements")
        comparisons = _draft_items(payload, "comparisons")
        interpretations = _draft_items(
            payload, "reported_interpretations", "interpretations"
        )
        measurements, conflict_issues, conflict_keys = (
            _split_conflicting_measurements(measurements)
        )
        audit.extend(conflict_issues)

        variant_keys = _require_unique_local_keys(
            variants,
            field="variant_key",
            path=f"experiments[{index}].experimental_variants",
        )
        test_keys = _require_unique_local_keys(
            tests,
            field="test_key",
            path=f"experiments[{index}].test_conditions",
        )
        measurement_keys = _require_unique_local_keys(
            measurements,
            field="measurement_key",
            path=f"experiments[{index}].measurements",
        )
        comparison_keys = _require_unique_local_keys(
            comparisons,
            field="comparison_key",
            path=f"experiments[{index}].comparisons",
        )
        variant_key_set = set(variant_keys)
        test_key_set = set(test_keys)
        measurement_key_set = set(measurement_keys)
        comparison_key_set = set(comparison_keys)

        for measurement in measurements:
            for reference in _reference_keys(
                measurement, fields=("variant_key", "variant_keys")
            ):
                if reference not in variant_key_set:
                    raise ValueError(
                        f"experiments[{index}] measurement reference is not local: "
                        f"{reference}"
                    )
            for reference in _reference_keys(
                measurement, fields=("test_key", "test_keys")
            ):
                if reference not in test_key_set:
                    raise ValueError(
                        f"experiments[{index}] measurement test reference is not "
                        f"local: {reference}"
                    )
        for comparison in comparisons:
            for reference in _reference_keys(
                comparison,
                fields=("baseline_variant_key", "target_variant_key"),
            ):
                if reference not in variant_key_set:
                    raise ValueError(
                        f"experiments[{index}] comparison reference is not local: "
                        f"{reference}"
                    )
            for reference in _reference_keys(
                comparison,
                fields=(
                    "baseline_measurement_keys",
                    "target_measurement_keys",
                ),
            ):
                if reference not in measurement_key_set:
                    raise ValueError(
                        f"experiments[{index}] comparison measurement reference is "
                        f"not local: {reference}"
                    )

        referenced_labels = set(draft.source_labels) | _collect_source_labels(payload)
        unknown_labels = sorted(referenced_labels - catalog)
        if unknown_labels:
            raise ValueError(
                f"experiments[{index}] references unknown source labels: "
                + ", ".join(unknown_labels)
            )

        generated_issues = [
            dict(issue)
            for issue in payload.get("unresolved_issues") or ()
            if isinstance(issue, Mapping)
        ]
        draft_issues = [
            *(
                dict(issue)
                for issue in draft.unresolved_issues
                if isinstance(issue, Mapping)
            ),
            *generated_issues,
        ]
        allowed_targets = {
            "experiment",
            *(f"variants/{key}" for key in variant_keys),
            *(f"experimental_variants/{key}" for key in variant_keys),
            *(f"sample_variants/{key}" for key in variant_keys),
            *(f"tests/{key}" for key in test_keys),
            *(f"test_conditions/{key}" for key in test_keys),
            *(f"measurements/{key}" for key in measurement_keys),
            *(f"comparisons/{key}" for key in comparison_keys),
        }
        _validate_issue_references(
            [
                issue
                for issue in draft_issues
                if isinstance(issue, Mapping)
            ],
            source_labels=catalog,
            allowed_targets=allowed_targets,
        )

        for interpretation in interpretations:
            interpretation_labels = _collect_source_labels(interpretation)
            unknown_interpretation_labels = sorted(interpretation_labels - catalog)
            if unknown_interpretation_labels:
                raise ValueError(
                    f"experiments[{index}] interpretation references unknown "
                    "source labels: " + ", ".join(unknown_interpretation_labels)
                )
            for field, allowed in (
                ("variant_keys", variant_key_set),
                ("test_keys", test_key_set),
                ("measurement_keys", measurement_key_set),
                ("comparison_keys", comparison_key_set),
            ):
                for reference in _reference_keys(interpretation, fields=(field,)):
                    if reference not in allowed:
                        raise ValueError(
                            f"experiments[{index}] interpretation reference is not "
                            f"local: {reference}"
                        )

        measurement_by_key = {
            str(item["measurement_key"]): item for item in measurements
        }
        for measurement in measurements:
            measurement_key = str(measurement["measurement_key"])
            if not str(measurement.get("outcome") or "").strip():
                raise ValueError(
                    f"experiments[{index}] measurement {measurement_key} has no outcome"
                )
            if measurement.get("value") is None and not str(
                measurement.get("result_text") or ""
            ).strip():
                raise ValueError(
                    f"experiments[{index}] measurement {measurement_key} has no result"
                )
            if not _reference_keys(measurement, fields=("source_labels",)):
                raise ValueError(
                    f"experiments[{index}] measurement has no reviewable source label"
                )
            missing_binding_edges = tuple(
                field
                for field in (
                    "variant_binding_source_labels",
                    "test_binding_source_labels",
                )
                if not _reference_keys(measurement, fields=(field,))
            )
            if missing_binding_edges:
                audit.append(
                    {
                        "target_ref": f"measurements/{measurement_key}",
                        "description": (
                            "Measurement value is retained, but result-level binding "
                            "edges are missing: " + ", ".join(missing_binding_edges)
                        ),
                    }
                )

        for comparison in comparisons:
            comparison_key = str(comparison["comparison_key"])
            baseline_keys = _reference_keys(
                comparison, fields=("baseline_measurement_keys",)
            )
            target_keys = _reference_keys(
                comparison, fields=("target_measurement_keys",)
            )
            if not baseline_keys or not target_keys:
                raise ValueError(
                    f"experiments[{index}] comparison {comparison_key} requires "
                    "measurement references on both sides"
                )
            if not _reference_keys(comparison, fields=("source_labels",)):
                raise ValueError(
                    f"experiments[{index}] comparison has no reviewable source label"
                )
            referenced_measurements = [
                measurement_by_key[key]
                for key in (*baseline_keys, *target_keys)
                if key in measurement_by_key
            ]
            outcomes = {
                str(item.get("outcome") or "").strip()
                for item in referenced_measurements
                if str(item.get("outcome") or "").strip()
            }
            comparison_outcome = str(comparison.get("outcome") or "").strip()
            if not comparison_outcome or any(
                not _outcome_matches(item, (comparison_outcome,)) for item in outcomes
            ):
                raise ValueError(
                    f"experiments[{index}] comparison outcome does not match its "
                    "measurements"
                )

            referenced = set((*baseline_keys, *target_keys))
            conflict_members = {
                conflict_key
                for values in conflict_keys.values()
                for conflict_key in values
            }
            affected = sorted(
                key
                for key in referenced
                if key in conflict_keys or key in conflict_members
            )
            if affected:
                comparison["direction_candidate"] = "unknown"
                comparison["relation_status_candidate"] = "uncertain"
                comparison["status_candidate"] = "insufficient_context"
                audit.append(
                    {
                        "target_ref": f"comparisons/{comparison_key}",
                        "description": (
                            "A referenced measurement has conflicting reports; the "
                            "comparison is blocked until a report is selected: "
                            + ", ".join(affected)
                        ),
                    }
                )
                continue
            direction_issue = _recompute_comparison_direction(
                comparison, measurement_by_key
            )
            if direction_issue:
                audit.append(
                    {
                        "target_ref": f"comparisons/{comparison_key}",
                        "description": direction_issue,
                    }
                )

        payload.pop("variants", None)
        payload.pop("unresolved_issues", None)
        payload.pop("interpretations", None)
        payload["experimental_variants"] = variants
        payload["test_conditions"] = tests
        payload["measurements"] = measurements
        payload["comparisons"] = comparisons
        payload["reported_interpretations"] = interpretations
        prepared.append(
            PaperExperimentDraft(
                payload=payload,
                source_labels=draft.source_labels,
                unresolved_issues=tuple(draft_issues),
            )
        )
        accepted.append(series_key)
        seen_series_keys.add(series_key)

    prepared_output = replace(output, experiments=tuple(prepared))
    return reconcile_model_output(
        prepared_output,
        accepted_experiment_keys=accepted,
        audit_issues=audit,
    )


def assess_draft_readiness(
    output: ReconciledPaperExperimentOutput,
    *,
    objective: ResearchObjective,
    omitted_source_refs: Sequence[str] = (),
) -> DraftReadiness:
    """Decide whether a reconciled Draft can answer this Objective."""

    if not isinstance(output, ReconciledPaperExperimentOutput):
        raise TypeError("readiness requires ReconciledPaperExperimentOutput")
    if not isinstance(objective, ResearchObjective):
        raise TypeError("readiness requires ResearchObjective")

    missing: list[str] = []
    measurement_keys: list[str] = []
    comparison_keys: list[str] = []
    objective_outcomes = tuple(objective.outcomes)
    objective_variables = tuple(objective.variables)

    omitted = tuple(
        str(item).strip() for item in omitted_source_refs if str(item).strip()
    )
    if omitted:
        missing.append(
            "source bundle omitted Objective-relevant context: " + ", ".join(omitted)
        )

    for draft in output.output.experiments:
        scope_kind = str(draft.payload.get("scope_kind") or "unknown").casefold()
        if scope_kind == "unknown":
            missing.append(
                "experiment boundary is unknown; identity allocation requires "
                "reconciliation"
            )
        measurements = _draft_items(draft.payload, "measurements")
        variants = _draft_items(
            draft.payload, "experimental_variants", "variants"
        )
        variants_by_key = {
            str(item.get("variant_key") or "").strip(): item for item in variants
        }
        tests = _draft_items(draft.payload, "test_conditions")
        tests_by_key = {
            str(item.get("test_key") or "").strip(): item for item in tests
        }
        comparisons = _draft_items(draft.payload, "comparisons")
        measurements_by_key = {
            str(item.get("measurement_key") or "").strip(): item
            for item in measurements
        }

        for measurement in measurements:
            if not _outcome_matches(measurement.get("outcome"), objective_outcomes):
                continue
            key = str(measurement.get("measurement_key") or "").strip()
            if not key:
                continue
            measurement_reasons: list[str] = []
            if not _reference_keys(measurement, fields=("source_labels",)):
                measurement_reasons.append(
                    f"measurement {key} has no reviewable source"
                )
            missing_binding_edges = tuple(
                field
                for field in (
                    "variant_binding_source_labels",
                    "test_binding_source_labels",
                )
                if not _reference_keys(measurement, fields=(field,))
            )
            if missing_binding_edges:
                measurement_reasons.append(
                    f"measurement {key} lacks binding edges: "
                    + ", ".join(missing_binding_edges)
                )
            variant_key = str(measurement.get("variant_key") or "").strip()
            variant = variants_by_key.get(variant_key)
            if variant is None:
                measurement_reasons.append(f"measurement {key} has no variant")
            elif _variant_binding_resolution(variant, variants) != "exact":
                measurement_reasons.append(
                    f"measurement {key} variant identity is not exact"
                )
            test_key = str(measurement.get("test_key") or "").strip()
            test = tests_by_key.get(test_key)
            if test is None:
                measurement_reasons.append(
                    f"measurement {key} has no test condition"
                )
            elif _test_binding_resolution(test, tests) != "exact":
                measurement_reasons.append(
                    f"measurement {key} test identity is not exact"
                )
            elif test.get("outcome_scope") and not _outcome_matches(
                measurement.get("outcome"),
                tuple(str(item) for item in test.get("outcome_scope") or ()),
            ):
                measurement_reasons.append(
                    f"measurement {key} is outside its test outcome scope"
                )
            if measurement_reasons:
                missing.extend(measurement_reasons)
            else:
                # Only the exact subset is selected. Other reported values in
                # the same revision remain auditable partial observations and
                # must not make an otherwise usable Objective fail.
                measurement_keys.append(key)

        for comparison in comparisons:
            changed = tuple(
                str(item.get("name") or item).strip()
                if isinstance(item, Mapping)
                else str(item).strip()
                for item in comparison.get("changed_variables") or ()
            )
            if not _outcome_matches(
                comparison.get("outcome"), objective_outcomes
            ) or not any(
                _outcome_matches(item, objective_variables) for item in changed
            ):
                continue
            key = str(comparison.get("comparison_key") or "").strip()
            if not key:
                continue
            comparison_reasons: list[str] = []
            baseline_keys = _reference_keys(
                comparison, fields=("baseline_measurement_keys",)
            )
            target_keys = _reference_keys(
                comparison, fields=("target_measurement_keys",)
            )
            if not baseline_keys or not target_keys:
                comparison_reasons.append(
                    f"comparison {key} has no measurement edges"
                )
            else:
                referenced = (*baseline_keys, *target_keys)
                if any(
                    ref not in measurements_by_key
                    or ref not in measurement_keys
                    or not _outcome_matches(
                        measurements_by_key[ref].get("outcome"), objective_outcomes
                    )
                    for ref in referenced
                ):
                    comparison_reasons.append(
                        f"comparison {key} does not close over selected results"
                    )
            if not _reference_keys(comparison, fields=("source_labels",)):
                comparison_reasons.append(
                    f"comparison {key} has no reviewable source"
                )
            if comparison.get("direction_candidate") == "unknown":
                comparison_reasons.append(
                    f"comparison {key} has no unambiguous direction"
                )
            if comparison_reasons:
                missing.extend(comparison_reasons)
            else:
                comparison_keys.append(key)

    if not measurement_keys:
        missing.append("objective outcome has no reportable measurement")
    if objective_variables and not comparison_keys:
        missing.append("no closed within-paper comparison for an objective variable")

    selected_targets = {
        *(f"measurements/{key}" for key in measurement_keys),
        *(f"comparisons/{key}" for key in comparison_keys),
    }
    for issue in output.output.unresolved_issues:
        if not isinstance(issue, Mapping):
            continue
        target = str(issue.get("target_ref") or "").strip()
        description = str(issue.get("description") or "").casefold()
        if target in selected_targets and any(
            token in description
            for token in (
                "ambiguous",
                "unknown",
                "missing",
                "cannot",
                "not exact",
                "conflict",
                "blocked",
                "multiple measurements",
            )
        ):
            missing.append(f"unresolved context affects {target}")

    unique_missing = tuple(dict.fromkeys(missing))
    return DraftReadiness(
        ready=not unique_missing,
        missing_context=unique_missing,
        selected_measurement_keys=tuple(dict.fromkeys(measurement_keys)),
        selected_comparison_keys=tuple(dict.fromkeys(comparison_keys)),
        reason_codes=tuple(
            "missing_measurement"
            if "no reportable measurement" in item
            else "missing_comparison"
            if "no closed within-paper comparison" in item
            else "omitted_source"
            if "omitted" in item
            else "unresolved_context"
            for item in unique_missing
        ),
    )


def reconcile_model_output(
    output: PaperExperimentModelOutput,
    *,
    accepted_experiment_keys: Sequence[str],
    audit_issues: Sequence[Mapping[str, Any]] = (),
) -> ReconciledPaperExperimentOutput:
    """Create the service-owned write handoff after boundary reconciliation.

    This function does not claim that a model response is scientifically
    complete.  It verifies the structural precondition for identity allocation:
    callers must provide the scopes selected by their parent-first reconciler,
    and a Draft must not still be carrying a raw boundary-proposal envelope.
    Broad sample/test facts remain valid and are intentionally not rejected.
    """

    if not isinstance(output, PaperExperimentModelOutput):
        raise TypeError("boundary reconciliation requires PaperExperimentModelOutput")
    raw_boundary_fields = {
        "boundaries",
        "boundary_proposals",
        "raw_boundary_proposals",
    }
    accepted_input = tuple(str(key).strip() for key in accepted_experiment_keys)
    if any(not key for key in accepted_input) or len(set(accepted_input)) != len(accepted_input):
        raise ValueError("accepted experiment keys must be non-empty and unique")

    local_payloads = {
        _local_series_key(item.payload): item.payload
        for item in output.experiments
        if _local_series_key(item.payload)
    }
    # Only an explicit parent/matrix proposal can establish a physical parent.
    # ``unknown`` is deliberately *not* a parent: treating the first unknown
    # proposal as the archive owner is the source of the boundary-first
    # over-merge bug.  It turns an arbitrary section/table view into the
    # experiment identity before the service has reconciled its scope.
    has_physical_parent = any(
        _boundary_kind(item.payload) in _EXPLICIT_PARENT_KINDS
        for item in output.experiments
    )
    synthetic_parent_allowed = len(output.experiments) > 1 and not has_physical_parent

    for index, draft in enumerate(output.experiments):
        payload = draft.payload
        leaked = sorted(raw_boundary_fields.intersection(payload))
        if leaked:
            raise ValueError(
                "raw boundary proposals must be reconciled before identity "
                f"allocation (experiments[{index}]: {', '.join(leaked)})"
            )
        scope_kind = str(payload.get("scope_kind") or "").strip().lower()
        if scope_kind in {"selected_stratum", "follow_up"}:
            selector = payload.get("scope_selector")
            parent_key = str(payload.get("parent_series_key") or "").strip()
            if not isinstance(selector, Mapping) or not any(
                selector.get(field)
                for field in (
                    "fixed_attributes",
                    "varied_attributes",
                    "selected_levels",
                    "included_states",
                    "population_scope_labels",
                    "test_scope_labels",
                )
            ):
                raise ValueError(
                    "selected/follow-up scope requires a reconciled scope_selector"
                )
            if not parent_key:
                raise ValueError(
                    "selected/follow-up scope requires a reconciled parent_series_key"
                )
            if (
                parent_key not in accepted_input
                and parent_key not in local_payloads
                and not synthetic_parent_allowed
            ):
                raise ValueError(
                    "selected/follow-up scope parent is not a reconciled experiment"
                )
            parent_payload = local_payloads.get(parent_key)
            if not _selector_hits_local_facts(
                payload,
                selector,
                extra_payloads=(parent_payload,) if parent_payload else tuple(local_payloads.values()),
            ):
                raise ValueError(
                    "selected/follow-up scope selector does not match local facts"
                )
        if scope_kind in {"physical_split", "split", "independent"} and not _has_positive_split_evidence(
            payload, draft, set(output.source_labels)
        ):
            raise ValueError(
                "physical split requires source-backed split evidence"
            )

    reconciled_drafts, reconciliation_issues = _collapse_boundary_drafts(
        output.experiments,
        accepted_input,
    )
    accepted = _map_reconciled_experiment_keys(
        reconciled_drafts,
        accepted_input,
    )
    accepted = tuple(str(key).strip() for key in accepted)
    if len(set(accepted)) != len(accepted) or any(not key for key in accepted):
        raise ValueError("accepted experiment keys must be non-empty and unique")
    for draft, key in zip(reconciled_drafts, accepted, strict=True):
        declared = _local_series_key(draft.payload)
        if declared and declared != key:
            raise ValueError(
                f"accepted experiment key {key!r} does not match draft series {declared!r}"
            )

    merged_output = output
    all_audit_issues = (*audit_issues, *reconciliation_issues)
    if all_audit_issues or tuple(reconciled_drafts) != output.experiments:
        merged_output = replace(
            output,
            experiments=tuple(reconciled_drafts),
            unresolved_issues=(
                *output.unresolved_issues,
                *(dict(item) for item in all_audit_issues if isinstance(item, Mapping)),
            ),
        )
    return ReconciledPaperExperimentOutput(
        output=merged_output,
        accepted_experiment_keys=accepted,
        audit_issues=tuple(all_audit_issues),
    )


def _map_reconciled_experiment_keys(
    drafts: Sequence[PaperExperimentDraft],
    accepted_input: Sequence[str],
) -> tuple[str, ...]:
    """Map accepted local keys by retained scope identity, not array position.

    Boundary reconciliation can collapse several advisory scopes into one
    parent while retaining a later physical split.  Positional slicing would
    then assign the removed scope's key to that split.  A retained draft must
    therefore either carry its own accepted local key or, for a service-created
    synthetic parent, explicitly name the accepted parent key.
    """

    if not drafts:
        return ()
    accepted = tuple(str(key).strip() for key in accepted_input)
    available = set(accepted)
    mapped: list[str] = []
    for index, draft in enumerate(drafts):
        declared = _local_series_key(draft.payload)
        chosen = declared if declared in available else ""
        if not chosen and index == 0 and draft.payload.get("synthetic_parent"):
            parent_key = str(draft.payload.get("parent_series_key") or "").strip()
            if parent_key in available:
                chosen = parent_key
        # Older callers may omit a local series key when there is exactly one
        # retained scope and provide only the service-selected key. Preserve
        # that established single-scope contract; multi-scope reconciliation
        # remains strict and must use each retained draft's local key.
        if not chosen and len(drafts) == 1 and not declared and len(available) == 1:
            chosen = next(iter(available))
        if not chosen:
            raise ValueError(
                "boundary reconciliation must provide an accepted key for retained "
                f"scope {declared or index!r}"
            )
        mapped.append(chosen)
        available.remove(chosen)
    return tuple(mapped)


def _local_series_key(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("series_key")
        or payload.get("series_id")
        or payload.get("experiment_key")
        or ""
    ).strip()


def _generated_series_key(payload: Mapping[str, Any], *, index: int) -> str:
    """Create a deterministic response-local scope key when the model omits one.

    This is deliberately not a domain identity.  It only gives the service a
    stable join key for the current Draft so local component references and
    boundary reconciliation can proceed.  Formal experiment IDs are still
    allocated by the writer after reconciliation.
    """

    identity = {
        "index": index,
        "label": payload.get("label"),
        "scope_description": payload.get("scope_description"),
        "design_type": payload.get("design_type"),
        "scope_kind": payload.get("scope_kind"),
        "parent_series_key": payload.get("parent_series_key"),
        "variants": payload.get("experimental_variants")
        or payload.get("variants")
        or (),
        "tests": payload.get("test_conditions") or (),
    }
    digest = hashlib.sha1(
        json.dumps(identity, ensure_ascii=True, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    return f"draft_{digest}"


# Boundary labels are advisory, but these categories have distinct service
# semantics.  In particular, an omitted/unknown kind must not be promoted to
# a physical parent merely because it appeared first in the model response.
# An omitted scope kind is the legacy/default parent shape.  It is different
# from an explicit ``unknown`` proposal: the former is a complete ordinary
# draft, while the latter is an unresolved boundary candidate and must never
# become a parent merely because it was returned first.
_EXPLICIT_PARENT_KINDS = frozenset({"", "parent", "matrix"})
_OVERLAPPING_SCOPE_KINDS = frozenset({"selected_stratum", "follow_up"})
_PHYSICAL_SPLIT_KINDS = frozenset({"physical_split", "split", "independent"})


def _boundary_kind(payload: Mapping[str, Any]) -> str:
    return str(payload.get("scope_kind") or "").strip().lower()


def _is_explicit_parent_proposal(payload: Mapping[str, Any]) -> bool:
    """Distinguish an explicit parent declaration from the legacy default."""

    return str(payload.get("scope_kind") or "").strip().casefold() in {
        "parent",
        "matrix",
    }


def _has_positive_split_evidence(
    payload: Mapping[str, Any],
    draft: PaperExperimentDraft,
    source_catalog: set[str],
) -> bool:
    reason = str(payload.get("split_reason") or "").strip().lower()
    evidence = payload.get("split_evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence or not reason:
        return False
    labels = set(draft.source_labels) | _collect_source_labels(payload)
    evidence_labels = {
        str(item.get("source_label") or item.get("source_ref") or "").strip()
        if isinstance(item, Mapping)
        else str(item).strip()
        for item in evidence
    }
    evidence_labels.discard("")
    return bool(
        evidence_labels
        and evidence_labels <= source_catalog
        and evidence_labels & labels
        and any(
            marker in reason
            for marker in (
                "different population",
                "separate population",
                "different assignment",
                "independent assignment",
                "different design",
                "separate design",
                "different cohort",
                "different specimen",
                "不同群体",
                "不同分配",
                "不同设计",
                "独立样品",
            )
        )
    )


def _selector_hits_local_facts(
    payload: Mapping[str, Any],
    selector: Mapping[str, Any],
    *,
    extra_payloads: Sequence[Mapping[str, Any]] = (),
) -> bool:
    """Require an overlapping selector to hit a concrete local fact."""

    payloads = (payload, *extra_payloads)
    variants: list[Mapping[str, Any]] = []
    tests: list[Mapping[str, Any]] = []
    for candidate in payloads:
        variants.extend(
            item
            for item in (
                candidate.get("variants")
                or candidate.get("experimental_variants")
                or ()
            )
            if isinstance(item, Mapping)
        )
        tests.extend(
            item
            for item in candidate.get("test_conditions") or ()
            if isinstance(item, Mapping)
        )

    def scalar_equal(left: Any, right: Any) -> bool:
        left_text = str(left).strip().casefold()
        right_text = str(right).strip().casefold()
        if not left_text or not right_text:
            return False
        try:
            return float(left_text) == float(right_text)
        except ValueError:
            return left_text == right_text

    def variant_attributes(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        attrs: list[Mapping[str, Any]] = []
        for field in ("subject_attributes", "intervention_attributes", "state", "attributes"):
            attrs.extend(
                value for value in item.get(field) or () if isinstance(value, Mapping)
            )
        return attrs

    level_requirements = [
        item
        for field in ("selected_levels", "fixed_attributes")
        for item in selector.get(field) or ()
        if isinstance(item, Mapping)
    ]
    if level_requirements:
        # All selected levels must occur on one concrete variant.  Checking a
        # union of unrelated rows would make a 999/100 selector appear valid.
        if not any(
            all(
                any(
                    scalar_equal(attribute.get("value"), requirement.get("value"))
                    and (
                        not requirement.get("name")
                        or str(attribute.get("name") or "").strip().casefold()
                        == str(requirement.get("name") or "").strip().casefold()
                    )
                    for attribute in variant_attributes(variant)
                )
                or scalar_equal(
                    requirement.get("value"),
                    str(variant.get("variant_label") or "").replace("P", ""),
                )
                for requirement in level_requirements
            )
            for variant in variants
        ):
            # A label such as P150 is a valid source-local shorthand for one
            # selected level even when the model did not repeat an attribute.
            label_text = " ".join(str(item.get("variant_label") or "") for item in variants)
            for requirement in level_requirements:
                value = str(requirement.get("value") or "").strip()
                if not value or not re.search(rf"(?<!\d){re.escape(value)}(?!\d)", label_text):
                    return False
    for field in ("included_states", "population_scope_labels"):
        for item in selector.get(field) or ():
            token = str(item).strip().casefold()
            if token and not any(token in str(variant).casefold() for variant in variants):
                return False
    test_labels = [str(item).strip().casefold() for item in selector.get("test_scope_labels") or ()]
    if test_labels and not any(
        all(label in str(test).casefold() for label in test_labels) for test in tests
    ):
        return False
    named_fields = [
        str(item).strip().casefold()
        for item in selector.get("varied_attributes") or ()
        if not isinstance(item, Mapping)
    ]
    if named_fields and not any(
        all(
            any(str(attribute.get("name") or "").strip().casefold() == name for attribute in variant_attributes(variant))
            for name in named_fields
        )
        for variant in variants
    ):
        return False
    return bool(level_requirements or test_labels or named_fields or selector.get("included_states") or selector.get("population_scope_labels"))


def _merge_draft_payloads(
    target: dict[str, Any], incoming: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    issues: list[Mapping[str, Any]] = []
    sequence_fields = (
        "variants",
        "experimental_variants",
        "test_conditions",
        "measurements",
        "comparisons",
        "reported_interpretations",
        "unresolved_issues",
    )
    for field in sequence_fields:
        incoming_items = incoming.get(field)
        if not isinstance(incoming_items, (list, tuple)):
            continue
        current = target.setdefault(field, [])
        if not isinstance(current, list):
            current = list(current) if isinstance(current, (list, tuple)) else []
            target[field] = current
        key_field = {
            "variants": "variant_key",
            "experimental_variants": "variant_key",
            "test_conditions": "test_key",
            "measurements": "measurement_key",
            "comparisons": "comparison_key",
            "reported_interpretations": "interpretation_key",
        }.get(field)
        existing_keys = {
            str(item.get(key_field))
            for item in current
            if key_field and isinstance(item, Mapping) and item.get(key_field)
        }
        for item in incoming_items:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get(key_field)) if key_field else ""
            if key and key in existing_keys:
                # Repeated source-local records are one semantic object; retain
                # any extra source labels and leave conflicting scalar values in
                # the audit instead of silently choosing one.
                match = next(
                    existing for existing in current
                    if isinstance(existing, Mapping)
                    and str(existing.get(key_field)) == key
                )
                if isinstance(match, dict):
                    compared_fields = [
                        "value",
                        "unit",
                        "result_text",
                        "statistics",
                    ]
                    if field == "measurements":
                        # A repeated local key with the same numeric value but a
                        # different sample/test edge is not a harmless duplicate.
                        # Preserve it as a conflict so a later resolver cannot
                        # silently keep whichever response arrived first.
                        compared_fields.extend(
                            [
                                "variant_key",
                                "test_key",
                                "measurement_scope",
                                "reported_sample_label",
                                "reported_test_label",
                            ]
                        )
                    conflicting = [
                        name
                        for name in compared_fields
                        if name in item
                        and match.get(name) not in (None, "", [], {})
                        and item.get(name) not in (None, "", [], {})
                        and match.get(name) != item.get(name)
                    ]
                    if conflicting and field == "measurements":
                        conflict_key = f"{key}__conflict_{len(current) + 1}"
                        preserved = dict(item)
                        preserved[key_field] = conflict_key
                        preserved["conflict_of"] = key
                        current.append(preserved)
                        existing_keys.add(conflict_key)
                        issues.append(
                            {
                                "target_ref": f"measurements/{key}",
                                "description": (
                                    "conflict: source reports were retained as separate "
                                    "measurements instead of choosing one value."
                                ),
                                "conflict_fields": conflicting,
                                "source_labels": list(
                                    dict.fromkeys(
                                        [
                                            *(match.get("source_labels") or ()),
                                            *(item.get("source_labels") or ()),
                                        ]
                                    )
                                ),
                            }
                        )
                        continue
                    for name, value in item.items():
                        if name in {
                            "source_labels",
                            "binding_source_labels",
                            "variant_binding_source_labels",
                            "test_binding_source_labels",
                        }:
                            match[name] = list(
                                dict.fromkeys(
                                    [
                                        *_source_labels(match.get(name)),
                                        *_source_labels(value),
                                    ]
                                )
                            )
                            continue
                        if name not in match or match.get(name) in (None, "", [], {}):
                            match[name] = value
                continue
            current.append(dict(item))
            if key:
                existing_keys.add(key)
    for field in ("source_labels", "unknown_fields", "split_evidence"):
        incoming_items = incoming.get(field)
        if isinstance(incoming_items, (list, tuple)):
            target[field] = list(dict.fromkeys([
                *(target.get(field) or ()),
                *incoming_items,
            ]))
    return tuple(issues)


def _boundary_variant_signature(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the physical variant facts used to justify a boundary merge.

    Local keys and Source labels are response mechanics.  A merge is allowed
    only when the two proposals describe the same reported variants and
    physical context; otherwise an ``unknown`` proposal remains its own
    partial archive instead of being absorbed by whichever parent came first.
    """

    def scientific_value(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): scientific_value(nested)
                for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
                if str(key) not in {
                    "source_label",
                    "source_labels",
                    "binding_source_labels",
                    "variant_binding_source_labels",
                    "test_binding_source_labels",
                    "variant_key",
                    "variant_id",
                    "binding_status",
                    "identity_specificity",
                    "identity_evidence",
                    "missing_dimensions",
                    "notes",
                }
            }
        if isinstance(value, (list, tuple)):
            normalized = [scientific_value(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(
                    item, ensure_ascii=True, sort_keys=True, default=str
                ),
            )
        return value

    signatures: list[str] = []
    for variant in _draft_items(payload, "experimental_variants", "variants"):
        record = {
            "variant_label": unicodedata.normalize(
                "NFKC", str(variant.get("variant_label") or "")
            ).casefold().strip(),
            "subject_attributes": scientific_value(
                variant.get("subject_attributes") or ()
            ),
            "intervention_attributes": scientific_value(
                variant.get("intervention_attributes") or ()
            ),
            "state": scientific_value(variant.get("state") or ()),
            "population_scope": scientific_value(
                variant.get("population_scope") or {}
            ),
        }
        signatures.append(
            json.dumps(record, ensure_ascii=True, sort_keys=True, default=str)
        )
    return tuple(sorted(signatures))


def _unknown_scope_matches_parent(
    parent: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> bool:
    parent_signature = _boundary_variant_signature(parent)
    candidate_signature = _boundary_variant_signature(candidate)
    if not parent_signature or parent_signature != candidate_signature:
        return False
    parent_design = str(parent.get("design_type") or "unknown").strip().casefold()
    candidate_design = str(candidate.get("design_type") or "unknown").strip().casefold()
    return (
        parent_design == candidate_design
        or parent_design in {"", "unknown"}
        or candidate_design in {"", "unknown"}
    )


def _collapse_boundary_drafts(
    drafts: Sequence[PaperExperimentDraft],
    accepted_keys: Sequence[str],
) -> tuple[tuple[PaperExperimentDraft, ...], tuple[Mapping[str, Any], ...]]:
    if len(drafts) <= 1:
        return tuple(drafts), ()

    # A response containing only source-backed physical splits has no parent
    # series to synthesize.  Selecting the first draft as a fallback parent
    # would silently erase one independent experiment boundary and make its
    # identity depend on response ordering.  Keep every split as its own
    # retained scope; the normal accepted-key mapping will validate that each
    # one has a distinct service-selected key.
    if all(_boundary_kind(draft.payload) in _PHYSICAL_SPLIT_KINDS for draft in drafts):
        return tuple(drafts), ()

    has_explicit_parent = any(
        _boundary_kind(draft.payload) in _EXPLICIT_PARENT_KINDS
        for draft in drafts
    )
    explicit_parent_indexes = tuple(
        index
        for index, draft in enumerate(drafts)
        if _is_explicit_parent_proposal(draft.payload)
    )
    if len(explicit_parent_indexes) > 1:
        # There is no safe way to infer that two independently named parent
        # scopes are complementary views of one physical experiment.  The
        # previous implementation selected the first parent and merged every
        # other parent into it, making experiment identity depend on provider
        # response order and silently moving measurements across boundaries.
        # Preserve every proposal and make the ambiguity explicit so the
        # caller can reconcile it with more Source context or a human review.
        return tuple(drafts), (
            {
                "target_ref": "experiment",
                "description": (
                    "Multiple explicit parent experiment scopes were returned; "
                    "they were retained separately until their physical boundary "
                    "is reconciled."
                ),
                "parent_series_keys": [
                    _local_series_key(drafts[index].payload) or str(index)
                    for index in explicit_parent_indexes
                ],
            },
        )
    if not has_explicit_parent and any(
        _boundary_kind(draft.payload) == "unknown" for draft in drafts
    ):
        # A selected/follow-up view cannot promote an unresolved candidate to
        # a physical parent.  Keep both records partial until a later Source
        # establishes their relationship.
        return tuple(drafts), ()

    # Only an explicit ``parent``/``matrix`` proposal can be the physical
    # container.  In particular, ``unknown`` must remain unresolved: choosing
    # the first unknown response as the parent would make experiment identity
    # depend on provider ordering and silently merge independent studies.
    parent_index = next(
        (
            index
            for index, draft in enumerate(drafts)
            if _boundary_kind(draft.payload) in _EXPLICIT_PARENT_KINDS
        ),
        None,
    )
    if parent_index is None:
        # With no explicit/unknown parent, a selected or follow-up scope is
        # the only valid synthetic container.  A physical split is never a
        # fallback parent: doing so would absorb an independent experiment
        # merely because the model returned it first.
        parent_index = next(
            (
                index
                for index, draft in enumerate(drafts)
                if _boundary_kind(draft.payload) in _OVERLAPPING_SCOPE_KINDS
            ),
            None,
        )
    if parent_index is None:
        # This is reachable for a mixed response only when every remaining
        # scope is a physical split; keep the scopes independent and let the
        # accepted-key check enforce one key per split.
        return tuple(drafts), ()
    parent = drafts[parent_index]
    parent_payload = dict(parent.payload)
    parent_kind = str(parent_payload.get("scope_kind") or "").strip().lower()
    parent_is_scope = parent_kind in {"selected_stratum", "follow_up"}
    local_keys = {_local_series_key(item.payload) for item in drafts}
    declared_parent_key = _local_series_key(parent_payload)
    requested_parent_key = str(parent_payload.get("parent_series_key") or "").strip()
    if parent_is_scope:
        # Prefer the retained scope's own key when the service accepted it.
        # If the model referenced a service-created synthetic parent, honor
        # that key instead; this also works when a physical split precedes the
        # selected scope in the response.
        parent_key = next(
            (
                candidate
                for candidate in (
                    requested_parent_key,
                    declared_parent_key,
                    accepted_keys[0] if accepted_keys else "",
                )
                if candidate and candidate in accepted_keys
            ),
            declared_parent_key
            or (accepted_keys[0] if accepted_keys else "parent"),
        )
    else:
        parent_key = declared_parent_key or (accepted_keys[0] if accepted_keys else "parent")
    if parent_is_scope:
        parent_payload["series_key"] = parent_key
    parent_payload.setdefault("series_key", parent_key)
    parent_was_synthetic = parent_is_scope
    parent_payload["scope_kind"] = "parent"
    if parent_was_synthetic:
        parent_payload["synthetic_parent"] = True
    scope_views: list[dict[str, Any]] = list(parent_payload.get("scope_views") or ())
    if parent_was_synthetic:
        scope_views.append(
            {
                "series_key": _local_series_key(parent.payload) or "scope-0",
                "scope_kind": str(parent.payload.get("scope_kind") or "unknown"),
                "parent_series_key": str(parent.payload.get("parent_series_key") or parent_key),
                "scope_selector": dict(parent.payload.get("scope_selector") or {}),
            }
        )
    parent_labels = set(parent.source_labels)
    parent_issues = [dict(item) for item in parent.unresolved_issues]
    retained: list[PaperExperimentDraft] = []
    audit: list[Mapping[str, Any]] = []
    for index, draft in enumerate(drafts):
        if index == parent_index:
            continue
        kind = str(draft.payload.get("scope_kind") or "").strip().lower()
        if kind in {"physical_split", "split", "independent"}:
            retained.append(draft)
            continue
        if kind == "unknown" and not _unknown_scope_matches_parent(
            parent_payload, draft.payload
        ):
            retained.append(draft)
            audit.append(
                {
                    "target_ref": (
                        f"experiments/{_local_series_key(draft.payload) or index}"
                    ),
                    "description": (
                        "Experiment boundary remains unknown; the candidate was "
                        "retained separately because its physical variant scope "
                        "does not match the explicit parent."
                    ),
                }
            )
            continue
        merge_issues = _merge_draft_payloads(parent_payload, draft.payload)
        audit.extend(merge_issues)
        parent_labels.update(draft.source_labels)
        parent_issues.extend(dict(item) for item in draft.unresolved_issues)
        if kind in {"selected_stratum", "follow_up"}:
            scope_views.append(
                {
                    "series_key": _local_series_key(draft.payload) or str(index),
                    "scope_kind": kind,
                    "parent_series_key": parent_key,
                    "scope_selector": dict(draft.payload.get("scope_selector") or {}),
                }
            )
        audit.append(
            {
                "target_ref": f"experiments/{_local_series_key(draft.payload) or index}",
                "description": (
                    "Boundary proposal was collapsed into the parent because a section, "
                    "table, outcome, or overlapping scope does not establish a distinct "
                    "physical experiment."
                ),
            }
        )
    merged_parent = PaperExperimentDraft(
        payload={**parent_payload, "scope_views": scope_views} if scope_views else parent_payload,
        source_labels=tuple(sorted(parent_labels)),
        unresolved_issues=tuple(parent_issues),
    )
    return (merged_parent, *retained), tuple(audit)


def _issues_for_draft(
    output: ReconciledPaperExperimentOutput,
    *,
    draft: PaperExperimentDraft,
    accepted_key: str,
) -> tuple[Mapping[str, Any], ...]:
    """Select preparation audit issues owned by one response-local Draft."""

    payload = draft.payload
    variant_keys = _require_unique_local_keys(
        _draft_items(payload, "experimental_variants", "variants"),
        field="variant_key",
        path="draft experimental_variants",
    )
    test_keys = _require_unique_local_keys(
        _draft_items(payload, "test_conditions"),
        field="test_key",
        path="draft test_conditions",
    )
    measurement_keys = _require_unique_local_keys(
        _draft_items(payload, "measurements"),
        field="measurement_key",
        path="draft measurements",
    )
    comparison_keys = _require_unique_local_keys(
        _draft_items(payload, "comparisons"),
        field="comparison_key",
        path="draft comparisons",
    )
    local_targets = {
        f"experiments/{accepted_key}",
        *(f"variants/{key}" for key in variant_keys),
        *(f"experimental_variants/{key}" for key in variant_keys),
        *(f"sample_variants/{key}" for key in variant_keys),
        *(f"tests/{key}" for key in test_keys),
        *(f"test_conditions/{key}" for key in test_keys),
        *(f"measurements/{key}" for key in measurement_keys),
        *(f"comparisons/{key}" for key in comparison_keys),
    }
    selected: list[Mapping[str, Any]] = []
    for issue in output.output.unresolved_issues:
        if not isinstance(issue, Mapping):
            continue
        target = str(issue.get("target_ref") or "").strip()
        if target in local_targets or (
            target == "experiment" and len(output.output.experiments) == 1
        ):
            selected.append(issue)
    return tuple(selected)


def bind_model_output(
    output: ReconciledPaperExperimentOutput,
    *,
    experiment_ids: Sequence[str],
    experiment_versions: Sequence[int],
    document_id: str,
    source_fingerprint: str,
) -> tuple[PaperExperimentRevision, ...]:
    """Resolve sources and inject formal identity after reconciliation only."""

    if not isinstance(output, ReconciledPaperExperimentOutput):
        raise ValueError(
            "formal identity allocation requires boundary reconciliation; "
            "call reconcile_model_output first"
        )
    model_output = output.output

    if model_output.document_id != document_id:
        raise ValueError("model output document does not match request")
    if model_output.source_fingerprint != source_fingerprint:
        raise ValueError("model output source fingerprint does not match request")
    if len(model_output.experiments) != len(experiment_ids) or len(model_output.experiments) != len(
        experiment_versions
    ):
        raise ValueError("formal identity count must match draft experiment count")

    labels = {
        label: SourceReference.from_mapping(reference)
        for label, reference in model_output.source_labels.items()
    }
    revisions: list[PaperExperimentRevision] = []
    for draft, accepted_key, experiment_id, experiment_version in zip(
        model_output.experiments,
        output.accepted_experiment_keys,
        experiment_ids,
        experiment_versions,
        strict=True,
    ):
        draft_payload = dict(draft.payload)
        if draft.source_labels:
            draft_payload["source_labels"] = list(draft.source_labels)
        content = _resolve_source_labels(draft_payload, labels)
        boundary_refs = _resolve_boundary_evidence_refs(draft_payload, labels)
        if boundary_refs:
            # ``split_evidence`` is a Draft-only shape.  The revision schema
            # does not need another boundary entity, but it must retain the
            # Source lineage that justified an independent scope.  Keep those
            # references in the experiment-level Source set and add a small
            # audit record so a later reader can distinguish them from value
            # or measurement evidence.
            content["source_refs"] = _dedupe_records(
                [
                    *(item for item in content.get("source_refs") or () if isinstance(item, Mapping)),
                    *boundary_refs,
                ]
            )
        _validate_source_context(content, document_id, source_fingerprint)
        draft_source_refs = content.get("source_refs") or ()
        content["source_refs"] = _dedupe_records(
            item for item in draft_source_refs if isinstance(item, Mapping)
        )
        content["experiment_id"] = experiment_id
        content["experiment_version"] = experiment_version
        content["document_id"] = document_id
        content["source_fingerprint"] = source_fingerprint
        relevant_issues = _issues_for_draft(
            output,
            draft=draft,
            accepted_key=accepted_key,
        )
        content["unresolved_issues"] = _dedupe_records(
            item
            for item in _resolve_source_labels(
                [*draft.unresolved_issues, *relevant_issues], labels
            )
            if isinstance(item, Mapping)
        )
        boundary_issue = _boundary_scope_issue(
            draft_payload,
            boundary_refs=boundary_refs,
        )
        if boundary_issue is not None:
            content["unresolved_issues"] = _dedupe_records(
                [*content["unresolved_issues"], boundary_issue]
            )
        content = _preserve_reported_measurement_scope(content)
        content = _resolve_measurement_bindings(content)
        revisions.append(PaperExperimentRevision.from_mapping(content))
    return tuple(revisions)


def _validate_source_context(
    content: Mapping[str, Any], document_id: str, source_fingerprint: str
) -> None:
    for reference in _iter_source_records(content):
        if str(reference.get("document_id") or "") != document_id:
            raise ValueError("source reference document does not match request")
        if str(reference.get("source_fingerprint") or "") != source_fingerprint:
            raise ValueError("source reference fingerprint does not match request")


def _resolve_boundary_evidence_refs(
    payload: Mapping[str, Any],
    labels: Mapping[str, SourceReference],
) -> list[dict[str, Any]]:
    """Resolve Draft-only split evidence without persisting model labels.

    Boundary evidence is not a measurement and therefore does not deserve a
    new scientific component table.  It is nevertheless provenance for the
    experiment identity.  Resolving it here lets the revision retain that
    provenance in its existing experiment-level ``source_refs`` field.
    """

    raw_evidence = payload.get("split_evidence") or ()
    if not isinstance(raw_evidence, (list, tuple)):
        return []
    resolved: list[dict[str, Any]] = []
    for item in raw_evidence:
        if isinstance(item, str):
            raw_labels: tuple[Any, ...] = (item,)
        elif isinstance(item, Mapping):
            values: list[Any] = []
            for field in ("source_label", "source_labels", "binding_source_labels"):
                value = item.get(field)
                if isinstance(value, (list, tuple)):
                    values.extend(value)
                elif value not in (None, ""):
                    values.append(value)
            raw_labels = tuple(values)
        else:
            raw_labels = ()
        for raw_label in raw_labels:
            label = str(raw_label).strip()
            if not label:
                continue
            reference = labels.get(label)
            if reference is None:
                raise ValueError(f"unknown source label: {label}")
            resolved.append(reference.to_record())
    return _dedupe_records(resolved)


def _boundary_scope_issue(
    payload: Mapping[str, Any],
    *,
    boundary_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Return an auditable record for non-default experiment scope metadata."""

    scope_kind = str(payload.get("scope_kind") or "").strip().casefold()
    scope_selector = payload.get("scope_selector")
    parent_series_key = str(payload.get("parent_series_key") or "").strip()
    scope_views = payload.get("scope_views")
    is_non_default = bool(
        scope_kind not in {"", "parent", "matrix"}
        or scope_selector
        or parent_series_key
        or payload.get("synthetic_parent")
        or scope_views
        or boundary_refs
    )
    if not is_non_default:
        return None
    metadata: dict[str, Any] = {}
    if scope_kind:
        metadata["scope_kind"] = scope_kind
    if parent_series_key:
        metadata["parent_series_key"] = parent_series_key
    if isinstance(scope_selector, Mapping):
        metadata["scope_selector"] = dict(scope_selector)
    if isinstance(scope_views, (list, tuple)) and scope_views:
        metadata["scope_views"] = [
            dict(item) for item in scope_views if isinstance(item, Mapping)
        ]
    if payload.get("synthetic_parent"):
        metadata["synthetic_parent"] = True
    issue: dict[str, Any] = {
        "target_ref": "experiment",
        "description": (
            "Experiment boundary metadata was reconciled by the service; the "
            "stored scope is not an additional physical experiment."
        ),
        "boundary_scope": metadata,
    }
    if boundary_refs:
        issue["source_refs"] = [dict(item) for item in boundary_refs]
    return issue


def _iter_source_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {
                "source_refs",
                "binding_source_refs",
                "variant_binding_source_refs",
                "test_binding_source_refs",
            }:
                if isinstance(nested, (list, tuple)):
                    for item in nested:
                        if isinstance(item, Mapping):
                            yield item
                continue
            yield from _iter_source_records(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_source_records(nested)


def _resolve_measurement_bindings(content: Mapping[str, Any]) -> dict[str, Any]:
    """Compute an honest exact/partial binding state from resolved local facts."""

    result = dict(content)
    variants = [
        dict(item)
        for item in result.get("variants") or result.get("experimental_variants") or ()
        if isinstance(item, Mapping)
    ]
    tests = [
        dict(item)
        for item in result.get("test_conditions") or ()
        if isinstance(item, Mapping)
    ]
    variant_keys = {
        str(item.get("variant_key") or item.get("variant_id") or "")
        for item in variants
    }
    test_by_key = {
        str(item.get("test_key") or item.get("test_condition_id") or ""): item
        for item in tests
    }
    variant_resolutions = {
        str(item.get("variant_key") or item.get("variant_id") or ""):
        _variant_binding_resolution(item, variants)
        for item in variants
    }
    test_resolutions = {
        key: _test_binding_resolution(item, tests)
        for key, item in test_by_key.items()
    }
    for variant in variants:
        key = str(variant.get("variant_key") or variant.get("variant_id") or "")
        variant["binding_status"] = (
            "direct"
            if variant_resolutions.get(key) == "exact" and variant.get("source_refs")
            else "uncertain"
        )
    for test in tests:
        key = str(test.get("test_key") or test.get("test_condition_id") or "")
        resolution = test_resolutions.get(key, "unbound")
        test["binding_status"] = (
            "direct"
            if resolution == "exact" and test.get("source_refs")
            else "uncertain"
        )
        test["test_identity_status"] = (
            "identified"
            if resolution == "exact"
            else "partial"
            if resolution not in {"unbound", "category"}
            else "unknown"
        )
    result["experimental_variants"] = variants
    result.pop("variants", None)
    result["test_conditions"] = tests
    result["identity_status"] = (
        "identified"
        if variants and all(value == "exact" for value in variant_resolutions.values())
        else "partial"
        if variants
        else "unknown"
    )

    measurements: list[dict[str, Any]] = []
    issues = [
        dict(item)
        for item in result.get("unresolved_issues") or ()
        if isinstance(item, Mapping)
    ]
    exact_count = 0
    for raw in result.get("measurements") or ():
        if not isinstance(raw, Mapping):
            continue
        measurement = dict(raw)
        variant_key = str(
            measurement.get("variant_key") or measurement.get("variant_id") or ""
        )
        test_key = str(
            measurement.get("test_key") or measurement.get("test_condition_id") or ""
        )
        variant_refs = [
            dict(item)
            for item in measurement.get("variant_binding_source_refs") or ()
            if isinstance(item, Mapping)
        ]
        test_refs = [
            dict(item)
            for item in measurement.get("test_binding_source_refs") or ()
            if isinstance(item, Mapping)
        ]
        combined_refs = _dedupe_records([*variant_refs, *test_refs])
        test_record = test_by_key.get(test_key, {})
        variant_record = next(
            (
                item
                for item in variants
                if str(item.get("variant_key") or item.get("variant_id") or "")
                == variant_key
            ),
            {},
        )
        variant_resolution = variant_resolutions.get(variant_key, "unbound")
        test_resolution = test_resolutions.get(test_key, "unbound")
        outcome_scope = tuple(
            str(item).strip()
            for item in test_record.get("outcome_scope") or ()
            if str(item).strip()
        )
        outcome_scope_matches = not outcome_scope or _outcome_matches(
            measurement.get("outcome"), outcome_scope
        )
        exact = bool(
            variant_key
            and variant_key in variant_keys
            and test_key
            and test_key in test_by_key
            and variant_resolution == "exact"
            and variant_refs
            and test_refs
            and test_resolution == "exact"
            and outcome_scope_matches
        )
        scope = dict(measurement.get("measurement_scope") or {})
        resolution = "exact" if exact else (
            "unbound"
            if variant_resolution == "unbound" or test_resolution == "unbound"
            else "ambiguous"
            if (
                variant_resolution == "ambiguous"
                or test_resolution == "ambiguous"
                or measurement.get("candidate_variant_keys")
                or measurement.get("candidate_test_keys")
            )
            else "partial"
        )
        scope["binding_resolution"] = resolution
        scope["variant_binding_resolution"] = variant_resolution
        scope["test_binding_resolution"] = test_resolution
        scope["test_protocol_completeness"] = str(
            test_record.get("protocol_completeness") or "unknown"
        ).strip().lower()
        measurement["measurement_scope"] = scope
        if combined_refs:
            measurement["binding_source_refs"] = combined_refs
        measurement["binding_status"] = "direct" if exact else "uncertain"
        if exact:
            exact_count += 1
        else:
            measurement_key = str(
                measurement.get("measurement_key")
                or measurement.get("measurement_id")
                or "measurement"
            )
            issue = {
                "target_ref": f"measurements/{measurement_key}",
                "description": (
                    "Measurement is retained as a reported fact but is not exact: "
                    "both result-level binding edges and a concrete, "
                    "outcome-applicable test identity are required before strict "
                    "comparison; protocol completeness remains a recorded "
                    "limitation."
                ),
                "binding_resolution": resolution,
            }
            if not any(
                item.get("target_ref") == issue["target_ref"]
                and "not exact" in str(item.get("description"))
                for item in issues
            ):
                issues.append(issue)
        measurements.append(measurement)
    result["measurements"] = measurements
    result["unresolved_issues"] = issues
    if measurements and exact_count == len(measurements):
        result["binding_status"] = "bound"
    elif measurements:
        result["binding_status"] = "partial"
    else:
        result["binding_status"] = "draft"
    return result


_BROAD_VARIANT_LABELS = frozenset(
    {
        "sample",
        "specimen",
        "subject",
        "group",
        "condition",
        "variant",
        "as-slm",
        "ht-slm",
        "hip-slm",
        "mechanical sample",
    }
)

_BROAD_TEST_LABELS = frozenset(
    {
        "test",
        "measurement",
        "mechanical test",
        "mechanical properties",
        "characterization",
        "mechanical characterization",
        "tensile",
        "hardness",
        "density",
        "microstructure",
        "wear",
        "residual stress",
    }
)


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", "-").split())


def _variant_has_concrete_identity(variant: Mapping[str, Any]) -> bool:
    """Return whether a variant carries a source-level discriminator.

    The model's ``identity_specificity`` flag is advisory.  A broad label such
    as ``as-SLM`` remains broad even when the model writes ``exact``.  Concrete
    attributes (for example a treatment level, cohort, or process setting) or
    a non-generic label provide the evidence needed for a candidate identity.
    """

    generic_attribute_names = {
        "state",
        "processing state",
        "material state",
        "sample",
        "specimen",
        "group",
        "condition",
        "variant",
        "treatment",
    }
    generic_values = {
        "unknown",
        "unspecified",
        "not specified",
        "n/a",
        "as-slm",
        "ht-slm",
        "hip-slm",
        "sample",
        "specimen",
        "group",
        "condition",
        "variant",
    }
    attributes = []
    for field in ("subject_attributes", "intervention_attributes", "state", "attributes"):
        for attribute in variant.get(field) or ():
            if not isinstance(attribute, Mapping):
                continue
            name = _normalized_label(attribute.get("name"))
            value = _normalized_label(attribute.get("value"))
            if not name or not value or value in generic_values:
                continue
            if name in generic_attribute_names and value in generic_values:
                continue
            attributes.append(attribute)
    if attributes:
        return True
    label = _normalized_label(variant.get("variant_label") or variant.get("label"))
    if not label or label in _BROAD_VARIANT_LABELS:
        return False
    # Labels that only add a generic suffix remain broad (``sample 1`` is not
    # a source-supported treatment identity without a row/attribute).
    if re.fullmatch(r"(?:sample|specimen|group|variant|condition)(?:[- ]?\d+)?", label):
        return False
    return True


def _variant_binding_resolution(
    variant: Mapping[str, Any], all_variants: Sequence[Mapping[str, Any]] = ()
) -> str:
    """Classify a sample edge without trusting a model-provided exact flag."""

    if not variant:
        return "unbound"
    specificity = _normalized_label(variant.get("identity_specificity"))
    if specificity in {"partial", "unknown", "category", "broad"}:
        return "partial"
    label = _normalized_label(variant.get("variant_label") or variant.get("label"))
    concrete = _variant_has_concrete_identity(variant)
    if not concrete:
        # A broad row is ambiguous when a sibling supplies a more specific
        # identity; otherwise it is still only a partial observation.
        sibling_specific = any(
            other is not variant
            and _variant_has_concrete_identity(other)
            and (
                label in _normalized_label(other.get("variant_label") or other.get("label"))
                or _normalized_label(other.get("variant_label") or other.get("label"))
                in label
            )
            for other in all_variants
        )
        return "ambiguous" if sibling_specific else "partial"
    # Explicitly missing dimensions override an optimistic model label.
    if variant.get("missing_dimensions"):
        return "partial"
    # A concrete label is exact only when it is not duplicated by another
    # source row with a different identity payload.
    duplicate_identity = any(
        other is not variant
        and _normalized_label(other.get("variant_label") or other.get("label")) == label
        and (
            _variant_has_concrete_identity(other)
            or other.get("missing_dimensions")
        )
        for other in all_variants
    )
    return "ambiguous" if duplicate_identity else "exact"


def _test_has_concrete_protocol(test: Mapping[str, Any]) -> bool:
    """Check for a protocol discriminator, not merely an outcome category."""

    method = _normalized_label(test.get("method"))
    standard = _normalized_label(test.get("standard"))
    generic_protocol_labels = _BROAD_TEST_LABELS | {
        "astm",
        "iso",
        "test method",
        "method",
    }
    generic_standard_labels = {
        "astm",
        "iso",
        "jis",
        "en",
        "gb",
        "gb/t",
        "standard",
        "specification",
        "test standard",
    }
    standard_is_concrete = bool(
        standard
        and standard not in generic_standard_labels
        and not standard.endswith(" standard")
    )
    parameters = [
        item
        for item in test.get("parameters") or ()
        if isinstance(item, Mapping)
        and str(item.get("name") or "").strip()
        and item.get("value") not in (None, "")
        and _normalized_label(item.get("value")) not in _BROAD_TEST_LABELS
    ]
    test_type = _normalized_label(test.get("test_type") or test.get("property_type"))
    return bool(
        (method and method not in generic_protocol_labels)
        or standard_is_concrete
        or parameters
        or (test_type and test_type not in _BROAD_TEST_LABELS)
    )


def _test_binding_resolution(
    test: Mapping[str, Any], all_tests: Sequence[Mapping[str, Any]] = ()
) -> str:
    """Classify concrete test identity; completeness is diagnostic metadata."""

    if not test:
        return "unbound"
    specificity = _normalized_label(test.get("protocol_specificity"))
    category = _normalized_label(test.get("test_type") or test.get("property_type"))
    concrete = _test_has_concrete_protocol(test)
    if not concrete:
        sibling_specific = any(
            other is not test
            and _test_has_concrete_protocol(other)
            and (
                category
                == _normalized_label(other.get("test_type") or other.get("property_type"))
                or category in _normalized_label(other.get("test_type") or other.get("property_type"))
            )
            for other in all_tests
        )
        return "ambiguous" if sibling_specific else "category"
    if specificity in {"partial", "unknown", "category", "broad"}:
        return "partial"
    # ``exact`` requires concrete protocol evidence and an exact specificity
    # declaration.  Whether the protocol applies to a particular outcome is
    # checked at the measurement edge; completeness remains a limitation.
    return "exact"


def _variant_is_exact(variant: Mapping[str, Any]) -> bool:
    """Backward-compatible predicate for callers outside this module."""

    return _variant_binding_resolution(variant) == "exact"


_REPORTED_MEASUREMENT_SCOPE_FIELDS = (
    "reported_sample_label",
    "reported_test_label",
    "candidate_variant_keys",
    "candidate_test_keys",
    "variant_binding_source_refs",
    "test_binding_source_refs",
    "binding_status_candidate",
    "binding_basis",
)


def _preserve_reported_measurement_scope(
    content: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep broad Draft scope facts when formal keys are not yet resolved.

    Drafts intentionally carry more detail than the compact revision model: a
    paper may report ``as-SLM`` or ``mechanical test`` without proving one
    concrete variant/test edge.  The adapter must retain that evidence in the
    existing JSON scope and unresolved-issue fields instead of silently
    dropping unknown Draft keys during ``from_mapping``.
    """

    result = dict(content)
    raw_measurements = result.get("measurements")
    if not isinstance(raw_measurements, (list, tuple)):
        return result

    measurements: list[Any] = []
    issues = [
        dict(item)
        for item in result.get("unresolved_issues") or ()
        if isinstance(item, Mapping)
    ]
    existing_issue_keys = {
        (str(item.get("target_ref") or ""), str(item.get("description") or ""))
        for item in issues
    }

    for raw_measurement in raw_measurements:
        if not isinstance(raw_measurement, Mapping):
            measurements.append(raw_measurement)
            continue
        measurement = dict(raw_measurement)
        scope = (
            dict(measurement.get("measurement_scope"))
            if isinstance(measurement.get("measurement_scope"), Mapping)
            else {}
        )
        reported_scope = (
            dict(scope.get("reported_scope"))
            if isinstance(scope.get("reported_scope"), Mapping)
            else {}
        )
        for field in _REPORTED_MEASUREMENT_SCOPE_FIELDS:
            value = measurement.get(field)
            if value not in (None, "", [], (), {}):
                reported_scope[field] = (
                    list(value) if isinstance(value, tuple) else value
                )
        if reported_scope:
            scope["reported_scope"] = reported_scope
            measurement["measurement_scope"] = scope

        variant_binding_refs = measurement.get(
            "variant_binding_source_refs"
        ) or measurement.get("binding_source_refs")
        test_binding_refs = measurement.get(
            "test_binding_source_refs"
        ) or measurement.get("binding_source_refs")
        has_exact_edge = bool(
            measurement.get("variant_key")
            and measurement.get("test_key")
            and variant_binding_refs
            and test_binding_refs
        )
        if (
            reported_scope
            or not measurement.get("variant_key")
            or not measurement.get("test_key")
        ) and not has_exact_edge:
            measurement_key = str(
                measurement.get("measurement_key")
                or measurement.get("measurement_id")
                or "measurement"
            )
            candidate_refs = [
                f"experimental_variants/{value}"
                for value in measurement.get("candidate_variant_keys") or ()
                if str(value).strip()
            ]
            candidate_refs.extend(
                f"test_conditions/{value}"
                for value in measurement.get("candidate_test_keys") or ()
                if str(value).strip()
            )
            description = (
                "Measurement binding remains unresolved; reported sample/test "
                "scope and candidate references were retained without promoting "
                "a broad label to an exact edge."
            )
            issue_key = (f"measurements/{measurement_key}", description)
            if issue_key not in existing_issue_keys:
                issues.append(
                    {
                        "target_ref": issue_key[0],
                        "description": description,
                        "candidate_refs": candidate_refs,
                        "source_refs": list(
                            [
                                *(variant_binding_refs or ()),
                                *(test_binding_refs or ()),
                            ]
                            or measurement.get("source_refs")
                            or ()
                        ),
                    }
                )
                existing_issue_keys.add(issue_key)
        measurements.append(measurement)

    result["measurements"] = measurements
    result["unresolved_issues"] = issues
    return result


_SOURCE_LABEL_FIELDS = (
    "source_labels",
    "binding_source_labels",
    "variant_binding_source_labels",
    "test_binding_source_labels",
)


def _source_label_items(value: Any) -> tuple[Any, ...]:
    """Normalize Draft label containers without making set order observable."""

    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(value, key=lambda item: str(item)))
    raise ValueError("source labels must be a string, list, tuple, or set")


def _resolve_source_labels(value: Any, labels: Mapping[str, SourceReference]) -> Any:
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _resolve_source_labels(item, labels)
            for item in _source_label_items(value)
        ]
    if not isinstance(value, Mapping):
        return value
    result = {
        key: _resolve_source_labels(item, labels)
        for key, item in value.items()
        if key not in _SOURCE_LABEL_FIELDS
    }
    for source_field, resolved_field in zip(
        _SOURCE_LABEL_FIELDS,
        (
            "source_refs",
            "binding_source_refs",
            "variant_binding_source_refs",
            "test_binding_source_refs",
        ),
        strict=True,
    ):
        source_label_values = _source_label_items(value.get(source_field))
        if source_label_values:
            refs: list[dict[str, Any]] = []
            for label in source_label_values:
                if not isinstance(label, str) or label not in labels:
                    raise ValueError(f"unknown source label: {label}")
                refs.append(labels[label].to_record())
            result[resolved_field] = refs
    return result


__all__ = [
    "DraftReadiness",
    "PaperExperimentDraft",
    "PaperExperimentModelOutput",
    "ReconciledPaperExperimentOutput",
    "assess_draft_readiness",
    "bind_model_output",
    "prepare_model_output",
    "reconcile_model_output",
]

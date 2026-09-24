"""Model-output and authoring boundaries for PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable, Mapping, Sequence

from domain.core.paper_experiment import PaperExperimentRevision, SourceReference


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


def _is_forbidden_field(field: str) -> bool:
    """Reject formal identity fields even when a caller invents a new name."""

    normalized = field.strip().lower()
    return (
        normalized in _FORBIDDEN_DRAFT_FIELDS
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
    )


def _first_forbidden_field(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            field = str(key)
            current_path = f"{path}.{field}" if path else field
            if _is_forbidden_field(field):
                return current_path
            found = _first_forbidden_field(nested, current_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found = _first_forbidden_field(nested, f"{path}[{index}]")
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
            if key in {
                "source_labels",
                "binding_source_labels",
                "variant_binding_source_labels",
                "test_binding_source_labels",
            } and isinstance(nested, (list, tuple)):
                labels.update(str(item).strip() for item in nested if str(item).strip())
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
    source_labels: Mapping[str, Mapping[str, Any]] = None  # type: ignore[assignment]
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


# Boundary labels are advisory, but these categories have distinct service
# semantics.  In particular, an omitted/unknown kind must not be promoted to
# a physical parent merely because it appeared first in the model response.
_EXPLICIT_PARENT_KINDS = frozenset({"parent", "matrix"})
_OVERLAPPING_SCOPE_KINDS = frozenset({"selected_stratum", "follow_up"})
_PHYSICAL_SPLIT_KINDS = frozenset({"physical_split", "split", "independent"})


def _boundary_kind(payload: Mapping[str, Any]) -> str:
    return str(payload.get("scope_kind") or "").strip().lower()


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
                    conflicting = [
                        name
                        for name in ("value", "unit", "result_text", "statistics")
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


def _collapse_boundary_drafts(
    drafts: Sequence[PaperExperimentDraft],
    accepted_keys: Sequence[str],
) -> tuple[tuple[PaperExperimentDraft, ...], tuple[Mapping[str, Any], ...]]:
    if len(drafts) <= 1:
        return tuple(drafts), ()
    parent_index = next(
        (
            index
            for index, draft in enumerate(drafts)
            if str(draft.payload.get("scope_kind") or "").strip().lower()
            not in {"selected_stratum", "follow_up", "physical_split", "split", "independent"}
        ),
        0,
    )
    parent = drafts[parent_index]
    parent_payload = dict(parent.payload)
    parent_kind = str(parent_payload.get("scope_kind") or "").strip().lower()
    parent_is_scope = parent_kind in {"selected_stratum", "follow_up"}
    parent_key = (
        accepted_keys[0]
        if parent_is_scope and accepted_keys and accepted_keys[0] not in {
            _local_series_key(item.payload) for item in drafts
        }
        else _local_series_key(parent_payload) or (accepted_keys[0] if accepted_keys else "parent")
    )
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
        source_labels=tuple(parent_labels),
        unresolved_issues=tuple(parent_issues),
    )
    return (merged_parent, *retained), tuple(audit)

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
    for draft, experiment_id, experiment_version in zip(
        model_output.experiments, experiment_ids, experiment_versions, strict=True
    ):
        draft_payload = dict(draft.payload)
        if draft.source_labels:
            draft_payload["source_labels"] = list(draft.source_labels)
        content = _resolve_source_labels(draft_payload, labels)
        _validate_source_context(content, document_id, source_fingerprint)
        draft_source_refs = content.get("source_refs") or ()
        content["source_refs"] = _dedupe_records(
            item for item in draft_source_refs if isinstance(item, Mapping)
        )
        content["experiment_id"] = experiment_id
        content["experiment_version"] = experiment_version
        content["document_id"] = document_id
        content["source_fingerprint"] = source_fingerprint
        content["unresolved_issues"] = _resolve_source_labels(
            list(draft.unresolved_issues), labels
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
        variant_resolution = _variant_binding_resolution(variant_record, variants)
        test_resolution = _test_binding_resolution(test_record, tests)
        protocol_complete = test_resolution == "exact"
        exact = bool(
            variant_key
            and variant_key in variant_keys
            and test_key
            and test_key in test_by_key
            and variant_resolution == "exact"
            and variant_refs
            and test_refs
            and protocol_complete
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
                    "both result-level edges and a complete applicable protocol are "
                    "required before strict comparison."
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
        or standard
        or parameters
        or (test_type and test_type not in _BROAD_TEST_LABELS)
    )


def _test_binding_resolution(
    test: Mapping[str, Any], all_tests: Sequence[Mapping[str, Any]] = ()
) -> str:
    """Classify test identity and protocol completeness conservatively."""

    if not test:
        return "unbound"
    specificity = _normalized_label(test.get("protocol_specificity"))
    completeness = _normalized_label(test.get("protocol_completeness"))
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
    if completeness != "complete":
        return "partial"
    # ``exact`` is accepted only after concrete protocol evidence and complete
    # applicability are both present.  A model cannot self-certify a category.
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


def _resolve_source_labels(value: Any, labels: Mapping[str, SourceReference]) -> Any:
    if isinstance(value, list):
        return [_resolve_source_labels(item, labels) for item in value]
    if not isinstance(value, Mapping):
        return value
    result = {
        key: _resolve_source_labels(item, labels)
        for key, item in value.items()
        if key
        not in {
            "source_labels",
            "binding_source_labels",
            "variant_binding_source_labels",
            "test_binding_source_labels",
        }
    }
    for source_field, resolved_field in (
        ("source_labels", "source_refs"),
        ("binding_source_labels", "binding_source_refs"),
        ("variant_binding_source_labels", "variant_binding_source_refs"),
        ("test_binding_source_labels", "test_binding_source_refs"),
    ):
        source_label_values = value.get(source_field) or ()
        if source_label_values:
            refs: list[dict[str, Any]] = []
            for label in source_label_values:
                if label not in labels:
                    raise ValueError(f"unknown source label: {label}")
                refs.append(labels[label].to_record())
            result[resolved_field] = refs
    return result


__all__ = [
    "PaperExperimentDraft",
    "PaperExperimentModelOutput",
    "ReconciledPaperExperimentOutput",
    "bind_model_output",
    "reconcile_model_output",
]

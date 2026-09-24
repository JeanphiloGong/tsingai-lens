"""Model-output and authoring boundaries for PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

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


@dataclass(frozen=True)
class PaperExperimentDraft:
    """A model-proposed experiment with only local keys and source labels."""

    payload: Mapping[str, Any]
    source_labels: tuple[str, ...] = ()
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
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
            tuple(dict(item) for item in self.unresolved_issues if isinstance(item, Mapping)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentDraft":
        return cls(
            payload={
                key: value
                for key, value in payload.items()
                if key not in {"source_labels", "unresolved_issues"}
            },
            source_labels=payload.get("source_labels") or (),
            unresolved_issues=payload.get("unresolved_issues") or (),
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
            tuple(dict(item) for item in self.unresolved_issues if isinstance(item, Mapping)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentModelOutput":
        """Parse a trusted application envelope.

        Raw provider JSON should use :meth:`from_model_mapping`, which injects
        the request context and the service-owned source-label catalog.
        """
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
        return cls(
            document_id=str(payload.get("document_id") or "").strip(),
            source_fingerprint=str(payload.get("source_fingerprint") or "").strip(),
            experiments=tuple(
                PaperExperimentDraft.from_mapping(item)
                for item in payload.get("experiments") or ()
                if isinstance(item, Mapping)
            ),
            source_labels={
                str(key): dict(value)
                for key, value in dict(payload.get("source_labels") or {}).items()
                if isinstance(value, Mapping)
            },
            unresolved_issues=tuple(
                dict(item)
                for item in payload.get("unresolved_issues") or ()
                if isinstance(item, Mapping)
            ),
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
            unknown_labels = sorted(
                set(raw_source_labels) - set(source_labels)
            )
            if unknown_labels:
                raise ValueError(
                    "raw model output referenced unknown source labels: "
                    + ", ".join(unknown_labels)
                )
        forbidden = _first_forbidden_field(
            {
                key: value
                for key, value in payload.items()
                if key != "source_labels"
            }
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
                for item in payload.get("experiments") or ()
                if isinstance(item, Mapping)
            ),
            source_labels=source_labels,
            unresolved_issues=tuple(
                dict(item)
                for item in payload.get("unresolved_issues") or ()
                if isinstance(item, Mapping)
            ),
        )


def bind_model_output(
    output: PaperExperimentModelOutput,
    *,
    experiment_ids: Sequence[str],
    experiment_versions: Sequence[int],
    document_id: str,
    source_fingerprint: str,
) -> tuple[PaperExperimentRevision, ...]:
    """Resolve sources and inject formal identity at the application boundary."""

    if output.document_id != document_id:
        raise ValueError("model output document does not match request")
    if output.source_fingerprint != source_fingerprint:
        raise ValueError("model output source fingerprint does not match request")
    if len(output.experiments) != len(experiment_ids) or len(output.experiments) != len(
        experiment_versions
    ):
        raise ValueError("formal identity count must match draft experiment count")

    labels = {
        label: SourceReference.from_mapping(reference)
        for label, reference in output.source_labels.items()
    }
    revisions: list[PaperExperimentRevision] = []
    for draft, experiment_id, experiment_version in zip(
        output.experiments, experiment_ids, experiment_versions, strict=True
    ):
        content = _resolve_source_labels(draft.payload, labels)
        content["experiment_id"] = experiment_id
        content["experiment_version"] = experiment_version
        content["document_id"] = document_id
        content["source_fingerprint"] = source_fingerprint
        content["unresolved_issues"] = _resolve_source_labels(
            list(draft.unresolved_issues), labels
        )
        revisions.append(PaperExperimentRevision.from_mapping(content))
    return tuple(revisions)


def _resolve_source_labels(value: Any, labels: Mapping[str, SourceReference]) -> Any:
    if isinstance(value, list):
        return [_resolve_source_labels(item, labels) for item in value]
    if not isinstance(value, Mapping):
        return value
    result = {
        key: _resolve_source_labels(item, labels)
        for key, item in value.items()
        if key not in {"source_labels", "binding_source_labels"}
    }
    for source_field, resolved_field in (
        ("source_labels", "source_refs"),
        ("binding_source_labels", "binding_source_refs"),
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
    "bind_model_output",
]

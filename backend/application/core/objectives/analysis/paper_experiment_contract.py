"""Model-output and authoring boundaries for PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from domain.core.paper_experiment import PaperExperimentRevision, SourceReference


@dataclass(frozen=True)
class PaperExperimentDraft:
    """A model-proposed experiment with only local keys and source labels."""

    payload: Mapping[str, Any]
    source_labels: tuple[str, ...] = ()
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        forbidden = {
            "id",
            "experiment_id",
            "experiment_version",
            "revision_id",
            "collection_id",
        }
        present = forbidden & set(self.payload)
        if present:
            raise ValueError(
                "draft cannot contain formal identity or collection fields: "
                + ", ".join(sorted(present))
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
    """One bounded model response; it has no formal experiment identity."""

    document_id: str
    source_fingerprint: str
    experiments: tuple[PaperExperimentDraft, ...] = ()
    source_labels: Mapping[str, Mapping[str, Any]] = None  # type: ignore[assignment]
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip() or not self.source_fingerprint.strip():
            raise ValueError("model output requires document_id and source_fingerprint")
        object.__setattr__(self, "source_labels", dict(self.source_labels or {}))
        object.__setattr__(
            self,
            "unresolved_issues",
            tuple(dict(item) for item in self.unresolved_issues if isinstance(item, Mapping)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentModelOutput":
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
        content["unresolved_issues"] = list(draft.unresolved_issues)
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
        if key != "source_labels"
    }
    source_label_values = value.get("source_labels") or ()
    if source_label_values:
        refs: list[dict[str, Any]] = []
        for label in source_label_values:
            if label not in labels:
                raise ValueError(f"unknown source label: {label}")
            refs.append(labels[label].to_record())
        result["source_refs"] = refs
    return result


__all__ = [
    "PaperExperimentDraft",
    "PaperExperimentModelOutput",
    "bind_model_output",
]

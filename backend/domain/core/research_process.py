"""Domain aggregates for reconstructing one paper's research process.

These records describe scientific observations and experiment structure.  They
do not contain model prompts, retry state, window positions, or persistence
details.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Final, Mapping

from domain.core.evidence_backbone import (
    MeasurementResult,
    SampleVariant,
    TestCondition,
)
from domain.core.research_objective import (
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    ResearchObjective,
)

SOURCE_OBSERVATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"unvalidated", "validated", "uncertain", "rejected"}
)
PAPER_EXPERIMENT_STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "bound", "incomplete", "rejected"}
)
_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"text_window", "table", "figure", "block", "section"}
)


@dataclass(frozen=True)
class SourceObservation:
    """A fact copied from one exact Source before it becomes ObjectiveEvidence."""

    observation_id: str
    collection_id: str
    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    observation_role: str
    source_excerpt: str
    confidence: float
    selection_status: str = "extracted"
    selection_reason: str | None = None
    attribution_scope: str = "not_attributable"
    resolution_status: str = "unknown"
    failure_reason: str | None = None
    changed_variables: tuple[ObjectiveEvidenceVariable, ...] = ()
    comparison: ObjectiveEvidenceComparison | None = None
    reported_result: ObjectiveEvidenceResult | None = None
    scientific_context: ObjectiveEvidenceContext = field(
        default_factory=ObjectiveEvidenceContext
    )
    status: str = "unvalidated"
    source_refs: tuple[dict[str, Any], ...] = ()
    derived_from_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "collection_id",
            "objective_id",
            "document_id",
            "source_kind",
            "source_ref",
            "observation_role",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"source observation requires {name}")
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError(f"unsupported source observation kind: {self.source_kind}")
        if self.status not in SOURCE_OBSERVATION_STATUSES:
            raise ValueError(f"unsupported source observation status: {self.status}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("source observation confidence must be between 0 and 1")
        object.__setattr__(self, "changed_variables", tuple(self.changed_variables))
        parents = tuple(self.derived_from_observation_ids)
        if (
            any(not str(item).strip() for item in parents)
            or self.observation_id in parents
            or len(parents) != len(set(parents))
        ):
            raise ValueError(
                "observation derivation requires distinct parent observations"
            )
        object.__setattr__(self, "derived_from_observation_ids", parents)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceObservation":
        source_refs = tuple(
            dict(item)
            for item in payload.get("source_refs") or ()
            if isinstance(item, Mapping)
        )
        first_source_ref = source_refs[0] if source_refs else {}
        observation_id = str(
            payload.get("observation_id") or payload.get("evidence_id") or ""
        ).strip()
        if not observation_id:
            identity = json.dumps(
                [
                    payload.get("objective_id"),
                    payload.get("document_id"),
                    payload.get("source_kind") or first_source_ref.get("source_kind"),
                    payload.get("source_ref") or first_source_ref.get("source_ref"),
                    payload.get("observation_role") or payload.get("evidence_role"),
                    payload.get("reported_result"),
                    payload.get("scientific_context"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            observation_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        selection_status = str(payload.get("selection_status") or "extracted").strip()
        status = str(payload.get("status") or "").strip()
        if not status:
            status = "unvalidated"
        source_excerpt = str(
            payload.get("source_excerpt")
            or first_source_ref.get("source_excerpt")
            or ""
        ).strip()
        return cls(
            observation_id=observation_id,
            collection_id=str(payload.get("collection_id") or "unknown").strip(),
            objective_id=str(payload.get("objective_id") or "").strip(),
            document_id=str(payload.get("document_id") or "").strip(),
            source_kind=str(
                payload.get("source_kind")
                or first_source_ref.get("source_kind")
                or "text_window"
            ).strip(),
            source_ref=str(
                payload.get("source_ref")
                or first_source_ref.get("source_ref")
                or (observation_id if status == "rejected" else "")
            ).strip(),
            observation_role=str(
                payload.get("observation_role")
                or payload.get("evidence_role")
                or "unknown"
            ).strip(),
            source_excerpt=source_excerpt,
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(item)
                for item in payload.get("changed_variables") or ()
                if isinstance(item, Mapping)
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=(
                ObjectiveEvidenceResult.from_mapping(payload["reported_result"])
                if isinstance(payload.get("reported_result"), Mapping)
                else None
            ),
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
            confidence=float(payload.get("confidence") or 0),
            selection_status=selection_status,
            selection_reason=(
                str(payload["selection_reason"]).strip()
                if payload.get("selection_reason")
                else None
            ),
            attribution_scope=str(
                payload.get("attribution_scope") or "not_attributable"
            ).strip(),
            resolution_status=str(
                payload.get("resolution_status") or "unknown"
            ).strip(),
            failure_reason=(
                str(payload["failure_reason"]).strip()
                if payload.get("failure_reason")
                else None
            ),
            status=status,
            source_refs=source_refs,
            derived_from_observation_ids=tuple(
                payload.get("derived_from_observation_ids") or ()
            ),
        )

    @property
    def evidence_id(self) -> str:
        """Stable identifier used by the persisted ObjectiveEvidence format."""
        return self.observation_id

    @property
    def evidence_role(self) -> str:
        """Legacy extraction spelling for the observation's scientific role."""
        return self.observation_role

    def to_record(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "evidence_id": self.observation_id,
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "observation_role": self.observation_role,
            "evidence_role": self.observation_role,
            "source_excerpt": self.source_excerpt,
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "scientific_context": self.scientific_context.to_record(),
            "confidence": self.confidence,
            "selection_status": self.selection_status,
            "selection_reason": self.selection_reason,
            "attribution_scope": self.attribution_scope,
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "status": self.status,
            "source_refs": [dict(item) for item in self.source_refs],
            "derived_from_observation_ids": list(self.derived_from_observation_ids),
        }

    @property
    def has_scientific_content(self) -> bool:
        return bool(
            self.changed_variables
            or self.comparison
            or self.reported_result
            or self.scientific_context.has_content
        )


@dataclass(frozen=True)
class PaperExperiment:
    """One paper-owned experiment assembled from independently sourced facts."""

    experiment_id: str
    collection_id: str
    document_id: str
    study_id: str | None
    source_observations: tuple[SourceObservation, ...] = ()
    sample_variants: tuple[SampleVariant, ...] = ()
    test_conditions: tuple[TestCondition, ...] = ()
    measurements: tuple[MeasurementResult, ...] = ()
    source_observation_ids: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    status: str = "draft"

    def __post_init__(self) -> None:
        for name in ("experiment_id", "collection_id", "document_id"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"paper experiment requires {name}")
        if self.status not in PAPER_EXPERIMENT_STATUSES:
            raise ValueError(f"unsupported paper experiment status: {self.status}")
        records = (
            *self.source_observations,
            *self.sample_variants,
            *self.test_conditions,
            *self.measurements,
        )
        if any(
            record.collection_id != self.collection_id or record.document_id != self.document_id
            for record in records
        ):
            raise ValueError("paper experiment facts must belong to its document")
        ids = [record.variant_id for record in self.sample_variants]
        if len(ids) != len(set(ids)):
            raise ValueError("paper experiment sample variants must be unique")
        measurement_ids = [record.result_id for record in self.measurements]
        if len(measurement_ids) != len(set(measurement_ids)):
            raise ValueError("paper experiment measurements must be unique")
        observation_ids = [record.observation_id for record in self.source_observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("paper experiment source observations must be unique")
        if not set(observation_ids) <= set(self.source_observation_ids):
            raise ValueError(
                "paper experiment observations must be listed in source_observation_ids"
            )
        variant_ids = set(ids)
        condition_ids = {item.test_condition_id for item in self.test_conditions}
        for measurement in self.measurements:
            for reference, available in (
                (measurement.variant_id, variant_ids),
                (measurement.test_condition_id, condition_ids),
            ):
                if reference is not None and reference not in available:
                    raise ValueError(
                        "measurement binding references a fact outside its experiment"
                    )
        if self.status == "bound" and not self.has_bound_measurements:
            raise ValueError("bound experiment requires validated measurement bindings")
        object.__setattr__(
            self, "source_observation_ids", tuple(self.source_observation_ids)
        )
        object.__setattr__(
            self,
            "uncertainties",
            tuple(item for item in self.uncertainties if str(item).strip()),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperiment":
        return cls(
            experiment_id=str(payload.get("experiment_id") or "").strip(),
            collection_id=str(payload.get("collection_id") or "").strip(),
            document_id=str(payload.get("document_id") or "").strip(),
            study_id=(
                str(payload["study_id"]).strip()
                if payload.get("study_id")
                else None
            ),
            source_observations=tuple(
                SourceObservation.from_mapping(item)
                for item in payload.get("source_observations") or ()
                if isinstance(item, Mapping)
            ),
            sample_variants=tuple(
                SampleVariant.from_mapping(item)
                for item in payload.get("sample_variants") or ()
                if isinstance(item, Mapping)
            ),
            test_conditions=tuple(
                TestCondition.from_mapping(item)
                for item in payload.get("test_conditions") or ()
                if isinstance(item, Mapping)
            ),
            measurements=tuple(
                MeasurementResult.from_mapping(item)
                for item in payload.get("measurements") or ()
                if isinstance(item, Mapping)
            ),
            source_observation_ids=tuple(
                str(item).strip()
                for item in payload.get("source_observation_ids") or ()
                if str(item).strip()
            ),
            uncertainties=tuple(
                str(item).strip()
                for item in payload.get("uncertainties") or ()
                if str(item).strip()
            ),
            status=str(payload.get("status") or "draft").strip(),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "study_id": self.study_id,
            "source_observations": [
                item.to_record() for item in self.source_observations
            ],
            "sample_variants": [item.to_record() for item in self.sample_variants],
            "test_conditions": [item.to_record() for item in self.test_conditions],
            "measurements": [item.to_record() for item in self.measurements],
            "source_observation_ids": list(self.source_observation_ids),
            "uncertainties": list(self.uncertainties),
            "status": self.status,
        }

    @property
    def has_measurements(self) -> bool:
        return bool(self.measurements)

    @property
    def has_bound_measurements(self) -> bool:
        observations = {item.observation_id: item for item in self.source_observations}
        return bool(self.measurements) and all(
            item.variant_id is not None
            and item.test_condition_id is not None
            and item.result_id in observations
            and observations[item.result_id].status == "validated"
            for item in self.measurements
        )

    def comparison_status(
        self,
        objective: ResearchObjective,
        baseline_result_id: str,
        target_result_id: str,
    ) -> str:
        """Missing reporting limits a comparison; it never invalidates the observation."""
        measurements = {item.result_id: item for item in self.measurements}
        observations = {item.observation_id: item for item in self.source_observations}
        ids = (baseline_result_id, target_result_id)
        if objective.collection_id != self.collection_id or any(
            observation.objective_id != objective.objective_id
            for observation in self.source_observations
        ):
            raise ValueError("comparison objective must own this experiment")
        missing: list[str] = []
        differences: list[str] = []
        for result_id in ids:
            result = measurements.get(result_id)
            observation = observations.get(result_id)
            if result is None or observation is None:
                missing.append(
                    f"Measurement is not bound in this experiment: {result_id}"
                )
                continue
            if observation.status != "validated":
                missing.append(f"Source support is unresolved: {result_id}")
            if not result.variant_id or not result.test_condition_id:
                missing.append(f"Sample or test binding is unresolved: {result_id}")
            if (
                not observation.scientific_context.material
                or not observation.scientific_context.process
            ):
                missing.append(
                    f"Material or process context is unresolved: {result_id}"
                )
        if all(
            result_id in measurements and result_id in observations for result_id in ids
        ):
            left, right = (measurements[result_id] for result_id in ids)
            if (
                left.property_normalized != right.property_normalized
                or left.unit != right.unit
            ):
                differences.append("Outcome or reported units differ.")
            left_observation, right_observation = (
                observations[result_id] for result_id in ids
            )
            for section in ("material", "test"):
                left_context = {
                    item.name.casefold(): item
                    for item in getattr(left_observation.scientific_context, section)
                }
                right_context = {
                    item.name.casefold(): item
                    for item in getattr(right_observation.scientific_context, section)
                }
                if not left_context or not right_context:
                    missing.append(f"Unreported {section} context.")
                if left_context.keys() != right_context.keys():
                    missing.append(f"Incomplete {section} context for this pair.")
                for key in left_context.keys() & right_context.keys():
                    left_fact, right_fact = left_context[key], right_context[key]
                    if (
                        left_fact.value != right_fact.value
                        or left_fact.unit != right_fact.unit
                    ):
                        differences.append(
                            f"Reported {section} condition differs: {key}."
                        )
            # Only a recorded contrast establishes which factors changed. Two
            # measurements in one paper do not establish a controlled design.
            contrasts = tuple(
                item
                for item in self.source_observations
                if item.derived_from_observation_ids == ids
                and item.comparison is not None
            )
            if not contrasts:
                missing.append("No Source-backed contrast links these measurements.")
            else:
                contrast = contrasts[0]
                if contrast.status != "validated":
                    missing.append("Source support for the contrast is unresolved.")
                if not contrast.comparison.comparable:
                    missing.extend(
                        contrast.comparison.incomparability_reasons
                        or ("The recorded contrast has not established comparability.",)
                    )
                if not contrast.changed_variables:
                    missing.append("The contrast does not establish changed factors.")
                # Axis normalization and scientific attribution belong to the
                # existing Source-grounded reconstruction, not a second matcher.
        return (
            "non_comparable"
            if differences
            else "insufficient_context"
            if missing
            else "comparable"
        )


__all__ = [
    "PAPER_EXPERIMENT_STATUSES",
    "PaperExperiment",
    "SOURCE_OBSERVATION_STATUSES",
    "SourceObservation",
]

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations
import re
from typing import Any

from application.core.objectives.extraction import ObjectiveExtractor
from application.core.objectives import property_matching
from application.core.objectives.schemas import StructuredAxisCanonicalizationPlan
from domain.core import (
    ObjectiveFactSet,
    PaperSkim,
    PaperStudy,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    PaperStudyRelationship,
    ResearchObjective,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]
RelationshipInventory = Mapping[
    str,
    tuple[str, PaperStudy, PaperStudyRelationship],
]
AxisMapping = Mapping[str, Mapping[str, str]]
AxisPair = tuple[str, str, str]

_AXIS_PAIR_LIMIT_PER_TYPE = 96
_AXIS_PAIR_BATCH_SIZE = 16
_MISSING_CONTEXT_VALUES = frozenset(
    {"", "missing", "not reported", "not specified", "unknown", "uncertain"}
)
_VERIFIED_AXIS_SYNONYM_CANONICAL = {
    "base plate preheating": "base plate preheating temperature",
    "baseplate preheating": "base plate preheating temperature",
    "baseplate preheating temperature": "base plate preheating temperature",
    "build platform preheating temperature": "base plate preheating temperature",
    "preheating": "base plate preheating temperature",
    "preheating temperature": "base plate preheating temperature",
    "cracking": "crack formation",
    "cracking behavior": "crack formation",
    "microcrack formation": "crack formation",
    "scanning strategy": "scan strategy",
    "uts": "ultimate tensile strength",
}


class _Compatibility(StrEnum):
    COMPATIBLE = "compatible"
    POSSIBLE = "possible"
    INCOMPATIBLE = "incompatible"


class ObjectiveCandidateService:
    """Promote paper-study relationships into collection research objectives."""

    def discover_candidate_facts(
        self,
        collection_id: str,
        *,
        paper_skims: tuple[PaperSkim, ...],
        extractor: ObjectiveExtractor,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveFactSet:
        source_relationship_inventory = self._relationship_inventory(paper_skims)
        relationship_inventory = self._canonicalize_relationship_inventory_axes(
            collection_id=collection_id,
            extractor=extractor,
            relationship_inventory=source_relationship_inventory,
        )
        terminal_rejections = {
            relationship_id: rejection_reason
            for relationship_id, (_document_id, study, _relationship) in (
                relationship_inventory.items()
            )
            if (rejection_reason := self._objective_seed_rejection_reason(study))
            is not None
        }
        relationship_groups = self._build_relationship_groups(
            paper_skims,
            relationship_inventory=relationship_inventory,
        )
        self._notify_progress(
            progress_callback,
            phase="objective_discovery_started",
            current=0,
            total=len(relationship_groups),
            unit="groups",
            message="Promoting compatible paper-study relationships to objectives.",
        )

        accepted_objectives: list[ResearchObjective] = []
        require_cross_paper_support = len(
            {skim.document_id for skim in paper_skims}
        ) > 1
        for group_number, group in enumerate(relationship_groups, start=1):
            relationship_ids = tuple(
                str(record["relationship"]["relationship_id"])
                for record in group
            )
            objective, rejection_reason = self._objective_from_relationship_group(
                collection_id,
                relationship_ids=relationship_ids,
                relationship_inventory=relationship_inventory,
            )
            if (
                objective is not None
                and require_cross_paper_support
                and len(objective.seed_document_ids) < 2
            ):
                rejection_reason = (
                    "Relationship is not supported by multiple collection papers."
                )
                objective = None
            if objective is not None:
                accepted_objectives.append(objective)
            else:
                for relationship_id in relationship_ids:
                    terminal_rejections[relationship_id] = rejection_reason or (
                        "Study relationship could not form a schema-valid objective."
                    )

            self._notify_progress(
                progress_callback,
                phase="objective_discovery_batch_finished",
                current=group_number,
                total=len(relationship_groups),
                unit="groups",
                message="Promoted one compatible study-relationship group.",
            )

        research_objectives = self._rank_objectives(
            tuple(accepted_objectives),
            relationship_inventory=relationship_inventory,
        )
        research_objectives = tuple(
            ResearchObjective.from_mapping(
                {**objective.to_record(), "rank": rank}
            )
            for rank, objective in enumerate(research_objectives, start=1)
        )
        dispositions = self._study_dispositions(
            research_objectives,
            relationship_inventory=relationship_inventory,
            terminal_rejections=terminal_rejections,
        )
        facts = ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=paper_skims,
            research_objectives=research_objectives,
            study_dispositions=dispositions,
        )
        logger.info(
            "Research objective discovery finished collection_id=%s "
            "paper_skim_count=%s relationship_count=%s group_count=%s "
            "objective_count=%s rejected_relationship_count=%s",
            collection_id,
            len(paper_skims),
            len(relationship_inventory),
            len(relationship_groups),
            len(research_objectives),
            sum(
                disposition.status is PaperStudyDispositionStatus.REJECTED
                for disposition in dispositions
            ),
        )
        return facts

    @staticmethod
    def _relationship_inventory(
        paper_skims: tuple[PaperSkim, ...],
    ) -> dict[str, tuple[str, PaperStudy, PaperStudyRelationship]]:
        inventory: dict[str, tuple[str, PaperStudy, PaperStudyRelationship]] = {}
        for skim in paper_skims:
            for study in skim.studies:
                if study.document_id != skim.document_id:
                    raise ValueError("paper study belongs to another skim document")
                for relationship in study.relationships:
                    if relationship.relationship_id in inventory:
                        raise ValueError(
                            "paper study relationship ids must be collection-unique"
                        )
                    inventory[relationship.relationship_id] = (
                        skim.document_id,
                        study,
                        relationship,
                    )
        return inventory

    def _build_relationship_groups(
        self,
        paper_skims: tuple[PaperSkim, ...],
        *,
        relationship_inventory: RelationshipInventory | None = None,
    ) -> list[list[dict[str, Any]]]:
        inventory = relationship_inventory or self._relationship_inventory(paper_skims)
        skims_by_document_id = {skim.document_id: skim for skim in paper_skims}
        records = sorted(
            (
                self._relationship_record(
                    skims_by_document_id[document_id],
                    study,
                    relationship,
                )
                for document_id, study, relationship in inventory.values()
                if self._objective_seed_rejection_reason(study) is None
            ),
            key=self._record_relationship_id,
        )
        records_by_id = {
            self._record_relationship_id(record): record for record in records
        }
        base_groups: list[list[str]] = []
        for record in records:
            relationship_id = self._record_relationship_id(record)
            compatible_group = next(
                (
                    group
                    for group in base_groups
                    if all(
                        self._record_compatibility(
                            record,
                            records_by_id[other_id],
                        )
                        is _Compatibility.COMPATIBLE
                        for other_id in group
                    )
                ),
                None,
            )
            if compatible_group is None:
                base_groups.append([relationship_id])
            else:
                compatible_group.append(relationship_id)

        base_groups = self._attach_unambiguous_missing_material_groups(
            base_groups,
            relationship_inventory=inventory,
        )

        return [
            [records_by_id[relationship_id] for relationship_id in group]
            for group in sorted(base_groups, key=lambda group: tuple(group))
        ]

    @classmethod
    def _attach_unambiguous_missing_material_groups(
        cls,
        groups: list[list[str]],
        *,
        relationship_inventory: RelationshipInventory,
    ) -> list[list[str]]:
        def has_known_material(group: Iterable[str]) -> bool:
            return any(
                cls._known_material_keys(
                    relationship_inventory[relationship_id][1].material_scope
                )
                for relationship_id in group
            )

        anchored_groups = [
            group for group in groups if has_known_material(group)
        ]
        unanchored_groups = [
            group for group in groups if not has_known_material(group)
        ]
        retained_unanchored: list[list[str]] = []
        for group in unanchored_groups:
            candidates = [
                anchor
                for anchor in anchored_groups
                if all(
                    cls._relationship_compatibility(
                        relationship_inventory[relationship_id][1],
                        relationship_inventory[relationship_id][2],
                        relationship_inventory[anchor_id][1],
                        relationship_inventory[anchor_id][2],
                    )
                    is _Compatibility.POSSIBLE
                    for relationship_id in group
                    for anchor_id in anchor
                )
            ]
            if len(candidates) != 1:
                retained_unanchored.append(group)
                continue
            candidates[0].extend(group)
            candidates[0].sort()
        return [*anchored_groups, *retained_unanchored]

    @staticmethod
    def _relationship_record(
        skim: PaperSkim,
        study: PaperStudy,
        relationship: PaperStudyRelationship,
    ) -> dict[str, Any]:
        study_record = study.to_record()
        study_record.pop("relationships", None)
        return {
            "document_id": skim.document_id,
            "doc_role": skim.doc_role,
            "study": study_record,
            "relationship": relationship.to_record(),
            "evidence_density": skim.evidence_density,
            "paper_confidence": skim.confidence,
            "warnings": list(skim.warnings),
        }

    @staticmethod
    def _record_relationship_id(record: Mapping[str, Any]) -> str:
        relationship = record.get("relationship")
        if not isinstance(relationship, Mapping):
            return ""
        return str(relationship.get("relationship_id") or "")

    @classmethod
    def _record_compatibility(
        cls,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
    ) -> _Compatibility:
        left_study = left.get("study")
        right_study = right.get("study")
        left_relationship = left.get("relationship")
        right_relationship = right.get("relationship")
        if not all(
            isinstance(item, Mapping)
            for item in (
                left_study,
                right_study,
                left_relationship,
                right_relationship,
            )
        ):
            return _Compatibility.INCOMPATIBLE
        return cls._relationship_compatibility(
            PaperStudy.from_mapping(
                {**dict(left_study), "relationships": [dict(left_relationship)]}
            ),
            PaperStudyRelationship.from_mapping(left_relationship),
            PaperStudy.from_mapping(
                {**dict(right_study), "relationships": [dict(right_relationship)]}
            ),
            PaperStudyRelationship.from_mapping(right_relationship),
        )

    @classmethod
    def _relationship_compatibility(
        cls,
        left_study: PaperStudy,
        left: PaperStudyRelationship,
        right_study: PaperStudy,
        right: PaperStudyRelationship,
    ) -> _Compatibility:
        if not cls._axis_collections_are_equivalent(
            left.varied_factors,
            right.varied_factors,
        ) or not cls._axis_values_are_equivalent(left.outcome, right.outcome):
            return _Compatibility.INCOMPATIBLE
        return cls._context_collection_compatibility(
            left_study.material_scope,
            right_study.material_scope,
        )

    @classmethod
    def _context_collection_compatibility(
        cls,
        left: Iterable[str],
        right: Iterable[str],
    ) -> _Compatibility:
        left_keys = cls._known_material_keys(left)
        right_keys = cls._known_material_keys(right)
        if not left_keys and not right_keys:
            return _Compatibility.COMPATIBLE
        if not left_keys or not right_keys:
            return _Compatibility.POSSIBLE
        if left_keys == right_keys:
            return _Compatibility.COMPATIBLE
        if left_keys < right_keys or right_keys < left_keys:
            return _Compatibility.POSSIBLE
        return _Compatibility.INCOMPATIBLE

    @classmethod
    def _known_material_keys(cls, values: Iterable[str]) -> frozenset[str]:
        return frozenset(
            key
            for value in values
            if (key := cls._known_material_scalar(value)) is not None
        )

    @classmethod
    def _known_material_scalar(cls, value: Any) -> str | None:
        key = cls._axis_record_key(value)
        if not key or key in _MISSING_CONTEXT_VALUES:
            return None
        material_grades = cls._material_grade_keys(key)
        if len(material_grades) == 1:
            remainder = re.sub(
                r"(?<![a-z0-9])(?:aisi[\s-]*|ss[\s-]*)?"
                r"\d{3,4}[a-z]{0,2}(?![a-z0-9])",
                " ",
                key,
            )
            remaining_words = frozenset(re.findall(r"[a-z]+", remainder))
            if remaining_words <= {"stainless", "steel"}:
                return f"stainless-steel:{next(iter(material_grades))}"
        return cls._axis_identity(key)

    @classmethod
    def _known_context_scalar(cls, value: Any) -> str | None:
        key = cls._axis_identity(value)
        if not key or key in _MISSING_CONTEXT_VALUES:
            return None
        return key

    @classmethod
    def _axis_identity(cls, value: Any) -> str:
        literal_key = cls._axis_record_key(value)
        if not literal_key:
            return ""
        if any(character in literal_key for character in "()[]"):
            return literal_key
        return cls._verified_axis_synonym_canonical(literal_key)

    @staticmethod
    def _axis_record_key(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _verified_axis_synonym_canonical(value: str) -> str:
        return _VERIFIED_AXIS_SYNONYM_CANONICAL.get(value, value)

    @classmethod
    def _axis_values_are_equivalent(cls, left: Any, right: Any) -> bool:
        left_identity = cls._axis_identity(left)
        return bool(
            left_identity
            and left_identity == cls._axis_identity(right)
        )

    @classmethod
    def _axis_collections_are_equivalent(
        cls,
        left: Iterable[str],
        right: Iterable[str],
    ) -> bool:
        left_values = tuple(left)
        remaining_right = list(right)
        if len(left_values) != len(remaining_right):
            return False
        for left_value in left_values:
            matching_position = next(
                (
                    position
                    for position, right_value in enumerate(remaining_right)
                    if cls._axis_values_are_equivalent(left_value, right_value)
                ),
                None,
            )
            if matching_position is None:
                return False
            remaining_right.pop(matching_position)
        return True

    def _objective_from_relationship_group(
        self,
        collection_id: str,
        *,
        relationship_ids: tuple[str, ...],
        relationship_inventory: RelationshipInventory,
    ) -> tuple[ResearchObjective | None, str | None]:
        if not relationship_ids or not self._relationships_are_compatible(
            relationship_ids,
            relationship_inventory=relationship_inventory,
        ):
            return None, "Study relationships do not form one compatible objective."
        seed_document_ids = self._unique_text_values(
            relationship_inventory[relationship_id][0]
            for relationship_id in relationship_ids
        )
        studies = tuple(
            relationship_inventory[relationship_id][1]
            for relationship_id in relationship_ids
        )
        relationships = tuple(
            relationship_inventory[relationship_id][2]
            for relationship_id in relationship_ids
        )
        variables = relationships[0].varied_factors
        source_outcome = relationships[0].outcome
        outcome_expansions = property_matching.broad_outcome_expansions(
            source_outcome
        )
        normalized_outcome = property_matching.normalize_property_label(
            source_outcome
        )
        if (
            len(outcome_expansions) > 1
            and normalized_outcome is not None
            and normalized_outcome.rsplit(" ", 1)[-1] in {"property", "properties"}
        ):
            return (
                None,
                f"Outcome '{source_outcome}' requires a specific measurable outcome "
                "before it can seed a research objective.",
            )
        outcome = (
            outcome_expansions[0]
            if len(outcome_expansions) == 1
            else source_outcome
        )
        confidence = self._objective_confidence(studies, relationships)
        material_scope = self._shared_study_values(studies, "material_scope")
        material_scope_was_missing = any(
            not self._known_material_keys(study.material_scope) for study in studies
        )
        reason_parts = [
            "Supported by one backend-compatible relationship group.",
            (
                "Confidence is the minimum available non-zero source confidence."
                if confidence > 0
                else "No source supplied a non-zero confidence."
            ),
        ]
        if not material_scope:
            reason_parts.append(
                "No unambiguous shared material scope was available."
            )
        elif material_scope_was_missing:
            reason_parts.append(
                "Material scope was retained from the unambiguous non-conflicting "
                "source anchor."
            )
        objective_payload = {
            "collection_id": collection_id,
            "question": self._objective_question(variables, outcome),
            "variables": list(variables),
            "outcomes": [outcome],
            "material_scope": material_scope,
            "mechanisms": [],
            "constraints": self._shared_study_constraints(
                studies,
                excluded_axes=(*variables, outcome),
            ),
            "requested_comparator": self._shared_study_scalar(
                studies,
                "comparator",
            ),
            "seed_document_ids": seed_document_ids,
            "source_relationship_ids": list(relationship_ids),
            "confidence": confidence,
            "reason": " ".join(reason_parts),
        }
        try:
            return ResearchObjective.from_mapping(objective_payload), None
        except (TypeError, ValueError) as exc:
            return None, f"Study relationship group cannot form a valid objective: {exc}"

    @staticmethod
    def _objective_question(
        varied_factors: tuple[str, ...],
        outcome: str,
    ) -> str:
        auxiliary = "does" if len(varied_factors) == 1 else "do"
        return f"How {auxiliary} {' and '.join(varied_factors)} affect {outcome}?"

    def _relationships_are_compatible(
        self,
        relationship_ids: Iterable[str],
        *,
        relationship_inventory: RelationshipInventory,
    ) -> bool:
        ids = tuple(relationship_ids)
        for position, left_id in enumerate(ids):
            _left_document_id, left_study, left_relationship = (
                relationship_inventory[left_id]
            )
            for right_id in ids[position + 1 :]:
                _right_document_id, right_study, right_relationship = (
                    relationship_inventory[right_id]
                )
                if (
                    self._relationship_compatibility(
                        left_study,
                        left_relationship,
                        right_study,
                        right_relationship,
                    )
                    is _Compatibility.INCOMPATIBLE
                ):
                    return False
        return True

    @staticmethod
    def _objective_seed_rejection_reason(study: PaperStudy) -> str | None:
        if study.claim_scope not in {"synthesis", "background"}:
            return None
        return (
            f"Study relationship has claim_scope={study.claim_scope} and cannot "
            "directly seed a research objective."
        )

    def _shared_study_values(
        self,
        studies: tuple[PaperStudy, ...],
        field_name: str,
    ) -> list[str]:
        values_by_study = [
            tuple(getattr(study, field_name))
            for study in studies
        ]
        material_scope_was_missing = False
        if field_name == "material_scope":
            values_by_study = [
                tuple(
                    value
                    for value in values
                    if self._known_material_scalar(value) is not None
                )
                for values in values_by_study
            ]
            material_scope_was_missing = any(
                not values for values in values_by_study
            )
            values_by_study = [values for values in values_by_study if values]
        if not values_by_study or (
            field_name != "material_scope"
            and any(not values for values in values_by_study)
        ):
            return []

        def values_match(left: str, right: str) -> bool:
            if field_name != "material_scope":
                return self._axis_values_are_equivalent(left, right)
            left_key = self._known_material_scalar(left)
            return left_key is not None and left_key == self._known_material_scalar(
                right
            )

        first, *remaining = values_by_study
        shared_values = self._unique_axis_values(
            value
            for value in first
            if all(
                any(
                    values_match(value, candidate)
                    for candidate in values
                )
                for values in remaining
            )
        )
        if field_name == "material_scope" and material_scope_was_missing:
            shared_materials = {
                self._known_material_scalar(value) for value in shared_values
            }
            if len(shared_materials) != 1:
                return []
        return shared_values

    @staticmethod
    def _objective_confidence(
        studies: tuple[PaperStudy, ...],
        relationships: tuple[PaperStudyRelationship, ...],
    ) -> float:
        available = tuple(
            confidence
            for confidence in (
                *(study.confidence for study in studies),
                *(relationship.confidence for relationship in relationships),
            )
            if confidence > 0
        )
        return min(available, default=0.0)

    def _shared_study_constraints(
        self,
        studies: tuple[PaperStudy, ...],
        *,
        excluded_axes: Iterable[str] = (),
    ) -> list[str]:
        constraints: list[str] = []
        for field_name in (
            "process_context",
            "sample_context",
            "test_context",
            "fixed_conditions",
        ):
            constraints.extend(self._shared_study_values(studies, field_name))
        for field_name in ("design_type", "claim_scope"):
            if value := self._shared_study_scalar(studies, field_name):
                constraints.append(value)
        excluded = tuple(excluded_axes)
        return self._unique_axis_values(
            value
            for value in constraints
            if not any(
                self._axis_values_are_equivalent(value, axis)
                for axis in excluded
            )
        )

    @classmethod
    def _shared_study_scalar(
        cls,
        studies: tuple[PaperStudy, ...],
        field_name: str,
    ) -> str | None:
        values = tuple(getattr(study, field_name) for study in studies)
        keys = tuple(cls._known_context_scalar(value) for value in values)
        if not keys or any(key is None for key in keys) or len(set(keys)) != 1:
            return None
        return str(values[0])

    def _canonicalize_relationship_inventory_axes(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        relationship_inventory: RelationshipInventory,
    ) -> dict[str, tuple[str, PaperStudy, PaperStudyRelationship]]:
        axis_candidates = self._build_relationship_axis_candidates(
            relationship_inventory
        )
        axis_pairs = self._build_axis_candidate_pairs(axis_candidates)
        if not axis_pairs:
            return dict(relationship_inventory)
        pair_records = [
            {
                "pair_id": pair_id,
                "axis_type": axis_type,
                "left": left,
                "right": right,
            }
            for pair_id, (axis_type, left, right) in axis_pairs.items()
        ]
        decisions: list[dict[str, Any]] = []
        try:
            for start in range(0, len(pair_records), _AXIS_PAIR_BATCH_SIZE):
                plan = extractor.canonicalize_research_objective_axes(
                    {
                        "collection_id": collection_id,
                        "axis_pairs": pair_records[
                            start : start + _AXIS_PAIR_BATCH_SIZE
                        ],
                    }
                )
                decisions.extend(
                    decision.model_dump() for decision in plan.decisions
                )
            canonicalization_plan = StructuredAxisCanonicalizationPlan(
                decisions=decisions
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Research relationship axis canonicalization failed; using source axes "
                "collection_id=%s",
                collection_id,
                exc_info=True,
            )
            return dict(relationship_inventory)

        axis_mapping = self._axis_mapping_from_plan(
            canonicalization_plan,
            axis_candidates=axis_candidates,
            axis_pairs=axis_pairs,
            relationship_inventory=relationship_inventory,
        )
        if axis_mapping is None:
            logger.warning(
                "Research relationship axis canonicalization rejected; using source "
                "axes "
                "collection_id=%s",
                collection_id,
            )
            return dict(relationship_inventory)
        canonicalized_inventory = {
            relationship_id: (
                document_id,
                replace(
                    study,
                    material_scope=tuple(
                        self._canonicalize_axis_values(
                            study.material_scope,
                            axis_type="material",
                            axis_mapping=axis_mapping,
                        )
                    ),
                ),
                replace(
                    relationship,
                    varied_factors=tuple(
                        self._canonicalize_axis_values(
                            relationship.varied_factors,
                            axis_type="variable",
                            axis_mapping=axis_mapping,
                        )
                    ),
                    outcome=self._canonicalize_axis_values(
                        (relationship.outcome,),
                        axis_type="outcome",
                        axis_mapping=axis_mapping,
                    )[0],
                ),
            )
            for relationship_id, (
                document_id,
                study,
                relationship,
            ) in relationship_inventory.items()
        }
        return canonicalized_inventory

    def _build_relationship_axis_candidates(
        self,
        relationship_inventory: RelationshipInventory,
    ) -> dict[str, list[str]]:
        return {
            "material": self._unique_axis_values(
                material
                for _document_id, study, _relationship in (
                    relationship_inventory.values()
                )
                for material in study.material_scope
            ),
            "variable": self._unique_axis_values(
                factor
                for _document_id, _study, relationship in (
                    relationship_inventory.values()
                )
                for factor in relationship.varied_factors
            ),
            "outcome": self._unique_axis_values(
                relationship.outcome
                for _document_id, _study, relationship in (
                    relationship_inventory.values()
                )
            ),
        }

    @classmethod
    def _build_axis_candidate_pairs(
        cls,
        axis_candidates: dict[str, list[str]],
    ) -> dict[str, AxisPair]:
        pairs: dict[str, AxisPair] = {}
        for axis_type, values in axis_candidates.items():
            candidates = [
                (left, right)
                for left, right in combinations(values, 2)
                if cls._axis_pair_might_be_equivalent(axis_type, left, right)
            ]
            candidates.sort(
                key=lambda pair: (
                    -int(cls._axis_values_are_equivalent(*pair)),
                    -SequenceMatcher(
                        a=cls._axis_record_key(pair[0]),
                        b=cls._axis_record_key(pair[1]),
                    ).ratio(),
                    cls._axis_record_key(pair[0]),
                    cls._axis_record_key(pair[1]),
                )
            )
            for left, right in candidates[:_AXIS_PAIR_LIMIT_PER_TYPE]:
                pair_id = f"axis_pair_{len(pairs) + 1:04d}"
                pairs[pair_id] = (axis_type, left, right)
        return pairs

    @classmethod
    def _axis_pair_might_be_equivalent(
        cls,
        axis_type: str,
        left: str,
        right: str,
    ) -> bool:
        if cls._axis_values_are_equivalent(left, right):
            return True
        if axis_type == "material":
            return bool(
                cls._material_grade_keys(left) & cls._material_grade_keys(right)
            )
        if (
            property_matching.source_text_mentions_axis(left, right)
            or property_matching.source_text_mentions_axis(right, left)
        ):
            return True
        left_key = cls._axis_record_key(left)
        right_key = cls._axis_record_key(right)
        return SequenceMatcher(a=left_key, b=right_key).ratio() >= 0.78

    @staticmethod
    def _material_grade_keys(value: str) -> frozenset[str]:
        return frozenset(
            match.group(1)
            for match in re.finditer(
                r"(?<![a-z0-9])(?:aisi[\s-]*|ss[\s-]*)?"
                r"(\d{3,4}[a-z]{0,2})(?![a-z0-9])",
                value.casefold(),
            )
        )

    @classmethod
    def _axis_mapping_from_plan(
        cls,
        canonicalization_plan: StructuredAxisCanonicalizationPlan,
        *,
        axis_candidates: dict[str, list[str]],
        axis_pairs: Mapping[str, AxisPair],
        relationship_inventory: RelationshipInventory,
    ) -> dict[str, dict[str, str]] | None:
        decision_ids = tuple(
            decision.pair_id for decision in canonicalization_plan.decisions
        )
        selected_ids = tuple(
            decision.pair_id
            for decision in canonicalization_plan.decisions
            if decision.equivalent
        )
        if (
            decision_ids != tuple(axis_pairs)
            or len(decision_ids) != len(set(decision_ids))
        ):
            return None
        selected_edges = {
            (
                axis_type,
                frozenset(
                    (cls._axis_record_key(left), cls._axis_record_key(right))
                ),
            )
            for pair_id in selected_ids
            for axis_type, left, right in (axis_pairs[pair_id],)
        }
        label_counts = cls._axis_label_counts(relationship_inventory)
        axis_mapping: dict[str, dict[str, str]] = {
            axis_type: {
                cls._axis_record_key(value): value
                for value in axis_candidates[axis_type]
                if cls._axis_record_key(value)
            }
            for axis_type in axis_candidates
        }
        for axis_type, values in axis_candidates.items():
            groups: list[list[str]] = []
            for value in sorted(
                values,
                key=lambda item: (
                    -label_counts.get(axis_type, {}).get(
                        cls._axis_record_key(item), 0
                    ),
                    cls._axis_record_key(item),
                ),
            ):
                compatible_group = next(
                    (
                        group
                        for group in groups
                        if all(
                            (
                                axis_type,
                                frozenset(
                                    (
                                        cls._axis_record_key(value),
                                        cls._axis_record_key(other),
                                    )
                                ),
                            )
                            in selected_edges
                            for other in group
                        )
                    ),
                    None,
                )
                if compatible_group is None:
                    groups.append([value])
                else:
                    compatible_group.append(value)
            for group in groups:
                canonical = max(
                    group,
                    key=lambda value: (
                        label_counts.get(axis_type, {}).get(
                            cls._axis_record_key(value), 0
                        ),
                        len(value.split()) > 1,
                        -len(value),
                        cls._axis_record_key(value),
                    ),
                )
                for value in group:
                    axis_mapping[axis_type][cls._axis_record_key(value)] = canonical
        return axis_mapping

    @classmethod
    def _axis_label_counts(
        cls,
        relationship_inventory: RelationshipInventory,
    ) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {
            "material": {},
            "variable": {},
            "outcome": {},
        }

        def count(axis_type: str, value: str) -> None:
            key = cls._axis_record_key(value)
            counts[axis_type][key] = counts[axis_type].get(key, 0) + 1

        for _document_id, study, relationship in relationship_inventory.values():
            for material in study.material_scope:
                count("material", material)
            for factor in relationship.varied_factors:
                count("variable", factor)
            count("outcome", relationship.outcome)
        return counts

    def _canonicalize_axis_values(
        self,
        values: tuple[str, ...],
        *,
        axis_type: str,
        axis_mapping: AxisMapping,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        mapping = axis_mapping.get(axis_type, {})
        for value in values:
            canonical = mapping.get(self._axis_record_key(value), value)
            self._append_unique_axis(merged, seen, canonical)
        return merged

    @staticmethod
    def _rank_objectives(
        objectives: tuple[ResearchObjective, ...],
        *,
        relationship_inventory: RelationshipInventory,
    ) -> tuple[ResearchObjective, ...]:
        def rank(objective: ResearchObjective) -> tuple[float, float, float, str]:
            supporting_relationships = [
                relationship_inventory[relationship_id][2]
                for relationship_id in objective.source_relationship_ids
            ]
            mean_confidence = (
                sum(item.confidence for item in supporting_relationships)
                / len(supporting_relationships)
                if supporting_relationships
                else 0.0
            )
            return (
                -float(len(objective.seed_document_ids)),
                -float(len(objective.source_relationship_ids)),
                -mean_confidence,
                objective.objective_id,
            )

        return tuple(sorted(objectives, key=rank))

    @staticmethod
    def _study_dispositions(
        objectives: tuple[ResearchObjective, ...],
        *,
        relationship_inventory: RelationshipInventory,
        terminal_rejections: Mapping[str, str],
    ) -> tuple[PaperStudyDisposition, ...]:
        objective_by_relationship_id = {
            relationship_id: objective
            for objective in objectives
            for relationship_id in objective.source_relationship_ids
        }
        dispositions: list[PaperStudyDisposition] = []
        for relationship_id, (document_id, study, _relationship) in sorted(
            relationship_inventory.items()
        ):
            objective = objective_by_relationship_id.get(relationship_id)
            if objective is None:
                dispositions.append(
                    PaperStudyDisposition(
                        document_id=document_id,
                        study_id=study.study_id,
                        relationship_id=relationship_id,
                        status=PaperStudyDispositionStatus.REJECTED,
                        reason=terminal_rejections.get(relationship_id)
                        or "Study relationship could not form a valid objective.",
                    )
                )
                continue
            dispositions.append(
                PaperStudyDisposition(
                    document_id=document_id,
                    study_id=study.study_id,
                    relationship_id=relationship_id,
                    status=PaperStudyDispositionStatus.PROMOTED,
                    objective_id=objective.objective_id,
                )
            )
        return tuple(dispositions)

    @staticmethod
    def _unique_text_values(values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _unique_axis_values(self, values: Iterable[Any]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            self._append_unique_axis(merged, seen, value)
        return merged

    @classmethod
    def _append_unique_axis(
        cls,
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        key = cls._axis_record_key(text)
        if not text or not key or key in seen:
            return
        seen.add(key)
        target.append(text)

    @staticmethod
    def _notify_progress(
        progress_callback: ProgressCallback | None,
        *,
        phase: str,
        current: int,
        total: int,
        unit: str,
        message: str,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "phase": phase,
                "current": current,
                "total": total,
                "unit": unit,
                "message": message,
            }
        )

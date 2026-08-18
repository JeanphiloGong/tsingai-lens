from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
    StructuredAxisCanonicalizationPlan,
)
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
AxisTopicRelation = tuple[str, str, str]

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
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveFactSet:
        source_relationship_inventory = self._relationship_inventory(paper_skims)
        relationship_inventory, topic_relations = (
            self._canonicalize_relationship_inventory_axes(
                collection_id=collection_id,
                axis_equivalence_classifier=axis_equivalence_classifier,
                relationship_inventory=source_relationship_inventory,
            )
        )
        terminal_rejections = {
            relationship_id: rejection_reason
            for relationship_id, (_document_id, study, relationship) in (
                relationship_inventory.items()
            )
            if (
                rejection_reason := self._objective_seed_rejection_reason(
                    study,
                    relationship,
                )
            )
            is not None
        }
        relationship_groups = self._build_relationship_groups(
            paper_skims,
            relationship_inventory=relationship_inventory,
            topic_relations=topic_relations,
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
                topic_relations=topic_relations,
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
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
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
                if self._objective_seed_rejection_reason(study, relationship) is None
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
                            topic_relations=topic_relations,
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
            topic_relations=topic_relations,
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
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
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
                        topic_relations=topic_relations,
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
        *,
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
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
            topic_relations=topic_relations,
        )

    @classmethod
    def _relationship_compatibility(
        cls,
        left_study: PaperStudy,
        left: PaperStudyRelationship,
        right_study: PaperStudy,
        right: PaperStudyRelationship,
        *,
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
    ) -> _Compatibility:
        if not cls._axis_collections_support_same_topic(
            left.varied_factors,
            right.varied_factors,
            topic_relations=topic_relations,
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
        if re.search(
            r"(?<![a-z0-9])ti[\s-]*(?:6[\s-]*al[\s-]*4[\s-]*v|64)" r"(?![a-z0-9])",
            key,
        ):
            return "titanium-alloy:ti-6al-4v"
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
        if left_identity and left_identity == cls._axis_identity(right):
            return True
        left_property = property_matching.normalize_property_label(left)
        return bool(
            left_property
            and left_property == property_matching.normalize_property_label(right)
        )

    @classmethod
    def _axis_values_share_topic(
        cls,
        axis_type: str,
        left: Any,
        right: Any,
        *,
        topic_relations: frozenset[AxisTopicRelation],
    ) -> bool:
        if cls._axis_values_are_equivalent(left, right):
            return True
        left_key, right_key = sorted(
            (cls._axis_record_key(left), cls._axis_record_key(right))
        )
        return (axis_type, left_key, right_key) in topic_relations

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

    @classmethod
    def _axis_collections_support_same_topic(
        cls,
        left: Iterable[str],
        right: Iterable[str],
        *,
        topic_relations: frozenset[AxisTopicRelation],
    ) -> bool:
        return any(
            cls._axis_values_share_topic(
                "variable",
                left_value,
                right_value,
                topic_relations=topic_relations,
            )
            for left_value in left
            for right_value in right
        )

    def _objective_from_relationship_group(
        self,
        collection_id: str,
        *,
        relationship_ids: tuple[str, ...],
        relationship_inventory: RelationshipInventory,
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
    ) -> tuple[ResearchObjective | None, str | None]:
        if not relationship_ids or not self._relationships_are_compatible(
            relationship_ids,
            relationship_inventory=relationship_inventory,
            topic_relations=topic_relations,
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
        variables = tuple(
            self._unique_axis_values(
                factor
                for relationship in relationships
                for factor in relationship.varied_factors
            )
        )
        outcomes: list[str] = []
        outcome_keys: set[str] = set()
        for relationship in relationships:
            source_outcome = relationship.outcome
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
                    f"Outcome '{source_outcome}' requires a specific measurable "
                    "outcome before it can seed a research objective.",
                )
            self._append_unique_axis(
                outcomes,
                outcome_keys,
                (
                    outcome_expansions[0]
                    if len(outcome_expansions) == 1
                    else source_outcome
                ),
            )
        confidence = self._objective_confidence(studies, relationships)
        material_scope = self._shared_study_values(studies, "material_scope")
        material_scope_was_missing = any(
            not self._known_material_keys(study.material_scope) for study in studies
        )
        reason_parts = [
            "Supported by one backend-validated research-topic group; direct "
            "comparability remains a later evidence decision.",
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
            "question": self._objective_question(variables, tuple(outcomes)),
            "variables": list(variables),
            "outcomes": outcomes,
            "material_scope": material_scope,
            "mechanisms": [],
            "constraints": self._shared_study_constraints(
                studies,
                excluded_axes=(*variables, *outcomes),
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
        outcomes: tuple[str, ...],
    ) -> str:
        def coordinated(values: tuple[str, ...]) -> str:
            if len(values) == 1:
                return values[0]
            if len(values) == 2:
                return " and ".join(values)
            return f"{', '.join(values[:-1])}, and {values[-1]}"

        auxiliary = "does" if len(varied_factors) == 1 else "do"
        return (
            f"How {auxiliary} {coordinated(varied_factors)} affect "
            f"{coordinated(outcomes)}?"
        )

    def _relationships_are_compatible(
        self,
        relationship_ids: Iterable[str],
        *,
        relationship_inventory: RelationshipInventory,
        topic_relations: frozenset[AxisTopicRelation] = frozenset(),
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
                        topic_relations=topic_relations,
                    )
                    is _Compatibility.INCOMPATIBLE
                ):
                    return False
        return True

    @staticmethod
    def _objective_seed_rejection_reason(
        study: PaperStudy,
        relationship: PaperStudyRelationship,
    ) -> str | None:
        if study.claim_scope in {"synthesis", "background"}:
            return (
                f"Study relationship has claim_scope={study.claim_scope} and cannot "
                "directly seed a research objective."
            )
        if property_matching.outcome_label_requires_resolution(relationship.outcome):
            return (
                f"Outcome '{relationship.outcome}' requires a specific measurable "
                "outcome before it can seed a research objective."
            )
        return None

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
        if field_name == "material_scope":
            all_values = [value for values in values_by_study for value in values]
            shared_values = [
                max(
                    (
                        candidate
                        for candidate in all_values
                        if self._known_material_scalar(candidate)
                        == self._known_material_scalar(shared_value)
                    ),
                    key=lambda candidate: (
                        sum(
                            self._axis_record_key(value)
                            == self._axis_record_key(candidate)
                            for value in all_values
                        ),
                        -all_values.index(candidate),
                    ),
                )
                for shared_value in shared_values
            ]
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
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier,
        relationship_inventory: RelationshipInventory,
    ) -> tuple[
        dict[str, tuple[str, PaperStudy, PaperStudyRelationship]],
        frozenset[AxisTopicRelation],
    ]:
        eligible_relationship_inventory = {
            relationship_id: record
            for relationship_id, record in relationship_inventory.items()
            if self._objective_seed_rejection_reason(record[1], record[2]) is None
        }
        axis_candidates = self._build_relationship_axis_candidates(
            eligible_relationship_inventory
        )
        axis_pairs = self._build_axis_candidate_pairs(
            axis_candidates,
            relationship_inventory=eligible_relationship_inventory,
        )
        if not axis_pairs:
            return dict(relationship_inventory), frozenset()
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
                plan = axis_equivalence_classifier.classify(
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
            return dict(relationship_inventory), frozenset()

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
            return dict(relationship_inventory), frozenset()
        topic_relations = self._topic_relations_from_plan(
            canonicalization_plan,
            axis_pairs=axis_pairs,
            axis_mapping=axis_mapping,
        )
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
        return canonicalized_inventory, topic_relations

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
        *,
        relationship_inventory: RelationshipInventory | None = None,
    ) -> dict[str, AxisPair]:
        pairs: dict[str, AxisPair] = {}
        supported_cross_paper_pairs = (
            cls._supported_cross_paper_axis_pairs(relationship_inventory)
            if relationship_inventory is not None
            else frozenset()
        )
        for axis_type, values in axis_candidates.items():
            candidates = [
                (left, right)
                for left, right in combinations(values, 2)
                if cls._axis_pair_might_be_equivalent(axis_type, left, right)
                or cls._axis_relation_key(axis_type, left, right)
                in supported_cross_paper_pairs
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
            for left, right in candidates:
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
            left_material = cls._known_material_scalar(left)
            if (
                left_material is not None
                and left_material == cls._known_material_scalar(right)
            ):
                return False
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

    @classmethod
    def _supported_cross_paper_axis_pairs(
        cls,
        relationship_inventory: RelationshipInventory,
    ) -> frozenset[AxisPair]:
        supported: set[AxisPair] = set()
        relationships = tuple(relationship_inventory.values())
        for position, (
            left_document_id,
            left_study,
            left_relationship,
        ) in enumerate(relationships):
            for (
                right_document_id,
                right_study,
                right_relationship,
            ) in relationships[position + 1 :]:
                if left_document_id == right_document_id or (
                    cls._context_collection_compatibility(
                        left_study.material_scope,
                        right_study.material_scope,
                    )
                    is _Compatibility.INCOMPATIBLE
                ):
                    continue
                if cls._axis_values_are_equivalent(
                    left_relationship.outcome,
                    right_relationship.outcome,
                ):
                    supported.update(
                        cls._axis_relation_key("variable", left_factor, right_factor)
                        for left_factor in left_relationship.varied_factors
                        for right_factor in right_relationship.varied_factors
                        if not cls._axis_values_are_equivalent(
                            left_factor,
                            right_factor,
                        )
                    )
                if any(
                    cls._axis_values_are_equivalent(left_factor, right_factor)
                    for left_factor in left_relationship.varied_factors
                    for right_factor in right_relationship.varied_factors
                ) and not cls._axis_values_are_equivalent(
                    left_relationship.outcome,
                    right_relationship.outcome,
                ):
                    supported.add(
                        cls._axis_relation_key(
                            "outcome",
                            left_relationship.outcome,
                            right_relationship.outcome,
                        )
                    )
        return frozenset(supported)

    @classmethod
    def _axis_relation_key(
        cls,
        axis_type: str,
        left: Any,
        right: Any,
    ) -> AxisPair:
        left_key, right_key = sorted(
            (cls._axis_record_key(left), cls._axis_record_key(right))
        )
        return axis_type, left_key, right_key

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
        if decision_ids != tuple(axis_pairs) or len(decision_ids) != len(
            set(decision_ids)
        ):
            return None
        selected_edges = {
            (
                axis_type,
                frozenset(
                    (cls._axis_record_key(left), cls._axis_record_key(right))
                ),
            )
            for decision in canonicalization_plan.decisions
            for axis_type, left, right in (axis_pairs[decision.pair_id],)
            if decision.equivalent or cls._axis_values_are_equivalent(left, right)
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
    def _topic_relations_from_plan(
        cls,
        canonicalization_plan: StructuredAxisCanonicalizationPlan,
        *,
        axis_pairs: Mapping[str, AxisPair],
        axis_mapping: AxisMapping,
    ) -> frozenset[AxisTopicRelation]:
        relations: set[AxisTopicRelation] = set()
        for decision in canonicalization_plan.decisions:
            if not decision.same_research_topic:
                continue
            axis_type, left, right = axis_pairs[decision.pair_id]
            if axis_type != "variable":
                continue
            mapping = axis_mapping.get(axis_type, {})
            left_key, right_key = sorted(
                (
                    cls._axis_record_key(mapping.get(cls._axis_record_key(left), left)),
                    cls._axis_record_key(
                        mapping.get(cls._axis_record_key(right), right)
                    ),
                )
            )
            if left_key and right_key and left_key != right_key:
                relations.add((axis_type, left_key, right_key))
        return frozenset(relations)

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

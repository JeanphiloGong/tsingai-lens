from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from application.core.objectives import property_matching
from application.core.objectives.extraction import ObjectiveExtractor
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredObjectiveMergePlan,
    StructuredResearchObjective,
)
from domain.core import (
    PaperSkim,
    ResearchObjective,
    is_question_shaped_objective,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_DISCOVERY_SCOPE_VALUE_LIMIT = 2
_DISCOVERY_AXIS_VALUE_LIMIT = 6
_DISCOVERY_OBJECTIVE_LIMIT = 3
_DISCOVERY_WARNING_LIMIT = 2
_DISCOVERY_TEXT_VALUE_CHARS = 80
_DISCOVERY_OBJECTIVE_TEXT_CHARS = 180


def _non_empty_text_values(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(text for value in values if (text := str(value).strip()))


def _values_support_all_axes(
    values: tuple[str, ...],
    axes: Iterable[str],
) -> bool:
    return all(
        any(
            property_matching.axis_values_match(axis, value)
            or property_matching.source_text_mentions_axis(value, axis)
            or property_matching.source_text_mentions_axis(axis, value)
            for value in values
        )
        for axis in axes
    )


class ObjectiveCandidateService:
    """Discover and validate collection-level Objectives from PaperSkims."""

    # define a method that converts all per-paper PaperSkim records into a small, validated set of collection-level research objectives
    def discover_candidates(
        self,
        collection_id: str,
        *,
        paper_skims: tuple[PaperSkim, ...],
        documents: tuple[Any, ...],
        extractor: ObjectiveExtractor,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[ResearchObjective, ...]:
        discovery_skims = [
            self._build_objective_discovery_skim(skim) for skim in paper_skims
        ]
        objective_payload = {
            "collection_id": collection_id,
            "paper_skims": discovery_skims,
        }
        self._notify_progress(
            progress_callback,
            phase="objective_discovery_started",
            current=0,
            total=1,
            unit="steps",
            message="Merging paper skims into collection research objectives.",
        )
        parsed_objectives = extractor.discover_research_objectives(objective_payload)
        discovered_objective_count = len(parsed_objectives.objectives)
        discovery_skims_by_document_id = {
            str(skim["document_id"]): skim for skim in discovery_skims
        }
        accepted_objectives: list[ResearchObjective] = []
        for item in parsed_objectives.objectives:
            objective = self._canonicalize_objective_document_ids(
                ResearchObjective.from_mapping(
                    {
                        **item.model_dump(),
                        "collection_id": collection_id,
                    }
                ),
                documents=documents,
            )
            if not is_question_shaped_objective(objective):
                continue
            matching_document_ids = {
                document_id
                for document_id, skim in discovery_skims_by_document_id.items()
                if self._discovery_skim_supports_objective(skim, objective)
            }
            seed_document_ids = set(objective.seed_document_ids)
            if not seed_document_ids and len(matching_document_ids) == 1:
                payload = objective.to_record()
                payload["seed_document_ids"] = sorted(matching_document_ids)
                objective = ResearchObjective.from_mapping(payload)
                seed_document_ids = set(objective.seed_document_ids)
                logger.info(
                    "Research objective recovered one missing seed document "
                    "collection_id=%s question=%s seed_document_id=%s",
                    collection_id,
                    objective.question,
                    next(iter(seed_document_ids)),
                )
            if not seed_document_ids or not seed_document_ids.issubset(
                matching_document_ids
            ):
                logger.warning(
                    "Research objective rejected because axes do not come from one "
                    "seed candidate collection_id=%s question=%s seed_document_ids=%s",
                    collection_id,
                    objective.question,
                    sorted(seed_document_ids),
                )
                continue
            objective = self._recover_shared_seed_material_scope(
                objective,
                discovery_skims_by_document_id=discovery_skims_by_document_id,
            )
            accepted_objectives.append(objective)

        research_objectives = tuple(accepted_objectives)
        research_objectives = self._canonicalize_research_objective_axes_with_llm(
            collection_id=collection_id,
            extractor=extractor,
            paper_skims=paper_skims,
            objectives=research_objectives,
        )
        research_objectives = self._merge_research_objectives_with_llm(
            collection_id=collection_id,
            extractor=extractor,
            paper_skims=paper_skims,
            objectives=research_objectives,
        )
        for objective in research_objectives:
            StructuredResearchObjective.model_validate(
                {
                    key: value
                    for key, value in objective.to_record().items()
                    if key in StructuredResearchObjective.model_fields
                }
            )
        research_objectives = self._dedupe_research_objectives(research_objectives)
        logger.info(
            "Research objective discovery finished collection_id=%s paper_skim_count=%s discovered_objective_count=%s accepted_objective_count=%s",
            collection_id,
            len(paper_skims),
            discovered_objective_count,
            len(research_objectives),
        )
        return research_objectives

    @staticmethod
    def _build_objective_discovery_skim(skim: PaperSkim) -> dict[str, Any]:
        """Keep collection-level discovery input within the model context budget."""

        def bounded_values(
            items: tuple[str, ...],
            limit: int,
        ) -> list[str]:
            return [
                str(item).strip()[:_DISCOVERY_TEXT_VALUE_CHARS]
                for item in items[:limit]
                if str(item).strip()
            ]

        possible_objectives = [
            text
            for item in skim.possible_objectives
            if (text := str(item).strip())
            and len(text) <= _DISCOVERY_OBJECTIVE_TEXT_CHARS
        ][:_DISCOVERY_OBJECTIVE_LIMIT]

        return {
            "document_id": skim.document_id,
            "doc_role": skim.doc_role,
            "candidate_materials": bounded_values(
                skim.candidate_materials,
                _DISCOVERY_SCOPE_VALUE_LIMIT,
            ),
            "candidate_processes": bounded_values(
                skim.candidate_processes,
                _DISCOVERY_SCOPE_VALUE_LIMIT,
            ),
            "candidate_properties": bounded_values(
                skim.candidate_properties,
                _DISCOVERY_AXIS_VALUE_LIMIT,
            ),
            "changed_variables": bounded_values(
                skim.changed_variables,
                _DISCOVERY_AXIS_VALUE_LIMIT,
            ),
            "possible_objectives": possible_objectives,
            "evidence_density": skim.evidence_density,
            "confidence": skim.confidence,
            "warnings": bounded_values(skim.warnings, _DISCOVERY_WARNING_LIMIT),
        }

    @staticmethod
    def _discovery_skim_supports_objective(
        skim: Mapping[str, Any],
        objective: ResearchObjective,
    ) -> bool:
        question_hints = _non_empty_text_values(
            skim.get("possible_objectives", ())
        )
        changed_variables = _non_empty_text_values(
            skim.get("changed_variables", ())
        )
        candidate_properties = _non_empty_text_values(
            skim.get("candidate_properties", ())
        )
        variables_supported = _values_support_all_axes(
            changed_variables,
            objective.variables,
        )
        outcomes_supported = _values_support_all_axes(
            candidate_properties,
            objective.outcomes,
        )
        if not question_hints:
            return variables_supported and outcomes_supported

        question_supports_axes = any(
            all(
                property_matching.source_text_mentions_axis(question, axis)
                for axis in (*objective.variables, *objective.outcomes)
            )
            for question in question_hints
        )
        has_structured_variables = bool(skim.get("changed_variables"))
        has_structured_outcomes = bool(skim.get("candidate_properties"))
        return (
            question_supports_axes
            and (not has_structured_variables or variables_supported)
            and (not has_structured_outcomes or outcomes_supported)
        )

    def _recover_shared_seed_material_scope(
        self,
        objective: ResearchObjective,
        *,
        discovery_skims_by_document_id: Mapping[str, Mapping[str, Any]],
    ) -> ResearchObjective:
        if objective.material_scope:
            return objective

        shared_materials = self._shared_seed_materials(
            objective.seed_document_ids,
            discovery_skims_by_document_id=discovery_skims_by_document_id,
        )
        if not shared_materials:
            return objective

        payload = objective.to_record()
        payload["material_scope"] = shared_materials
        recovered = ResearchObjective.from_mapping(payload)
        logger.info(
            "Research objective recovered shared seed material scope "
            "collection_id=%s objective_id=%s material_scope=%s",
            objective.collection_id,
            objective.objective_id,
            shared_materials,
        )
        return recovered

    def _shared_seed_materials(
        self,
        seed_document_ids: Iterable[str],
        *,
        discovery_skims_by_document_id: Mapping[str, Mapping[str, Any]],
    ) -> list[str]:
        materials_by_seed = [
            _non_empty_text_values(
                (discovery_skims_by_document_id.get(document_id) or {}).get(
                    "candidate_materials",
                    (),
                )
            )
            for document_id in seed_document_ids
        ]
        if not materials_by_seed or any(
            not materials for materials in materials_by_seed
        ):
            return []

        first_seed_materials, *remaining_seed_materials = materials_by_seed
        return self._unique_axis_values(
            material
            for material in first_seed_materials
            if all(
                any(
                    property_matching.axis_values_match(material, candidate)
                    for candidate in seed_materials
                )
                for seed_materials in remaining_seed_materials
            )
        )

    @staticmethod
    def _canonicalize_objective_document_ids(
        objective: ResearchObjective,
        *,
        documents: Iterable[Any],
    ) -> ResearchObjective:
        """Keep model-produced document references within the current build."""
        aliases: dict[str, str] = {}
        canonical_ids: set[str] = set()
        for document in documents:
            document_id = str(getattr(document, "document_id", "") or "").strip()
            if not document_id:
                continue
            canonical_ids.add(document_id)
            metadata = getattr(document, "metadata", {}) or {}
            for key in (
                "source_filename",
                "original_filename",
                "stored_filename",
                "source_path",
            ):
                value = str(metadata.get(key) or "").strip()
                if value:
                    aliases[value] = document_id
                    aliases[value.rsplit("/", 1)[-1]] = document_id

        def canonicalize(values: Iterable[str]) -> list[str]:
            result: list[str] = []
            seen: set[str] = set()
            for value in values:
                normalized = str(value or "").strip()
                document_id = (
                    normalized
                    if normalized in canonical_ids
                    else aliases.get(normalized)
                    or aliases.get(normalized.rsplit("/", 1)[-1])
                )
                if (
                    not document_id
                    and len(normalized) >= 32
                    and all(
                        character in "0123456789abcdefABCDEF"
                        for character in normalized
                    )
                ):
                    truncated_matches = [
                        candidate
                        for candidate in canonical_ids
                        if len(candidate) == len(normalized) + 1
                        and candidate.startswith(normalized)
                    ]
                    if len(truncated_matches) == 1:
                        document_id = truncated_matches[0]
                if document_id and document_id not in seen:
                    seen.add(document_id)
                    result.append(document_id)
            return result

        payload = objective.to_record()
        payload["seed_document_ids"] = canonicalize(objective.seed_document_ids)
        payload["excluded_document_ids"] = canonicalize(
            objective.excluded_document_ids
        )
        return ResearchObjective.from_mapping(payload)

    def _canonicalize_research_objective_axes_with_llm(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        axis_candidates = self._build_axis_canonicalization_candidates(objectives)
        if sum(len(values) for values in axis_candidates.values()) <= 1:
            return objectives
        payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
            "axis_candidates": axis_candidates,
        }
        try:
            canonicalization_plan = extractor.canonicalize_research_objective_axes(
                payload
            )
        except Exception:
            logger.warning(
                "Research objective axis canonicalization failed; using normalized axes collection_id=%s",
                collection_id,
                exc_info=True,
            )
            return objectives

        axis_mapping = self._validate_axis_canonicalization_plan(
            canonicalization_plan,
            axis_candidates=axis_candidates,
        )
        if axis_mapping is None:
            logger.warning(
                "Research objective axis canonicalization rejected; using normalized axes collection_id=%s",
                collection_id,
            )
            return objectives
        canonicalized = tuple(
            self._apply_axis_canonicalization(objective, axis_mapping)
            for objective in objectives
        )
        try:
            for objective in canonicalized:
                StructuredResearchObjective.model_validate(
                    {
                        key: value
                        for key, value in objective.to_record().items()
                        if key in StructuredResearchObjective.model_fields
                    }
                )
        except ValidationError:
            logger.warning(
                "Research objective axis canonicalization broke question roles; "
                "using original axes collection_id=%s",
                collection_id,
            )
            return objectives
        return canonicalized

    def _build_axis_canonicalization_candidates(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> dict[str, list[str]]:
        return {
            "material": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.material_scope
            ),
            "variable": self._unique_axis_values(
                value for objective in objectives for value in objective.variables
            ),
            "outcome": self._unique_axis_values(
                value for objective in objectives for value in objective.outcomes
            ),
            "mechanism": self._unique_axis_values(
                value for objective in objectives for value in objective.mechanisms
            ),
            "constraint": self._unique_axis_values(
                value for objective in objectives for value in objective.constraints
            ),
        }

    @staticmethod
    def _validate_axis_canonicalization_plan(
        canonicalization_plan: StructuredAxisCanonicalizationPlan,
        *,
        axis_candidates: dict[str, list[str]],
    ) -> dict[str, dict[str, str]] | None:
        expected_keys = {
            axis_type: {
                property_matching.axis_key(value)
                for value in values
                if property_matching.axis_key(value)
            }
            for axis_type, values in axis_candidates.items()
        }
        seen_keys: dict[str, set[str]] = {
            axis_type: set() for axis_type in expected_keys
        }
        axis_mapping: dict[str, dict[str, str]] = {
            axis_type: {} for axis_type in expected_keys
        }

        for group in canonicalization_plan.axis_groups:
            axis_type = group.axis_type
            if axis_type not in expected_keys:
                return None
            aliases = tuple(str(value or "").strip() for value in group.aliases)
            canonical = str(group.canonical or "").strip()
            canonical_key = property_matching.axis_key(canonical)
            alias_keys = tuple(property_matching.axis_key(alias) for alias in aliases)
            if not aliases or not canonical or not canonical_key:
                return None
            if canonical_key not in alias_keys:
                return None
            for alias, alias_key in zip(aliases, alias_keys, strict=True):
                if not alias_key:
                    return None
                if not property_matching.axis_alias_matches_canonical(alias, canonical):
                    return None
                if alias_key not in expected_keys[axis_type]:
                    return None
                if alias_key in seen_keys[axis_type]:
                    return None
                seen_keys[axis_type].add(alias_key)
                axis_mapping[axis_type][alias_key] = canonical

        for axis_type, expected in expected_keys.items():
            if seen_keys[axis_type] != expected:
                return None
        return axis_mapping

    def _apply_axis_canonicalization(
        self,
        objective: ResearchObjective,
        axis_mapping: dict[str, dict[str, str]],
    ) -> ResearchObjective:
        payload = objective.to_record()
        payload["material_scope"] = self._canonicalize_axis_values(
            objective.material_scope,
            axis_type="material",
            axis_mapping=axis_mapping,
        )
        payload["variables"] = self._canonicalize_axis_values(
            objective.variables,
            axis_type="variable",
            axis_mapping=axis_mapping,
        )
        payload["outcomes"] = self._canonicalize_axis_values(
            objective.outcomes,
            axis_type="outcome",
            axis_mapping=axis_mapping,
        )
        payload["mechanisms"] = self._canonicalize_axis_values(
            objective.mechanisms,
            axis_type="mechanism",
            axis_mapping=axis_mapping,
        )
        payload["constraints"] = self._canonicalize_axis_values(
            objective.constraints,
            axis_type="constraint",
            axis_mapping=axis_mapping,
        )
        return ResearchObjective.from_mapping(payload)

    def _canonicalize_axis_values(
        self,
        values: tuple[str, ...],
        *,
        axis_type: str,
        axis_mapping: dict[str, dict[str, str]],
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        mapping = axis_mapping.get(axis_type, {})
        for value in values:
            canonical = mapping.get(property_matching.axis_key(value), value)
            self._append_unique_axis(merged, seen, canonical)
        return merged

    def _merge_research_objectives_with_llm(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        if len(objectives) <= 1:
            return objectives
        payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
            "candidate_objectives": [
                objective.to_record() for objective in objectives
            ],
        }
        try:
            merge_plan = extractor.merge_research_objectives(payload)
        except Exception:
            logger.warning(
                "Research objective merge decision failed; using normalized objectives collection_id=%s",
                collection_id,
                exc_info=True,
            )
            return objectives

        merged = self._validate_objective_merge_plan(
            merge_plan,
            objectives=objectives,
        )
        if merged is None:
            logger.warning(
                "Research objective merge decision rejected; using normalized objectives collection_id=%s",
                collection_id,
            )
            return objectives
        return merged

    def _validate_objective_merge_plan(
        self,
        merge_plan: StructuredObjectiveMergePlan,
        *,
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...] | None:
        objective_by_id = {objective.objective_id: objective for objective in objectives}
        used_source_ids: set[str] = set()
        merged_objectives: list[ResearchObjective] = []

        for group in merge_plan.merged_objectives:
            source_ids = tuple(
                str(value or "").strip() for value in group.source_objective_ids
            )
            if not source_ids:
                return None
            if any(source_id not in objective_by_id for source_id in source_ids):
                return None
            if any(source_id in used_source_ids for source_id in source_ids):
                return None
            used_source_ids.update(source_ids)
            source_objectives = tuple(
                objective_by_id[source_id] for source_id in source_ids
            )
            if len(source_objectives) > 1:
                shared_outcome_keys = set.intersection(
                    *(
                        property_matching.axis_key_set(*objective.outcomes)
                        for objective in source_objectives
                    )
                )
                if not shared_outcome_keys:
                    return None
            material_scope = self._validated_merge_axes(
                tuple(group.material_scope),
                source_objectives=source_objectives,
                source_field="material_scope",
            )
            variables = self._validated_merge_axes(
                tuple(group.variables),
                source_objectives=source_objectives,
                source_field="variables",
            )
            outcomes = self._validated_merge_axes(
                tuple(group.outcomes),
                source_objectives=source_objectives,
                source_field="outcomes",
            )
            mechanisms = self._validated_merge_axes(
                tuple(group.mechanisms),
                source_objectives=source_objectives,
                source_field="mechanisms",
            )
            constraints = self._validated_merge_axes(
                tuple(group.constraints),
                source_objectives=source_objectives,
                source_field="constraints",
            )
            if any(
                values is None
                for values in (
                    material_scope,
                    variables,
                    outcomes,
                    mechanisms,
                    constraints,
                )
            ):
                return None

            if len(source_objectives) == 1:
                source = source_objectives[0]
                if str(group.question or "").strip() != source.question:
                    return None
                if group.requested_comparator != source.requested_comparator:
                    return None
            objective_payload = {
                "question": group.question,
                "material_scope": material_scope,
                "variables": variables,
                "outcomes": outcomes,
                "mechanisms": mechanisms,
                "constraints": constraints,
                "requested_comparator": group.requested_comparator,
                "seed_document_ids": self._merge_objective_axes(
                    source_objectives,
                    "seed_document_ids",
                ),
                "excluded_document_ids": self._merge_objective_axes(
                    source_objectives,
                    "excluded_document_ids",
                ),
                "confidence": group.confidence,
                "reason": group.reason,
            }
            try:
                StructuredResearchObjective.model_validate(objective_payload)
            except ValidationError:
                return None
            objective = ResearchObjective.from_mapping(
                {
                    "collection_id": source_objectives[0].collection_id,
                    **objective_payload,
                }
            )
            if not is_question_shaped_objective(objective):
                return None
            merged_objectives.append(objective)

        if used_source_ids != set(objective_by_id):
            return None
        return tuple(merged_objectives)

    @staticmethod
    def _dedupe_research_objectives(
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        unique_objectives: list[ResearchObjective] = []
        objective_by_id: dict[str, ResearchObjective] = {}
        for objective in objectives:
            existing = objective_by_id.get(objective.objective_id)
            if existing is not None:
                if existing.to_record() != objective.to_record():
                    raise ValueError(
                        "conflicting research objectives share objective_id: "
                        f"{objective.objective_id}"
                    )
                continue
            objective_by_id[objective.objective_id] = objective
            unique_objectives.append(objective)
        return tuple(unique_objectives)

    def _validated_merge_axes(
        self,
        values: tuple[str, ...],
        *,
        source_objectives: tuple[ResearchObjective, ...],
        source_field: str,
    ) -> list[str] | None:
        allowed_axes = property_matching.axis_key_set(
            *(
                value
                for objective in source_objectives
                for value in getattr(objective, source_field)
            )
        )
        if not values:
            return self._merge_objective_axes(source_objectives, source_field)
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = property_matching.axis_key(value)
            if not key:
                continue
            if key not in allowed_axes:
                return None
            self._append_unique_axis(merged, seen, value)
        for objective in source_objectives:
            for value in getattr(objective, source_field):
                self._append_unique_axis(merged, seen, value)
        return merged

    def _unique_axis_values(self, values: Iterable[Any]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            self._append_unique_axis(merged, seen, value)
        return merged

    def _merge_objective_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        field_name: str,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for objective in objectives:
            for value in getattr(objective, field_name):
                self._append_unique_axis(merged, seen, value)
        return merged

    @staticmethod
    def _append_unique_axis(
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = property_matching.axis_key(text)
        if key in seen:
            return
        seen.add(key)
        target.append(text)

    @staticmethod
    def _notify_progress(
        progress_callback: ProgressCallback | None,
        **progress_detail: Any,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(progress_detail)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Research objective progress callback failed phase=%s",
                progress_detail.get("phase"),
            )


__all__ = ["ObjectiveCandidateService"]

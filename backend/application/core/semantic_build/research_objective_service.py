from __future__ import annotations

import logging
from typing import Any

from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.source.collection_service import CollectionService
from domain.core import (
    PaperSkim,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
)
from domain.ports import CoreFactRepository, SourceArtifactRepository
from domain.source import SourceArtifactSet
from infra.persistence.factory import (
    build_core_fact_repository,
    build_source_artifact_repository,
)
from .llm.extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)
from .llm.schemas import StructuredObjectiveMergePlan

logger = logging.getLogger(__name__)

_SKIM_TEXT_PREVIEW_CHARS = 4000
_SKIM_HEADING_LIMIT = 16
_SKIM_CAPTION_LIMIT = 12
_BROAD_PROPERTY_AXIS_EXPANSIONS = {
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
}


class ResearchObjectivesNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve research objectives."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"research objectives not ready: {collection_id}")


class ResearchObjectiveService:
    """Build and serve Core research-objective records."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
        core_fact_repository: CoreFactRepository | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
        document_profile_service: DocumentProfileService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self._structured_extractor = structured_extractor
        self.core_fact_repository = (
            core_fact_repository
            or getattr(document_profile_service, "core_fact_repository", None)
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.source_artifact_repository = (
            source_artifact_repository
            or getattr(document_profile_service, "source_artifact_repository", None)
            or build_source_artifact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            structured_extractor=structured_extractor,
            core_fact_repository=self.core_fact_repository,
            source_artifact_repository=self.source_artifact_repository,
        )

    def read_paper_skims(self, collection_id: str) -> tuple[PaperSkim, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts.paper_skims
        self.build_research_objectives(collection_id)
        return self.core_fact_repository.read_collection_facts(collection_id).paper_skims

    def read_research_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts.research_objectives
        return self.build_research_objectives(collection_id)

    def build_research_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self._load_source_artifacts(collection_id)
            profiles = self.document_profile_service.read_document_profiles(collection_id)
        except (FileNotFoundError, DocumentProfilesNotReadyError) as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        profiles_by_document_id = {
            profile.document_id: profile
            for profile in profiles
        }
        blocks_by_document_id = self._group_by_document_id(artifacts.blocks)
        tables_by_document_id = self._group_by_document_id(artifacts.tables)
        figures_by_document_id = self._group_by_document_id(artifacts.figures)
        extractor = self._get_structured_extractor()

        logger.info(
            "Research objective paper skim started collection_id=%s document_count=%s",
            collection_id,
            len(artifacts.documents),
        )
        paper_skims: list[PaperSkim] = []
        for document in artifacts.documents:
            payload = self._build_paper_skim_payload(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=blocks_by_document_id.get(document.document_id, []),
                tables=tables_by_document_id.get(document.document_id, []),
                figures=figures_by_document_id.get(document.document_id, []),
            )
            parsed = extractor.extract_paper_skim(payload)
            record = parsed.model_dump()
            record.update(
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "source_filename": self._resolve_source_filename(document),
                }
            )
            paper_skims.append(PaperSkim.from_mapping(record))

        objective_payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
        }
        parsed_objectives = extractor.discover_research_objectives(objective_payload)
        skim_by_document_id = {
            skim.document_id: skim
            for skim in paper_skims
            if skim.document_id
        }
        research_objectives = tuple(
            objective
            for objective in (
                self._normalize_research_objective(
                    ResearchObjective.from_mapping(item.model_dump()),
                    skim_by_document_id=skim_by_document_id,
                    paper_skims=tuple(paper_skims),
                )
                for item in parsed_objectives.objectives
            )
            if is_question_shaped_objective(objective)
        )
        research_objectives = self._merge_research_objectives_with_llm(
            collection_id=collection_id,
            extractor=extractor,
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
        )

        self.core_fact_repository.replace_collection_research_objectives(
            collection_id,
            tuple(paper_skims),
            research_objectives,
        )
        logger.info(
            "Research objective build finished collection_id=%s paper_skim_count=%s objective_count=%s",
            collection_id,
            len(paper_skims),
            len(research_objectives),
        )
        return research_objectives

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

    def _load_source_artifacts(self, collection_id: str) -> SourceArtifactSet:
        artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        if not artifacts.documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return artifacts

    def _build_paper_skim_payload(
        self,
        *,
        collection_id: str,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
        figures: list[Any],
    ) -> dict[str, Any]:
        ordered_blocks = sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        )
        headings = self._extract_headings(ordered_blocks)
        text_preview = self._build_text_preview(document, ordered_blocks)
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": document.title,
            "source_filename": self._resolve_source_filename(document),
            "document_profile": profile.to_record() if profile else {},
            "text_preview": text_preview,
            "headings": headings,
            "table_captions": [
                {
                    "table_id": table.table_id,
                    "caption_text": table.caption_text,
                    "heading_path": table.heading_path,
                    "column_headers": list(table.column_headers),
                }
                for table in sorted(tables, key=lambda item: item.table_order)[
                    :_SKIM_CAPTION_LIMIT
                ]
            ],
            "figure_captions": [
                {
                    "figure_id": figure.figure_id,
                    "caption_text": figure.caption_text,
                    "heading_path": figure.heading_path,
                }
                for figure in sorted(figures, key=lambda item: item.figure_order)[
                    :_SKIM_CAPTION_LIMIT
                ]
            ],
        }

    def _extract_headings(self, blocks: list[Any]) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for block in blocks:
            heading = ""
            if getattr(block, "block_type", "") == "heading":
                heading = str(getattr(block, "text", "") or "").strip()
            if not heading:
                heading = str(getattr(block, "heading_path", "") or "").strip()
            if not heading:
                continue
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            headings.append(heading)
            if len(headings) >= _SKIM_HEADING_LIMIT:
                break
        return headings

    def _build_text_preview(self, document: Any, blocks: list[Any]) -> str:
        parts = [
            str(getattr(block, "text", "") or "").strip()
            for block in blocks
            if str(getattr(block, "text", "") or "").strip()
            and getattr(block, "block_type", "") in {"paragraph", "list_item"}
        ]
        text = "\n\n".join(parts).strip()
        if not text:
            text = str(document.text or "").strip()
        return text[:_SKIM_TEXT_PREVIEW_CHARS]

    def _resolve_source_filename(self, document: Any) -> str | None:
        metadata = getattr(document, "metadata", {}) or {}
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None

    def _normalize_research_objective(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> ResearchObjective:
        payload = objective.to_record()
        payload["process_axes"] = self._merge_process_axes_from_skims(
            objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        payload["property_axes"] = self._expand_broad_property_axes(
            objective.property_axes,
            objective=objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        if not str(payload.get("comparison_intent") or "").strip():
            payload["comparison_intent"] = self._build_comparison_intent(payload)
        return ResearchObjective.from_mapping(payload)

    def _merge_process_axes_from_skims(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in objective.process_axes:
            self._append_unique_axis(merged, seen, value)

        candidate_skims = [
            skim_by_document_id[document_id]
            for document_id in objective.seed_document_ids
            if document_id in skim_by_document_id
        ]
        if not candidate_skims:
            candidate_skims = list(paper_skims)
        for skim in candidate_skims:
            for value in (*skim.candidate_processes, *skim.changed_variables):
                self._append_unique_axis(merged, seen, value)
        return merged

    def _expand_broad_property_axes(
        self,
        values: tuple[str, ...],
        *,
        objective: ResearchObjective,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()
        available_properties = self._available_property_axes(
            objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            replacements = _BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized.lower())
            if replacements is None:
                self._append_unique_axis(expanded, seen, normalized)
                continue
            matched_replacements = [
                replacement
                for replacement in replacements
                if self._property_axis_is_available(replacement, available_properties)
            ]
            if not matched_replacements:
                self._append_unique_axis(expanded, seen, normalized)
                continue
            for replacement in matched_replacements:
                self._append_unique_axis(expanded, seen, replacement)
        return expanded

    def _available_property_axes(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        candidate_skims = [
            skim_by_document_id[document_id]
            for document_id in objective.seed_document_ids
            if document_id in skim_by_document_id
        ]
        if not candidate_skims:
            candidate_skims = list(paper_skims)
        return {
            self._axis_key(value)
            for skim in candidate_skims
            for value in skim.candidate_properties
            if self._axis_key(value)
        }

    def _property_axis_is_available(
        self,
        replacement: str,
        available_properties: set[str],
    ) -> bool:
        key = self._axis_key(replacement)
        if key in available_properties:
            return True
        if key == "microhardness" and "hardness" in available_properties:
            return True
        if (
            key == "corrosion current density"
            and "current density" in available_properties
        ):
            return True
        return False

    def _merge_research_objectives_with_llm(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        if len(objectives) <= 1:
            return objectives
        payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
            "candidate_objectives": [objective.to_record() for objective in objectives],
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
            paper_skims=paper_skims,
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
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[ResearchObjective, ...] | None:
        objective_by_id = {objective.objective_id: objective for objective in objectives}
        allowed_material_axes = self._allowed_material_axes(objectives, paper_skims)
        allowed_process_axes = self._allowed_process_axes(objectives, paper_skims)
        allowed_property_axes = self._allowed_property_axes(objectives, paper_skims)
        used_source_ids: set[str] = set()
        merged_objectives: list[ResearchObjective] = []

        for group in merge_plan.merged_objectives:
            source_ids = tuple(
                str(value or "").strip()
                for value in group.source_objective_ids
            )
            if not source_ids:
                return None
            if any(source_id not in objective_by_id for source_id in source_ids):
                return None
            if any(source_id in used_source_ids for source_id in source_ids):
                return None
            used_source_ids.update(source_ids)
            source_objectives = tuple(
                objective_by_id[source_id]
                for source_id in source_ids
            )
            property_components = self._property_overlap_components(source_objectives)
            if len(property_components) > 1:
                for component in property_components:
                    merged_objectives.append(
                        self._build_objective_from_property_component(component)
                    )
                continue

            material_scope = self._validated_merge_axes(
                tuple(group.material_scope),
                allowed_axes=allowed_material_axes,
                source_objectives=source_objectives,
                source_field="material_scope",
            )
            process_axes = self._validated_merge_axes(
                tuple(group.process_axes),
                allowed_axes=allowed_process_axes,
                source_objectives=source_objectives,
                source_field="process_axes",
            )
            property_axes = self._validated_merge_axes(
                tuple(group.property_axes),
                allowed_axes=allowed_property_axes,
                source_objectives=source_objectives,
                source_field="property_axes",
            )
            if material_scope is None or process_axes is None or property_axes is None:
                return None

            payload = {
                "objective_id": build_research_objective_id(group.question),
                "question": group.question,
                "material_scope": material_scope,
                "process_axes": process_axes,
                "property_axes": property_axes,
                "comparison_intent": group.comparison_intent,
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
            objective = ResearchObjective.from_mapping(payload)
            if not objective.comparison_intent:
                return None
            if not is_question_shaped_objective(objective):
                return None
            merged_objectives.append(objective)

        if used_source_ids != set(objective_by_id):
            return None
        return tuple(merged_objectives)

    def _property_overlap_components(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[tuple[ResearchObjective, ...], ...]:
        components: list[tuple[list[ResearchObjective], set[str]]] = []
        for objective in objectives:
            current_keys = self._axis_key_set(*objective.property_axes)
            matched_indexes = [
                index
                for index, (_, component_keys) in enumerate(components)
                if current_keys and component_keys.intersection(current_keys)
            ]
            if not matched_indexes:
                components.append(([objective], set(current_keys)))
                continue
            first_index = matched_indexes[0]
            components[first_index][0].append(objective)
            components[first_index][1].update(current_keys)
            for index in reversed(matched_indexes[1:]):
                objectives_to_move, keys_to_move = components.pop(index)
                components[first_index][0].extend(objectives_to_move)
                components[first_index][1].update(keys_to_move)
        return tuple(tuple(component_objectives) for component_objectives, _ in components)

    def _build_objective_from_property_component(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> ResearchObjective:
        if len(objectives) == 1:
            return objectives[0]
        payload = {
            "material_scope": self._merge_objective_axes(objectives, "material_scope"),
            "process_axes": self._merge_objective_axes(objectives, "process_axes"),
            "property_axes": self._merge_objective_axes(objectives, "property_axes"),
            "seed_document_ids": self._merge_objective_axes(
                objectives,
                "seed_document_ids",
            ),
            "excluded_document_ids": self._merge_objective_axes(
                objectives,
                "excluded_document_ids",
            ),
            "confidence": max(objective.confidence for objective in objectives),
            "reason": "Merged objectives with overlapping property axes.",
        }
        payload["question"] = self._build_research_objective_question(payload)
        payload["objective_id"] = build_research_objective_id(payload["question"])
        payload["comparison_intent"] = self._build_comparison_intent(payload)
        return ResearchObjective.from_mapping(payload)

    def _validated_merge_axes(
        self,
        values: tuple[str, ...],
        *,
        allowed_axes: set[str],
        source_objectives: tuple[ResearchObjective, ...],
        source_field: str,
    ) -> list[str] | None:
        if not values:
            return self._merge_objective_axes(source_objectives, source_field)
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = self._axis_key(value)
            if not key:
                continue
            if key not in allowed_axes:
                return None
            self._append_unique_axis(merged, seen, value)
        return merged

    def _allowed_material_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(
                value
                for objective in objectives
                for value in objective.material_scope
            ),
            *(value for skim in paper_skims for value in skim.candidate_materials),
        )

    def _allowed_process_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(value for objective in objectives for value in objective.process_axes),
            *(value for skim in paper_skims for value in skim.candidate_processes),
            *(value for skim in paper_skims for value in skim.changed_variables),
        )

    def _allowed_property_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(value for objective in objectives for value in objective.property_axes),
            *(value for skim in paper_skims for value in skim.candidate_properties),
        )

    def _axis_key_set(self, *values: Any) -> set[str]:
        return {self._axis_key(value) for value in values if self._axis_key(value)}

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

    def _build_research_objective_question(self, payload: dict[str, Any]) -> str:
        process_text = (
            self._join_axis_text(payload.get("process_axes"))
            or "the studied process axes"
        )
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        return f"How do {process_text} affect {property_text} of {material_text}?"

    def _build_comparison_intent(self, payload: dict[str, Any]) -> str:
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        process_text = (
            self._join_axis_text(payload.get("process_axes"))
            or "the studied process axes"
        )
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        return (
            f"Compare {material_text} across {process_text} and evaluate changes in "
            f"{property_text}."
        )

    def _append_unique_axis(
        self,
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = self._axis_key(text)
        if key in seen:
            return
        seen.add(key)
        target.append(text)

    def _axis_key(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        if text.endswith(")") and "(" in text:
            base, _, suffix = text.rpartition("(")
            acronym = suffix[:-1].strip()
            if base.strip() and acronym.isalpha() and len(acronym) <= 8:
                text = base.strip()
        return " ".join(text.split())

    def _join_axis_text(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""
        return ", ".join(str(item).strip() for item in value if str(item).strip())

    def _group_by_document_id(self, values: tuple[Any, ...]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for value in values:
            document_id = str(getattr(value, "document_id", "") or "")
            if not document_id:
                continue
            grouped.setdefault(document_id, []).append(value)
        return grouped


__all__ = [
    "ResearchObjectiveService",
    "ResearchObjectivesNotReadyError",
]

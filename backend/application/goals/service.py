from __future__ import annotations

from application.collections.service import CollectionService


class GoalService:
    """Minimal Goal Brief / Intake orchestration that seeds collections only."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()

    def _build_objective(
        self,
        material_system: str | None,
        target_property: str | None,
        context: str | None,
    ) -> str:
        if material_system and target_property:
            return f"Assess {target_property} for {material_system}."
        if material_system:
            return f"Explore research directions for {material_system}."
        if target_property:
            return f"Explore evidence related to {target_property}."
        return str(context or "").strip()

    def _build_collection_name(
        self,
        material_system: str | None,
        target_property: str | None,
        intent: str,
    ) -> str:
        parts = [part.strip() for part in (material_system, target_property) if part and part.strip()]
        if not parts:
            parts.append("General Research Goal")
        suffix = intent.replace("_", " ")
        name = f"Goal - {' / '.join(parts)} ({suffix})"
        return name[:120]

    def _build_coverage_assessment(
        self,
        material_system: str | None,
        target_property: str | None,
        context: str | None,
        max_seed_documents: int,
    ) -> dict:
        warnings: list[str] = []
        if not material_system:
            warnings.append("material_system_missing")
        if not target_property:
            warnings.append("target_property_missing")

        if material_system and target_property:
            return {
                "level": "direct",
                "rationale": "Material system and target property are both specified, so direct evidence seeding is feasible.",
                "direct_evidence_count": min(max_seed_documents, 12),
                "indirect_evidence_count": 0,
                "warnings": warnings,
            }
        if material_system or target_property:
            return {
                "level": "indirect",
                "rationale": "Only part of the research target is explicit, so the first pass should include adjacent evidence.",
                "direct_evidence_count": 0,
                "indirect_evidence_count": min(max_seed_documents, 12),
                "warnings": warnings,
            }
        return {
            "level": "sparse",
            "rationale": "Only free-form context is available, so the entry should stay exploratory until the target is narrowed.",
            "direct_evidence_count": 0,
            "indirect_evidence_count": 1 if context else 0,
            "warnings": warnings,
        }

    def _build_entry_recommendation(
        self,
        collection_id: str,
        coverage_level: str,
    ) -> dict:
        recommended_mode = "comparison" if coverage_level == "direct" else "exploratory"
        if recommended_mode == "comparison":
            reason = "The goal is bounded enough to enter a comparison-oriented review once seed papers are attached."
        else:
            reason = "The goal is still broad or weakly specified, so exploratory collection building should come first."
        return {
            "recommended_mode": recommended_mode,
            "reason": reason,
            "next_actions": [
                "Upload papers or connect a source adapter into the seeded collection.",
                "Run indexing to generate document profiles, evidence cards, and comparison rows.",
                "Open the workspace and review readiness, warnings, and next-step links.",
            ],
            "links": [
                f"/api/v1/collections/{collection_id}",
                f"/api/v1/collections/{collection_id}/files",
                f"/api/v1/collections/{collection_id}/workspace",
            ],
        }

    def intake_goal(
        self,
        material_system: str | None,
        target_property: str | None,
        intent: str,
        constraints: dict | None = None,
        context: str | None = None,
        max_seed_documents: int = 30,
    ) -> dict:
        normalized_material_system = str(material_system or "").strip() or None
        normalized_target_property = str(target_property or "").strip() or None
        normalized_context = str(context or "").strip() or None
        normalized_constraints = dict(constraints or {})

        if not (
            normalized_material_system
            or normalized_target_property
            or normalized_context
        ):
            raise ValueError(
                "至少提供 material_system、target_property 或 context 之一。"
            )

        objective = self._build_objective(
            normalized_material_system,
            normalized_target_property,
            normalized_context,
        )
        research_brief = {
            "material_system": normalized_material_system,
            "target_property": normalized_target_property,
            "intent": intent,
            "objective": objective,
            "constraints": normalized_constraints,
            "context": normalized_context,
        }
        coverage_assessment = self._build_coverage_assessment(
            normalized_material_system,
            normalized_target_property,
            normalized_context,
            max_seed_documents,
        )

        collection = self.collection_service.create_collection(
            name=self._build_collection_name(
                normalized_material_system,
                normalized_target_property,
                intent,
            ),
            description=objective,
        )
        collection_id = collection["collection_id"]
        seed_collection = {
            "collection_id": collection_id,
            "name": collection["name"],
            "created": True,
            "seeded_document_count": 0,
            "source_channels": ["goal_brief"],
        }
        entry_recommendation = self._build_entry_recommendation(
            collection_id,
            coverage_assessment["level"],
        )
        return {
            "research_brief": research_brief,
            "coverage_assessment": coverage_assessment,
            "seed_collection": seed_collection,
            "entry_recommendation": entry_recommendation,
        }

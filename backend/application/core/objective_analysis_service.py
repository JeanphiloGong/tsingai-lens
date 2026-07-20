from __future__ import annotations

import logging
from typing import Any

from application.core.research_understanding_service import ResearchUnderstandingService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from domain.core import ResearchObjective, ResearchUnderstanding
from domain.ports import ObjectiveRepository, ResearchUnderstandingRepository


logger = logging.getLogger(__name__)

_PROGRESS_UPDATE_INTERVAL = 3
_NO_RESEARCH_FINDINGS_ERROR = "objective analysis produced no research findings"
_REVIEW_ONLY_WARNING = (
    "objective analysis produced review candidates but no primary research findings"
)


class ObjectiveAnalysisService:
    """Run one persisted Research Objective through deep analysis."""

    def __init__(
        self,
        *,
        objective_repository: ObjectiveRepository,
        research_understanding_repository: ResearchUnderstandingRepository,
        research_objective_service: ResearchObjectiveService,
        research_understanding_service: ResearchUnderstandingService,
    ) -> None:
        self.objective_repository = objective_repository
        self.research_understanding_repository = research_understanding_repository
        self.research_objective_service = research_objective_service
        self.research_understanding_service = research_understanding_service

    def confirm_objective(self, collection_id: str, objective_id: str) -> dict:
        objective = self.objective_repository.confirm_objective(
            collection_id,
            objective_id,
        )
        return self._result(collection_id, objective)

    def queue_analysis(self, collection_id: str, objective_id: str) -> dict:
        objective = self.objective_repository.queue_objective_analysis(
            collection_id,
            objective_id,
        )
        return self._result(collection_id, objective)

    def get_analysis(self, collection_id: str, objective_id: str) -> dict:
        objective = self._require_objective(collection_id, objective_id)
        return self._result(collection_id, objective)

    def run_analysis(self, collection_id: str, objective_id: str) -> dict:
        objective = self.objective_repository.claim_objective_analysis(
            collection_id,
            objective_id,
        )
        if objective is None:
            return self.get_analysis(collection_id, objective_id)
        try:
            understanding = self.research_objective_service.analyze_objective(
                collection_id,
                objective_id,
                progress_callback=self._build_progress_callback(
                    collection_id,
                    objective_id,
                ),
            )
            presented = self._with_presentation(understanding)
            if not self._has_research_findings(presented):
                raise RuntimeError(_NO_RESEARCH_FINDINGS_ERROR)
            self.research_understanding_repository.upsert_objective_understanding(
                collection_id,
                objective_id,
                presented,
            )
            persisted = self.research_understanding_repository.read_objective_understanding(
                collection_id,
                objective_id,
            )
            persisted = self._with_presentation(persisted)
            if not self._has_research_findings(persisted):
                raise RuntimeError(_NO_RESEARCH_FINDINGS_ERROR)
            objective = self.objective_repository.mark_objective_analysis_ready(
                collection_id,
                objective_id,
            )
            return self._result(collection_id, objective, persisted)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Objective analysis failed collection_id=%s objective_id=%s",
                collection_id,
                objective_id,
            )
            objective = self.objective_repository.mark_objective_analysis_failed(
                collection_id,
                objective_id,
                str(exc),
            )
            return self._result(collection_id, objective)

    def _result(
        self,
        collection_id: str,
        objective: ResearchObjective,
        understanding: ResearchUnderstanding | None = None,
    ) -> dict:
        if understanding is None:
            understanding = self.research_understanding_repository.read_objective_understanding(
                collection_id,
                objective.objective_id,
            )
            understanding = self._with_presentation(understanding)
        warnings = []
        if (
            objective.status == "ready"
            and understanding is not None
            and not self._has_primary_findings(understanding)
            and self._has_review_findings(understanding)
        ):
            warnings.append(_REVIEW_ONLY_WARNING)
        return {
            "collection_id": collection_id,
            "objective": objective,
            "understanding": understanding,
            "warnings": warnings,
        }

    def _require_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = self.objective_repository.read_objective_workspace(
            collection_id,
            objective_id,
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return objective

    def _build_progress_callback(self, collection_id: str, objective_id: str):
        last_update: tuple[str, int | None, int | None] = ("", None, None)

        def callback(progress: dict[str, Any]) -> None:
            nonlocal last_update
            phase = str(progress.get("phase") or "").strip()
            if not phase:
                return
            current = self._safe_int(progress.get("current"))
            total = self._safe_int(progress.get("total"))
            previous_phase, previous_current, previous_total = last_update
            if not (
                phase != previous_phase
                or total != previous_total
                or current is None
                or total is None
                or current == 1
                or current >= total
                or previous_current is None
                or current - previous_current >= _PROGRESS_UPDATE_INTERVAL
            ):
                return
            last_update = (phase, current, total)
            self.objective_repository.update_objective_analysis_progress(
                collection_id,
                objective_id,
                progress,
            )

        return callback

    def _with_presentation(
        self,
        understanding: ResearchUnderstanding | None,
    ) -> ResearchUnderstanding | None:
        if understanding is None:
            return None
        record = self.research_understanding_service.with_presentation(understanding)
        return ResearchUnderstanding.from_mapping(record or {})

    @classmethod
    def _has_research_findings(cls, understanding: ResearchUnderstanding | None) -> bool:
        return cls._has_primary_findings(understanding) or cls._has_review_findings(
            understanding
        )

    @staticmethod
    def _has_primary_findings(understanding: ResearchUnderstanding | None) -> bool:
        return bool(understanding and understanding.presentation.get("primary_findings"))

    @staticmethod
    def _has_review_findings(understanding: ResearchUnderstanding | None) -> bool:
        return bool(
            understanding and understanding.presentation.get("review_queue_findings")
        )

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = ["ObjectiveAnalysisService"]

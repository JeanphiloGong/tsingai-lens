from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from openai import OpenAI, OpenAIError

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewMaterialNotFoundError,
    ResearchViewNotReadyError,
)
from application.core.semantic_build.paper_facts_service import (
    PaperFactsNotReadyError,
    PaperFactsService,
)
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectiveService,
    ResearchObjectivesNotReadyError,
)
from application.evaluation.research_understanding_feedback_service import (
    ResearchUnderstandingFeedbackService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.goal import (
    GoalAnswerMode,
    GoalMessageRecord,
    GoalSessionRecord,
    GoalSourceLink,
    GoalSourceMode,
)
from domain.ports import GoalSessionRepository
from infra.persistence.factory import build_goal_session_repository

AnswerMode = GoalAnswerMode
SourceMode = GoalSourceMode
_GENERAL_FALLBACK_PREFIX = (
    "The current collection does not contain structured evidence for this "
    "question. The following answer is general background and should not be "
    "treated as a collection-supported conclusion.\n\n"
)
_MAX_CONTEXT_CHARS = 18000
_MAX_ROLLING_SUMMARY_CHARS = 1600
_MAX_SOURCE_LINKS = 12
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_UNSET = object()


class GoalSessionNotFoundError(FileNotFoundError):
    """Raised when a goal session cannot be found."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"goal session not found: {session_id}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


class GoalSessionService:
    """Collection-bound goal conversation sessions over Core artifacts."""

    def __init__(
        self,
        *,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        research_view_service: ResearchViewAggregationService | None = None,
        workspace_service: WorkspaceService | None = None,
        comparison_service: ComparisonService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        research_objective_service: ResearchObjectiveService | None = None,
        research_understanding_feedback_service: (
            ResearchUnderstandingFeedbackService | None
        ) = None,
        goal_session_repository: GoalSessionRepository | None = None,
        llm_client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService(
            self.collection_service.root_dir.parent / "tasks"
        )
        self.research_view_service = (
            research_view_service
            or ResearchViewAggregationService(
                collection_service=self.collection_service,
                task_service=self.task_service,
            )
        )
        self.workspace_service = workspace_service or WorkspaceService(
            collection_service=self.collection_service,
            task_service=self.task_service,
        )
        self.comparison_service = comparison_service or ComparisonService(
            collection_service=self.collection_service,
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
        )
        self.research_objective_service = (
            research_objective_service
            or ResearchObjectiveService(collection_service=self.collection_service)
        )
        self.research_understanding_feedback_service = (
            research_understanding_feedback_service
            or ResearchUnderstandingFeedbackService()
        )
        self.goal_session_repository = (
            goal_session_repository or build_goal_session_repository()
        )
        self.model = (
            model
            or os.getenv("GOAL_COPILOT_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        ).strip()
        self.llm_client = llm_client or OpenAI(
            api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
            base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        )

    def create_session(
        self,
        *,
        collection_id: str,
        user_id: str = "local-user",
        focused_material_id: str | None = None,
        focused_paper_id: str | None = None,
        focused_objective_id: str | None = None,
        focused_goal_id: str | None = None,
        goal_text: str | None = None,
        goal_brief_json: dict[str, Any] | None = None,
        answer_mode: str | None = "hybrid",
    ) -> dict[str, Any]:
        collection = self.collection_service.get_collection(collection_id)
        now = _now_iso()
        session = GoalSessionRecord.create(
            session_id=f"gs_{uuid4().hex[:12]}",
            user_id=user_id,
            collection_id=collection["collection_id"],
            focused_material_id=focused_material_id,
            focused_paper_id=focused_paper_id,
            focused_objective_id=focused_objective_id,
            focused_goal_id=focused_goal_id,
            goal_text=goal_text,
            goal_brief_json=goal_brief_json,
            answer_mode=answer_mode,
            collection_data_version=self._collection_data_version(collection),
            now_iso=now,
        )
        session_record = session.to_record()
        self._write_session(session_record)
        self._write_messages(session_record, [])
        return session_record

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = GoalSessionRecord.from_mapping(self._read_session(session_id))
        collection_data_version = self._collection_data_version(
            self.collection_service.get_collection(session.collection_id)
        )
        return session.with_collection_data_version(
            collection_data_version=collection_data_version,
            updated_at=session.updated_at,
        ).to_record()

    def get_session_for_user(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session["user_id"] != user_id:
            raise GoalSessionNotFoundError(session_id)
        return session

    def update_session(
        self,
        session_id: str,
        *,
        collection_id: Any = _UNSET,
        focused_material_id: Any = _UNSET,
        focused_paper_id: Any = _UNSET,
        focused_objective_id: Any = _UNSET,
        focused_goal_id: Any = _UNSET,
        goal_text: Any = _UNSET,
        goal_brief_json: Any = _UNSET,
        answer_mode: Any = _UNSET,
    ) -> dict[str, Any]:
        session = GoalSessionRecord.from_mapping(self._read_session(session_id))
        if collection_id is not _UNSET:
            next_collection_id = _clean_text(collection_id)
            if not next_collection_id:
                raise ValueError("collection_id cannot be cleared")
            if next_collection_id != session.collection_id:
                self.collection_service.get_collection(next_collection_id)
                session = session.bind_collection(next_collection_id)
        if focused_material_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=session.focused_goal_id,
            )
        if focused_paper_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=focused_paper_id,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=session.focused_goal_id,
            )
        if focused_objective_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=focused_objective_id,
                focused_goal_id=session.focused_goal_id,
            )
        if focused_goal_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=focused_goal_id,
            )
        if goal_text is not _UNSET:
            session = session.with_goal_text(goal_text)
        if goal_brief_json is not _UNSET:
            session = session.with_goal_brief_json(goal_brief_json)
        if answer_mode is not _UNSET:
            session = session.with_answer_mode(answer_mode)
        session = session.with_collection_data_version(
            collection_data_version=self._collection_data_version(
                self.collection_service.get_collection(session.collection_id)
            ),
            updated_at=_now_iso(),
        )
        session_record = session.to_record()
        self._write_session(session_record)
        return session_record

    def update_session_for_user(
        self,
        session_id: str,
        user_id: str,
        **fields: Any,
    ) -> dict[str, Any]:
        self.get_session_for_user(session_id, user_id)
        session = self.update_session(session_id, **fields)
        if session["user_id"] != user_id:
            raise GoalSessionNotFoundError(session_id)
        return session

    def list_messages(self, session_id: str) -> dict[str, Any]:
        session = GoalSessionRecord.from_mapping(self._read_session(session_id))
        return {
            "session_id": session.session_id,
            "items": self._read_messages(session.session_id),
        }

    def list_messages_for_user(self, session_id: str, user_id: str) -> dict[str, Any]:
        self.get_session_for_user(session_id, user_id)
        return self.list_messages(session_id)

    def post_message(
        self,
        session_id: str,
        *,
        message: str,
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_message = _clean_text(message)
        if not user_message:
            raise ValueError("message is required")

        session = GoalSessionRecord.from_mapping(self._read_session(session_id))
        session = self._apply_page_context(session, page_context or {})
        session, command_response = self._apply_inline_command(session, user_message)
        messages = self._read_messages(session.session_id)
        now = _now_iso()
        user_record = GoalMessageRecord.user(
            message_id=f"msg_{uuid4().hex[:12]}",
            session_id=session.session_id,
            content=user_message,
            created_at=now,
        )
        messages.append(user_record.to_record())

        if command_response is not None:
            response, session = self._build_command_message(session, command_response)
        else:
            response, session = self._answer_message(session, user_message)

        messages.append(response)
        session_record = session.to_record()
        self._write_session(session_record)
        self._write_messages(session_record, messages)
        return response

    def post_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_session_for_user(session_id, user_id)
        return self.post_message(
            session_id,
            message=message,
            page_context=page_context,
        )

    def _answer_message(
        self, session: GoalSessionRecord, message: str
    ) -> tuple[dict[str, Any], GoalSessionRecord]:
        mode: AnswerMode = session.answer_mode
        context = self._build_collection_context(session) if mode != "general" else {}
        has_collection_context = bool(context.get("has_collection_context"))
        warnings = list(context.get("warnings", []))
        used_evidence_ids = (
            self._stable_strings(context.get("evidence_ids"))
            if has_collection_context
            else []
        )
        links = dict(context.get("links") or {})
        source_links = (
            list(context.get("source_links") or []) if has_collection_context else []
        )

        if mode == "grounded" and not has_collection_context:
            source_mode: SourceMode = "collection_limited"
            answer = (
                "The bound collection does not currently contain structured Core "
                "evidence that can answer this question. Finish indexing, add more "
                "source material, or switch to hybrid/general mode for background."
            )
            warnings.append("no_collection_evidence_found")
        elif mode == "general":
            source_mode = "general_only"
            answer, failed_warning = self._try_generate_llm_answer(
                session=session,
                user_message=message,
                source_mode=source_mode,
                context={},
            )
            if failed_warning:
                warnings.append(failed_warning)
            used_evidence_ids = []
        elif has_collection_context:
            source_mode = "collection_grounded"
            answer, failed_warning = self._try_generate_llm_answer(
                session=session,
                user_message=message,
                source_mode=source_mode,
                context=context,
            )
            if failed_warning:
                source_mode = "collection_limited"
                warnings.append(failed_warning)
                used_evidence_ids = []
                source_links = []
            elif source_links and not self._answer_cites_source_link(
                answer,
                source_links,
            ):
                source_mode = "collection_limited"
                warnings.append("goal_copilot_missing_source_citation")
                answer = (
                    "Lens could not verify source citations in the generated answer, "
                    "so do not treat it as a traceable collection conclusion.\n\n"
                    f"{answer}"
                )
                used_evidence_ids = []
                source_links = []
        else:
            source_mode = "general_fallback"
            warnings.append("no_collection_evidence_found")
            generated, failed_warning = self._try_generate_llm_answer(
                session=session,
                user_message=message,
                source_mode=source_mode,
                context={},
            )
            if failed_warning:
                warnings.append(failed_warning)
            answer = self._ensure_general_fallback_boundary(generated)
            used_evidence_ids = []

        assistant_message = GoalMessageRecord.assistant(
            message_id=f"msg_{uuid4().hex[:12]}",
            session_id=session.session_id,
            content=answer,
            source_mode=source_mode,
            used_evidence_ids=used_evidence_ids,
            warnings=warnings,
            links=links,
            source_links=source_links,
            created_at=_now_iso(),
        )
        session = self._update_session_after_answer(
            session,
            user_message=message,
            assistant_message=assistant_message,
            context=context,
        )
        return assistant_message.to_record(), session

    def _build_command_message(
        self,
        session: GoalSessionRecord,
        command_response: str,
    ) -> tuple[dict[str, Any], GoalSessionRecord]:
        assistant_message = GoalMessageRecord.assistant(
            message_id=f"msg_{uuid4().hex[:12]}",
            session_id=session.session_id,
            content=command_response,
            source_mode="collection_limited",
            used_evidence_ids=[],
            warnings=[],
            links=self._session_links(session),
            source_links=[],
            created_at=_now_iso(),
        )
        session = self._update_session_after_answer(
            session,
            user_message=command_response,
            assistant_message=assistant_message,
            context={},
        )
        return assistant_message.to_record(), session

    def _apply_page_context(
        self,
        session: GoalSessionRecord,
        page_context: dict[str, Any],
    ) -> GoalSessionRecord:
        material_id = _clean_text(page_context.get("material_id"))
        paper_id = _clean_text(
            page_context.get("paper_id") or page_context.get("document_id")
        )
        objective_id = _clean_text(page_context.get("objective_id"))
        goal_id = _clean_text(page_context.get("goal_id"))
        return session.with_page_context(
            material_id=material_id,
            paper_id=paper_id,
            objective_id=objective_id,
            goal_id=goal_id,
        )

    def _apply_inline_command(
        self,
        session: GoalSessionRecord,
        message: str,
    ) -> tuple[GoalSessionRecord, str | None]:
        text = message.strip()
        if not text.startswith("$"):
            return session, None
        command, _, argument = text[1:].partition(" ")
        command = command.strip().lower()
        argument = argument.strip()
        if command == "mode":
            session = session.with_answer_mode(argument)
            return session, f"Answer mode updated to {session.answer_mode}."
        if command == "material":
            session = session.with_focus(
                focused_material_id=argument,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=session.focused_goal_id,
            )
            return (
                session,
                f"Focused material updated to {session.focused_material_id or 'none'}.",
            )
        if command in {"paper", "document"}:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=argument,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=session.focused_goal_id,
            )
            return (
                session,
                f"Focused paper updated to {session.focused_paper_id or 'none'}.",
            )
        if command == "objective":
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=argument,
                focused_goal_id=session.focused_goal_id,
            )
            return (
                session,
                f"Focused objective updated to {session.focused_objective_id or 'none'}.",
            )
        if command == "confirmed-goal":
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=session.focused_objective_id,
                focused_goal_id=argument,
            )
            return (
                session,
                f"Focused confirmed goal updated to {session.focused_goal_id or 'none'}.",
            )
        if command == "goal":
            return session.with_goal_text(argument), "Goal updated."
        if command == "clear" and argument == "focus":
            return (
                session.with_focus(
                    focused_material_id=None,
                    focused_paper_id=None,
                    focused_objective_id=None,
                    focused_goal_id=None,
                ),
                "Focus cleared.",
            )
        if command == "collection":
            self.collection_service.get_collection(argument)
            session = session.bind_collection(argument, clear_focus=True)
            return session, f"Bound collection updated to {session.collection_id}."
        raise ValueError(f"unsupported goal session command: ${command}")

    def _build_collection_context(self, session: GoalSessionRecord) -> dict[str, Any]:
        collection_id = session.collection_id
        warnings: list[str] = []
        collection = self.collection_service.get_collection(collection_id)
        workspace = self._safe_workspace(collection_id, warnings)
        focused_material_id = session.focused_material_id
        focused_objective_id = session.focused_objective_id
        focused_goal_id = session.focused_goal_id
        objectives = self._safe_objectives(collection_id, warnings)
        objective_research_view = None
        if focused_objective_id:
            objective_research_view = self._safe_objective_research_view(
                collection_id,
                focused_objective_id,
                warnings,
            )
        material_profile = None
        collection_research_view = None
        if focused_material_id:
            material_profile = self._safe_material_profile(
                collection_id,
                focused_material_id,
                warnings,
            )
        else:
            collection_research_view = self._safe_collection_research_view(
                collection_id,
                warnings,
            )
        comparisons = self._safe_comparisons(collection_id, warnings)
        evidence_cards = self._safe_evidence_cards(collection_id, warnings)
        curated_research_findings = self._safe_curated_research_findings(
            collection_id,
            focused_goal_id=focused_goal_id,
            focused_objective_id=focused_objective_id,
            warnings=warnings,
        )
        if (focused_goal_id or focused_objective_id) and not curated_research_findings:
            warnings.append("curated_research_findings_empty")
        if curated_research_findings:
            warnings = [
                warning
                for warning in warnings
                if warning
                not in {"comparison_rows_not_ready", "evidence_cards_not_ready"}
            ]

        context_payload = {
            "collection": collection,
            "workspace": workspace,
            "focused_material_id": focused_material_id,
            "focused_paper_id": session.focused_paper_id,
            "focused_objective_id": focused_objective_id,
            "focused_goal_id": focused_goal_id,
            "research_objectives": objectives,
            "objective_research_view": objective_research_view,
            "material_profile": material_profile,
            "collection_research_view": collection_research_view,
            "comparisons": comparisons,
            "evidence_cards": evidence_cards,
            "curated_research_findings": curated_research_findings,
        }
        if curated_research_findings or focused_goal_id:
            source_context_payload = {
                "collection": collection,
                "focused_material_id": focused_material_id,
                "focused_paper_id": session.focused_paper_id,
                "focused_objective_id": focused_objective_id,
                "focused_goal_id": focused_goal_id,
            }
            if curated_research_findings:
                source_context_payload["curated_research_findings"] = curated_research_findings
        else:
            source_context_payload = context_payload
        evidence_ids = self._collect_evidence_ids(source_context_payload)
        material_ids = self._collect_material_ids(source_context_payload)
        paper_ids = self._collect_paper_ids(source_context_payload)
        source_refs = self._build_source_refs(
            collection_id,
            evidence_sources=self._collect_evidence_sources(source_context_payload),
            paper_ids=paper_ids,
        )
        has_collection_context = bool(
            evidence_ids
            or self._has_non_empty_path(material_profile, ("sample_matrix", "rows"))
            or self._has_non_empty_path(objectives, ("objectives",))
            or self._has_non_empty_path(objective_research_view, ("evidence_units",))
            or self._has_non_empty_path(objective_research_view, ("logic_chain",))
            or bool(curated_research_findings)
            or self._has_non_empty_path(collection_research_view, ("materials",))
            or self._has_non_empty_path(
                collection_research_view, ("comparable_groups",)
            )
            or self._has_non_empty_path(comparisons, ("items",))
            or self._has_non_empty_path(evidence_cards, ("items",))
        )
        return {
            "has_collection_context": has_collection_context,
            "warnings": warnings,
            "evidence_ids": evidence_ids,
            "material_ids": material_ids,
            "paper_ids": paper_ids,
            "links": self._session_links(session),
            "source_links": self._public_source_links(source_refs),
            "source_refs": source_refs,
            "payload": self._compact_value(source_context_payload),
            "prompt_source_links": self._prompt_source_links(source_refs),
            "prompt_payload": self._prompt_payload(source_context_payload, source_refs),
        }

    def _safe_workspace(
        self,
        collection_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        _ = warnings
        return self.workspace_service.get_workspace_overview(collection_id)

    def _safe_objectives(
        self,
        collection_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.research_objective_service.list_objective_workspaces(
                collection_id
            )
        except ResearchObjectivesNotReadyError:
            warnings.append("research_objectives_not_ready")
            return None

    def _safe_objective_research_view(
        self,
        collection_id: str,
        objective_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.research_objective_service.get_objective_research_view(
                collection_id,
                objective_id,
            )
        except ResearchObjectiveNotFoundError:
            warnings.append("focused_objective_not_found")
            return None
        except ResearchObjectivesNotReadyError:
            warnings.append("research_objectives_not_ready")
            return None

    def _safe_collection_research_view(
        self,
        collection_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.research_view_service.get_collection_research_view(
                collection_id
            )
        except ResearchViewNotReadyError:
            warnings.append("research_view_not_ready")
            return None

    def _safe_material_profile(
        self,
        collection_id: str,
        material_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.research_view_service.get_collection_material_research_view(
                collection_id,
                material_id,
            )
        except ResearchViewMaterialNotFoundError:
            warnings.append("focused_material_not_found")
            return None
        except ResearchViewNotReadyError:
            warnings.append("research_view_not_ready")
            return None

    def _safe_comparisons(
        self,
        collection_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.comparison_service.list_comparison_rows(collection_id, limit=10)
        except ComparisonRowsNotReadyError:
            warnings.append("comparison_rows_not_ready")
            return None

    def _safe_evidence_cards(
        self,
        collection_id: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        try:
            return self.paper_facts_service.list_evidence_cards(collection_id, limit=10)
        except PaperFactsNotReadyError:
            warnings.append("evidence_cards_not_ready")
            return None

    def _safe_curated_research_findings(
        self,
        collection_id: str,
        *,
        focused_goal_id: str | None,
        focused_objective_id: str | None,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        scope_type = "goal" if focused_goal_id else "objective"
        scope_id = focused_goal_id or focused_objective_id
        if not scope_id:
            return []
        try:
            dataset = self.research_understanding_feedback_service.export_dataset(
                collection_id=collection_id,
                scope_type=scope_type,
                scope_id=scope_id,
                dataset_use_status="training_ready",
            )
        except FileNotFoundError:
            warnings.append("curated_research_findings_not_ready")
            return []
        except ValueError as exc:
            warnings.append(f"curated_research_findings_invalid: {exc}")
            return []
        items = dataset.get("items") if isinstance(dataset, dict) else None
        if not isinstance(items, list):
            return []
        findings = [
            self._curated_research_finding_for_prompt(item)
            for item in items
            if isinstance(item, dict)
        ]
        return [finding for finding in findings if finding][:8]

    def _curated_research_finding_for_prompt(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        if item.get("dataset_use_status") != "training_ready":
            return {}
        target = item.get("expert_target")
        if not isinstance(target, dict):
            target = {}
        prediction = item.get("system_prediction")
        if not isinstance(prediction, dict):
            prediction = {}
        statement = _clean_text(target.get("statement")) or _clean_text(
            prediction.get("statement")
        )
        if not statement:
            return {}
        if not self._curated_research_finding_is_actionable(target, prediction):
            return {}
        evidence_refs = [
            self._curated_evidence_ref_for_prompt(ref)
            for ref in item.get("training_evidence_refs", [])
            if isinstance(ref, dict)
        ]
        return {
            "finding": statement,
            "label_status": _clean_text(item.get("label_status")),
            "dataset_use_status": "training_ready",
            "variables": self._stable_strings(
                target.get("variables") or prediction.get("variables")
            ),
            "mediators": self._stable_strings(
                target.get("mediators") or prediction.get("mediators")
            ),
            "outcomes": self._stable_strings(
                target.get("outcomes") or prediction.get("outcomes")
            ),
            "direction": _clean_text(
                target.get("direction") or prediction.get("direction")
            ),
            "scope_summary": _clean_text(
                target.get("scope_summary") or prediction.get("scope_summary")
            ),
            "support_grade": _clean_text(
                target.get("support_grade") or prediction.get("support_grade")
            ),
            "evidence": [ref for ref in evidence_refs if ref][:4],
        }

    def _curated_research_finding_is_actionable(
        self,
        target: dict[str, Any],
        prediction: dict[str, Any],
    ) -> bool:
        status = (
            _clean_text(target.get("status") or prediction.get("status")) or ""
        ).lower()
        support_grade = (
            _clean_text(target.get("support_grade") or prediction.get("support_grade"))
            or ""
        ).lower()
        if status in {"unsupported", "conflicted"}:
            return False
        if support_grade in {"insufficient", "conflict", "conflicted", "weak"}:
            return False
        return True

    def _curated_evidence_ref_for_prompt(self, ref: dict[str, Any]) -> dict[str, Any]:
        evidence_id = _clean_text(ref.get("evidence_ref_id") or ref.get("evidence_id"))
        if not evidence_id:
            return {}
        text = _clean_text(
            ref.get("training_source_text")
            or ref.get("quote")
            or ref.get("source_text")
            or ref.get("text")
        )
        return {
            "evidence_ref_id": evidence_id,
            "document_id": _clean_text(ref.get("document_id") or ref.get("paper_id")),
            "page": ref.get("page"),
            "source_kind": _clean_text(ref.get("source_kind")),
            "source_ref": _clean_text(ref.get("source_ref")),
            "quote": text[:700] if text else None,
        }

    def _generate_llm_answer(
        self,
        *,
        session: GoalSessionRecord,
        user_message: str,
        source_mode: SourceMode,
        context: dict[str, Any],
    ) -> str:
        system_prompt, prompt = self._build_prompt(
            session=session,
            user_message=user_message,
            source_mode=source_mode,
            context=context,
        )
        completion = self.llm_client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        content = completion.choices[0].message.content if completion.choices else None
        answer = self._strip_thinking_blocks(self._coerce_message_content(content))
        if not answer:
            raise RuntimeError("goal copilot returned empty answer")
        return answer

    def _try_generate_llm_answer(
        self,
        *,
        session: GoalSessionRecord,
        user_message: str,
        source_mode: SourceMode,
        context: dict[str, Any],
    ) -> tuple[str, str | None]:
        try:
            return (
                self._generate_llm_answer(
                    session=session,
                    user_message=user_message,
                    source_mode=source_mode,
                    context=context,
                ),
                None,
            )
        except OpenAIError:
            return (
                "The goal copilot model is currently unavailable, so Lens cannot "
                "draft a reliable answer from the collection in this turn. Review "
                "the findings and evidence directly, then retry after the model "
                "endpoint is available.",
                "goal_copilot_model_unavailable",
            )

    def _build_prompt(
        self,
        *,
        session: GoalSessionRecord,
        user_message: str,
        source_mode: SourceMode,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        if source_mode == "collection_grounded":
            source_rule = (
                "Answer only from the provided collection context. Cite source link "
                "labels such as [Source 1] when making collection-supported claims. "
                "When asked for experiments, protocols, or next-step research plans, "
                "use curated/training-ready findings first and say when expert-reviewed "
                "findings are insufficient for a decision. "
                "Do not paste raw document_id, paper_id, evidence_id, or other long "
                "internal ids into the answer. Do not invent sample ids, paper names, "
                "values, or source links."
            )
        elif source_mode == "general_fallback":
            source_rule = (
                "The collection context is empty or insufficient. Answer from general "
                "background knowledge only, and clearly state that it is not a "
                "collection-supported conclusion. Do not cite source links or evidence ids."
            )
        else:
            source_rule = (
                "Answer from general background knowledge only. Do not present the "
                "answer as a finding from the bound collection and do not cite source links "
                "or evidence ids."
            )
        system_prompt = (
            "You are Lens, a collection-bound research copilot. Preserve the "
            "boundary between collection evidence and general background. "
            f"{source_rule} Keep the answer concise and useful."
        )
        context_text = ""
        source_links_text = ""
        if context:
            context_text = json.dumps(
                context.get("prompt_payload", context.get("payload", context)),
                ensure_ascii=False,
                indent=2,
            )[:_MAX_CONTEXT_CHARS]
            source_links_text = json.dumps(
                context.get("prompt_source_links") or [],
                ensure_ascii=False,
                indent=2,
            )
        prompt = (
            f"Goal session:\n"
            f"- collection_id: {session.collection_id}\n"
            f"- focused_material_id: {session.focused_material_id}\n"
            f"- focused_paper_id: {session.focused_paper_id}\n"
            f"- focused_objective_id: {session.focused_objective_id}\n"
            f"- focused_goal_id: {session.focused_goal_id}\n"
            f"- goal_text: {session.goal_text}\n"
            f"- answer_mode: {session.answer_mode}\n"
            f"- rolling_summary: {session.rolling_summary}\n\n"
            f"User message:\n{user_message}\n\n"
            f"Source links:\n{source_links_text or '[]'}\n\n"
            f"Collection context:\n{context_text or '{}'}"
        )
        return system_prompt, prompt

    def _update_session_after_answer(
        self,
        session: GoalSessionRecord,
        *,
        user_message: str,
        assistant_message: GoalMessageRecord,
        context: dict[str, Any],
    ) -> GoalSessionRecord:
        return session.after_assistant_message(
            user_message=user_message,
            assistant_message=assistant_message,
            material_ids=context.get("material_ids"),
            paper_ids=context.get("paper_ids"),
            collection_data_version=self._collection_data_version(
                self.collection_service.get_collection(session.collection_id)
            ),
            updated_at=assistant_message.created_at,
            max_summary_chars=_MAX_ROLLING_SUMMARY_CHARS,
        )

    def _collection_data_version(self, collection: dict[str, Any]) -> str:
        collection_id = collection["collection_id"]
        artifacts = (
            self.collection_service.artifact_repository.read(collection_id) or {}
        )
        return str(
            artifacts.get("updated_at")
            or collection.get("updated_at")
            or collection.get("created_at")
            or ""
        )

    def _session_links(self, session: GoalSessionRecord) -> dict[str, str]:
        collection_id = session.collection_id
        links = {
            "workspace": f"/collections/{collection_id}",
            "objectives": f"/collections/{collection_id}/objectives",
            "materials": f"/collections/{collection_id}/materials",
            "comparisons": f"/collections/{collection_id}/comparisons",
            "evidence": f"/collections/{collection_id}/evidence",
        }
        objective_id = session.focused_objective_id
        if objective_id:
            links["focused_objective"] = (
                f"/collections/{collection_id}/objectives/{objective_id}"
            )
        material_id = session.focused_material_id
        if material_id:
            links["focused_material"] = (
                f"/collections/{collection_id}/materials/{material_id}"
            )
        return links

    def _document_href(self, collection_id: str, document_id: str) -> str:
        return (
            f"/collections/{quote(collection_id, safe='')}/documents/"
            f"{quote(document_id, safe='')}"
        )

    def _evidence_href(
        self,
        collection_id: str,
        *,
        evidence_id: str,
        document_id: str | None,
    ) -> str:
        if document_id:
            return (
                f"{self._document_href(collection_id, document_id)}"
                f"?evidence_id={quote(evidence_id, safe='')}"
            )
        return (
            f"/collections/{quote(collection_id, safe='')}/evidence"
            f"?evidence_id={quote(evidence_id, safe='')}"
        )

    def _build_source_refs(
        self,
        collection_id: str,
        *,
        evidence_sources: list[dict[str, str | None]],
        paper_ids: list[str],
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen_hrefs: set[str] = set()
        covered_documents: set[str] = set()

        for source in evidence_sources:
            evidence_id = _clean_text(source.get("evidence_id"))
            if not evidence_id:
                continue
            document_id = _clean_text(source.get("document_id"))
            href = self._evidence_href(
                collection_id,
                evidence_id=evidence_id,
                document_id=document_id,
            )
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            if document_id:
                covered_documents.add(document_id)
            refs.append(
                {
                    "kind": "evidence",
                    "label": f"Source {len(refs) + 1}",
                    "href": href,
                    "evidence_id": evidence_id,
                    "document_id": document_id or "",
                }
            )
            if len(refs) >= _MAX_SOURCE_LINKS:
                return refs

        for paper_id in paper_ids:
            if paper_id in covered_documents:
                continue
            href = self._document_href(collection_id, paper_id)
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            refs.append(
                {
                    "kind": "document",
                    "label": f"Source {len(refs) + 1}",
                    "href": href,
                    "document_id": paper_id,
                    "evidence_id": "",
                }
            )
            if len(refs) >= _MAX_SOURCE_LINKS:
                return refs
        return refs

    def _public_source_links(
        self, source_refs: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return [GoalSourceLink.from_mapping(ref).to_record() for ref in source_refs]

    def _prompt_source_links(
        self, source_refs: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return [
            {
                "kind": ref["kind"],
                "label": ref["label"],
            }
            for ref in source_refs
        ]

    def _read_session(self, session_id: str) -> dict[str, Any]:
        session = self.goal_session_repository.read_session(session_id)
        if not isinstance(session, dict):
            raise GoalSessionNotFoundError(session_id)
        return session

    def _write_session(self, session: dict[str, Any]) -> None:
        self.goal_session_repository.write_session(session)

    def _read_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.goal_session_repository.read_messages(session_id)

    def _write_messages(
        self,
        session: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        self.goal_session_repository.write_messages(session["session_id"], messages)

    def _collect_evidence_ids(self, value: Any) -> list[str]:
        found: list[str] = []
        for key, item in self._walk(value):
            if key in {"evidence_id", "evidence_ref_id"}:
                text = _clean_text(item)
                if text:
                    found.append(text)
            elif key in {
                "used_evidence_ids",
                "evidence_ids",
                "anchor_ids",
            } and isinstance(item, list):
                found.extend(text for text in (_clean_text(v) for v in item) if text)
        return self._stable_strings(found)

    def _collect_evidence_sources(self, value: Any) -> list[dict[str, str | None]]:
        found: list[dict[str, str | None]] = []

        def visit(item: Any, inherited_document_id: str | None = None) -> None:
            if isinstance(item, dict):
                document_id = (
                    _clean_text(item.get("document_id") or item.get("paper_id"))
                    or inherited_document_id
                )
                evidence_id = _clean_text(
                    item.get("evidence_id") or item.get("evidence_ref_id")
                )
                if evidence_id:
                    found.append(
                        {
                            "evidence_id": evidence_id,
                            "document_id": document_id,
                        }
                    )
                evidence_ids = (
                    item.get("used_evidence_ids")
                    or item.get("evidence_ids")
                    or item.get("anchor_ids")
                )
                if isinstance(evidence_ids, list):
                    for evidence_value in evidence_ids:
                        nested_evidence_id = _clean_text(evidence_value)
                        if nested_evidence_id:
                            found.append(
                                {
                                    "evidence_id": nested_evidence_id,
                                    "document_id": document_id,
                                }
                            )
                for nested in item.values():
                    visit(nested, document_id)
            elif isinstance(item, list):
                for nested in item:
                    visit(nested, inherited_document_id)

        visit(value)
        unique: list[dict[str, str | None]] = []
        seen: set[tuple[str, str | None]] = set()
        for source in found:
            evidence_id = _clean_text(source.get("evidence_id"))
            if not evidence_id:
                continue
            document_id = _clean_text(source.get("document_id"))
            key = (evidence_id, document_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append({"evidence_id": evidence_id, "document_id": document_id})
        return unique

    def _collect_material_ids(self, value: Any) -> list[str]:
        return self._collect_ids(value, {"material_id"})

    def _collect_paper_ids(self, value: Any) -> list[str]:
        return self._collect_ids(value, {"paper_id", "document_id"})

    def _collect_ids(self, value: Any, keys: set[str]) -> list[str]:
        found: list[str] = []
        for key, item in self._walk(value):
            if key in keys:
                text = _clean_text(item)
                if text:
                    found.append(text)
        return self._stable_strings(found)

    def _walk(self, value: Any) -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = []
        if isinstance(value, dict):
            for key, item in value.items():
                items.append((str(key), item))
                items.extend(self._walk(item))
        elif isinstance(value, list):
            for item in value:
                items.extend(self._walk(item))
        return items

    def _has_non_empty_path(self, value: Any, path: tuple[str, ...]) -> bool:
        current = value
        for key in path:
            if not isinstance(current, dict):
                return False
            current = current.get(key)
        return bool(current)

    def _compact_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 5:
            return None
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 30:
                    compact["_truncated"] = True
                    break
                compact[str(key)] = self._compact_value(item, depth=depth + 1)
            return compact
        if isinstance(value, list):
            return [self._compact_value(item, depth=depth + 1) for item in value[:12]]
        if isinstance(value, str):
            return value[:900]
        return value

    def _prompt_payload(self, value: Any, source_refs: list[dict[str, str]]) -> Any:
        compact = self._compact_value(value)
        evidence_labels = {
            ref["evidence_id"]: ref["label"]
            for ref in source_refs
            if ref.get("evidence_id")
        }
        document_labels = {
            ref["document_id"]: ref["label"]
            for ref in source_refs
            if ref.get("document_id")
        }
        return self._replace_internal_source_ids(
            compact,
            evidence_labels=evidence_labels,
            document_labels=document_labels,
        )

    def _replace_internal_source_ids(
        self,
        value: Any,
        *,
        evidence_labels: dict[str, str],
        document_labels: dict[str, str],
    ) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text in {"document_id", "paper_id"}:
                    label = document_labels.get(str(item or ""))
                    if label:
                        cleaned["document_source"] = label
                    continue
                if key_text in {"evidence_id", "evidence_ref_id"}:
                    label = evidence_labels.get(str(item or ""))
                    if label:
                        cleaned["evidence_source"] = label
                    continue
                if key_text in {"used_evidence_ids", "evidence_ids", "anchor_ids"}:
                    if isinstance(item, list):
                        labels = [
                            evidence_labels.get(str(entry or ""))
                            for entry in item
                            if evidence_labels.get(str(entry or ""))
                        ]
                        if labels:
                            cleaned["evidence_sources"] = self._stable_strings(labels)
                    continue
                cleaned[key_text] = self._replace_internal_source_ids(
                    item,
                    evidence_labels=evidence_labels,
                    document_labels=document_labels,
                )
            return cleaned
        if isinstance(value, list):
            return [
                self._replace_internal_source_ids(
                    item,
                    evidence_labels=evidence_labels,
                    document_labels=document_labels,
                )
                for item in value
            ]
        return value

    def _stable_strings(self, values: Any) -> list[str]:
        result: list[str] = []
        if not isinstance(values, list):
            return result
        for value in values:
            text = _clean_text(value)
            if text and text not in result:
                result.append(text)
        return result

    def _coerce_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return str(content or "").strip()
        parts: list[str] = []
        for item in content:
            text = item if isinstance(item, str) else getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()

    def _strip_thinking_blocks(self, answer: str) -> str:
        return _THINK_BLOCK_RE.sub("", answer).strip()

    def _answer_cites_source_link(
        self,
        answer: str,
        source_links: list[dict[str, str]],
    ) -> bool:
        for link in source_links:
            label = _clean_text(link.get("label"))
            if not label:
                continue
            pattern = rf"(?<![A-Za-z0-9])\[?\s*{re.escape(label)}\s*\]?(?![A-Za-z0-9])"
            if re.search(pattern, answer, flags=re.IGNORECASE):
                return True
        return False

    def _ensure_general_fallback_boundary(self, answer: str) -> str:
        if "not a collection-supported conclusion" in answer.lower():
            return answer
        if (
            "current collection" in answer.lower()
            and "general background" in answer.lower()
        ):
            return answer
        return f"{_GENERAL_FALLBACK_PREFIX}{answer.strip()}"

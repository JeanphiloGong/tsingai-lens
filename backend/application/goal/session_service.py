from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from application.evaluation.finding_feedback_service import (
    FindingFeedbackService,
)
from application.goal.protocol_contract import (
    has_affirmative_ved_only_effect_claim,
    proposed_design_choice_has_unsupported_detail,
    proposed_design_choices_are_source_independent,
    ved_design_is_scientifically_consistent,
)
from application.source.collection_service import CollectionService
from domain.goal import (
    GoalAnswerMode,
    GoalMessageRecord,
    GoalSessionRecord,
    GoalSourceLink,
    GoalSourceMode,
)
from domain.ports import GoalSessionRepository

AnswerMode = GoalAnswerMode
SourceMode = GoalSourceMode
_MAX_CONTEXT_CHARS = 18000
_MAX_ROLLING_SUMMARY_CHARS = 1600
_MAX_SOURCE_LINKS = 12
_THINK_BLOCK_RE = re.compile(
    r"<think\b[^>]*>.*?</think\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)
_UNSET = object()
REVIEWED_FINDING_GATE = "reviewed_findings"


class _StructuredProtocolDraft(BaseModel):
    proposed_variable_manipulations: list[str] = Field(
        min_length=1,
        max_length=12,
        description=(
            "One plain design action per list item. Do not include category labels, "
            "citations, source facts, or multiple actions in one string."
        ),
    )
    design_risks: list[str] = Field(
        min_length=1,
        max_length=12,
        description=(
            "One plain design risk per list item. Do not repeat evidence limits or "
            "include category labels. Do not claim that changing a VED constituent "
            "isolates a universal VED-only effect or propose confirming such an effect."
        ),
    )


class _ProtocolContractError(RuntimeError):
    """Raised when a generated protocol cannot satisfy the review contract."""


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
        collection_service: CollectionService,
        finding_feedback_service: FindingFeedbackService,
        goal_session_repository: GoalSessionRepository,
        llm_client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service
        self.goal_session_repository = goal_session_repository
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
            )
        if focused_paper_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=focused_paper_id,
                focused_objective_id=session.focused_objective_id,
            )
        if focused_objective_id is not _UNSET:
            session = session.with_focus(
                focused_material_id=session.focused_material_id,
                focused_paper_id=session.focused_paper_id,
                focused_objective_id=focused_objective_id,
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
            "items": [
                self._with_message_source_validity(session, message)
                for message in self._read_messages(session.session_id)
            ],
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
        return self._with_message_source_validity(session, response, revalidate=False)

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

        if mode != "general" and not has_collection_context:
            source_mode: SourceMode = "collection_limited"
            answer = (
                "The selected research objective does not currently have expert-reviewed "
                "Findings with auditable Evidence. Review a Finding before asking Lens "
                "to use it for research conclusions or experiment planning."
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
            elif (
                context.get("review_gate") == REVIEWED_FINDING_GATE
                and self._is_protocol_draft(answer)
                and not self._protocol_contract_is_valid(answer)
            ):
                source_mode = "collection_limited"
                warnings.append("goal_copilot_protocol_contract_invalid")
                answer = (
                    "Lens could not verify the protocol draft contract, so do not "
                    "save or use this answer as an expert-ready experiment plan.\n\n"
                    f"{answer}"
                )
                used_evidence_ids = []
                source_links = []
            elif not source_links or not self._answer_cites_source_link(
                answer, source_links
            ):
                source_mode = "collection_limited"
                warnings.append("goal_copilot_missing_source_citation")
                answer = (
                    "Lens could not verify source citations in the generated answer, "
                    "so do not treat it as a traceable collection conclusion. Review "
                    "the published findings and evidence directly, then retry."
                )
                used_evidence_ids = []
                source_links = []
        assistant_message = GoalMessageRecord.assistant(
            message_id=f"msg_{uuid4().hex[:12]}",
            session_id=session.session_id,
            content=answer,
            source_mode=source_mode,
            used_evidence_ids=used_evidence_ids,
            warnings=warnings,
            links=links,
            source_links=source_links,
            review_gate=(
                REVIEWED_FINDING_GATE
                if source_mode == "collection_grounded"
                and context.get("review_gate") == REVIEWED_FINDING_GATE
                else None
            ),
            source_finding_refs=context.get("source_finding_refs"),
            source_validity=(
                "current"
                if source_mode == "collection_grounded"
                and context.get("review_gate") == REVIEWED_FINDING_GATE
                else None
            ),
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
        return session.with_page_context(
            material_id=material_id,
            paper_id=paper_id,
            objective_id=objective_id,
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
            )
            return (
                session,
                f"Focused objective updated to {session.focused_objective_id or 'none'}.",
            )
        if command == "goal":
            return session.with_goal_text(argument), "Goal updated."
        if command == "clear" and argument == "focus":
            return (
                session.with_focus(
                    focused_material_id=None,
                    focused_paper_id=None,
                    focused_objective_id=None,
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
        focused_material_id = session.focused_material_id
        focused_objective_id = session.focused_objective_id
        reviewed_findings = self._safe_reviewed_findings(
            collection_id,
            focused_objective_id=focused_objective_id,
            warnings=warnings,
        )
        if not focused_objective_id:
            warnings.append("focused_objective_required")
        elif not reviewed_findings:
            warnings.append("reviewed_findings_empty")

        source_context_payload = {
            "collection": collection,
            "focused_material_id": focused_material_id,
            "focused_paper_id": session.focused_paper_id,
            "focused_objective_id": focused_objective_id,
        }
        if reviewed_findings:
            source_context_payload["reviewed_findings"] = reviewed_findings
        evidence_ids = self._collect_evidence_ids(source_context_payload)
        material_ids = self._collect_material_ids(source_context_payload)
        paper_ids = self._collect_paper_ids(source_context_payload)
        source_refs = self._build_source_refs(
            collection_id,
            evidence_sources=self._collect_evidence_sources(source_context_payload),
            paper_ids=paper_ids,
        )
        has_collection_context = bool(reviewed_findings and evidence_ids)
        return {
            "has_collection_context": has_collection_context,
            "warnings": warnings,
            "evidence_ids": evidence_ids,
            "material_ids": material_ids,
            "paper_ids": paper_ids,
            "links": self._session_links(session),
            "source_links": self._public_source_links(source_refs),
            "source_refs": source_refs,
            "review_gate": (REVIEWED_FINDING_GATE if reviewed_findings else None),
            "source_finding_refs": self._source_finding_refs(
                reviewed_findings,
                objective_id=focused_objective_id,
            ),
            "payload": self._compact_value(source_context_payload),
            "prompt_source_links": self._prompt_source_links(source_refs),
            "prompt_payload": self._prompt_payload(source_context_payload, source_refs),
        }

    def _safe_reviewed_findings(
        self,
        collection_id: str,
        *,
        focused_objective_id: str | None,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if not focused_objective_id:
            return []
        try:
            dataset = self.finding_feedback_service.export_dataset(
                collection_id=collection_id,
                objective_id=focused_objective_id,
                dataset_use_status="training_ready",
            )
        except FileNotFoundError:
            warnings.append("reviewed_findings_not_ready")
            return []
        except ValueError as exc:
            warnings.append(f"reviewed_findings_invalid: {exc}")
            return []
        items = dataset.get("items") if isinstance(dataset, dict) else None
        if not isinstance(items, list):
            return []
        findings: list[dict[str, Any]] = []
        omitted = False
        for item in items:
            if not isinstance(item, dict):
                continue
            finding = self._reviewed_finding_for_prompt(item)
            if not finding:
                continue
            candidate = [*findings, finding]
            encoded = json.dumps(
                {"reviewed_findings": candidate},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(encoded) > _MAX_CONTEXT_CHARS:
                omitted = True
                continue
            findings.append(finding)
        if omitted:
            warnings.append("reviewed_findings_context_limited")
        return findings

    def _reviewed_finding_for_prompt(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        if item.get("dataset_use_status") != "training_ready":
            return {}
        finding_id = _clean_text(item.get("finding_id"))
        try:
            analysis_version = int(item.get("analysis_version") or 0)
        except (TypeError, ValueError):
            analysis_version = 0
        finding_fingerprint = _clean_text(item.get("finding_fingerprint"))
        evidence_fingerprint = _clean_text(item.get("evidence_fingerprint"))
        if (
            not finding_id
            or analysis_version < 1
            or not finding_fingerprint
            or not evidence_fingerprint
        ):
            return {}
        target = item.get("training_target")
        if not isinstance(target, dict):
            return {}
        statement = _clean_text(target.get("statement"))
        if not statement:
            return {}
        evidence_refs = [
            self._reviewed_evidence_for_prompt(ref)
            for ref in item.get("evidence", [])
            if isinstance(ref, dict)
        ]
        if not self._reviewed_finding_is_actionable(
            target,
            evidence_refs=evidence_refs,
        ):
            return {}
        return {
            "finding_id": finding_id,
            "analysis_version": analysis_version,
            "finding_fingerprint": finding_fingerprint,
            "evidence_fingerprint": evidence_fingerprint,
            "statement": statement,
            "label_status": _clean_text(item.get("label_status")),
            "dataset_use_status": "training_ready",
            "factors": self._stable_strings(target.get("factors")),
            "outcome": _clean_text(target.get("outcome")),
            "direction": _clean_text(target.get("direction")),
            "assertion_strength": _clean_text(target.get("assertion_strength")),
            "attribution_scope": _clean_text(target.get("attribution_scope")),
            "synthesis_status": _clean_text(target.get("synthesis_status")),
            "certainty": target.get("certainty"),
            "mechanisms": target.get("mechanisms") or [],
            "scientific_context": target.get("scientific_context") or {},
            "limitations": self._stable_strings(target.get("limitations")),
            "paper_contributions": target.get("paper_contributions") or [],
            "evidence": [ref for ref in evidence_refs if ref],
        }

    def _source_finding_refs(
        self,
        findings: list[dict[str, Any]],
        *,
        objective_id: str | None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "objective_id": objective_id,
                "finding_id": finding["finding_id"],
                "analysis_version": finding["analysis_version"],
                "finding_fingerprint": finding["finding_fingerprint"],
                "evidence_fingerprint": finding["evidence_fingerprint"],
                "evidence_ids": self._stable_strings(
                    [
                        ref.get("evidence_id")
                        for ref in finding.get("evidence", [])
                        if isinstance(ref, dict)
                    ]
                ),
            }
            for finding in findings
        ]

    def _reviewed_finding_is_actionable(
        self,
        target: dict[str, Any],
        *,
        evidence_refs: list[dict[str, Any]],
    ) -> bool:
        factors = self._stable_strings(target.get("factors"))
        outcome = _clean_text(target.get("outcome"))
        supporting_ids = {
            evidence_id
            for contribution in target.get("paper_contributions", [])
            if isinstance(contribution, dict)
            for evidence_id in self._stable_strings(
                contribution.get("supporting_evidence_ids")
            )
        }
        available_ids = {
            ref.get("evidence_id")
            for ref in evidence_refs
            if ref.get("evidence_id") and ref.get("source_excerpt")
        }
        return (
            bool(factors)
            and bool(outcome)
            and bool(_clean_text(target.get("direction")))
            and bool(supporting_ids)
            and supporting_ids <= available_ids
        )

    def _reviewed_evidence_for_prompt(self, ref: dict[str, Any]) -> dict[str, Any]:
        evidence_id = _clean_text(ref.get("evidence_id"))
        if not evidence_id:
            return {}
        text = _clean_text(ref.get("source_excerpt"))
        if not text:
            return {}
        return {
            "evidence_id": evidence_id,
            "document_id": _clean_text(ref.get("document_id")),
            "page_numbers": ref.get("page_numbers") or [],
            "source_kind": _clean_text(ref.get("source_kind")),
            "source_ref": _clean_text(ref.get("source_ref")),
            "evidence_role": _clean_text(ref.get("evidence_role")),
            "changed_variables": ref.get("changed_variables") or [],
            "reported_result": ref.get("reported_result"),
            "attribution_scope": _clean_text(ref.get("attribution_scope")),
            "scientific_context": ref.get("scientific_context") or {},
            "source_excerpt": text,
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
        answer = self._complete_llm_prompt(system_prompt, prompt)
        if (
            source_mode == "collection_grounded"
            and context.get("review_gate") == REVIEWED_FINDING_GATE
            and self._is_protocol_draft(answer)
        ):
            answer = self._repair_protocol_answer(
                system_prompt=system_prompt,
                prompt=prompt,
                answer=answer,
                allowed_source_labels={
                    str(link.get("label") or "").strip()
                    for link in context.get("prompt_source_links") or []
                    if str(link.get("label") or "").strip()
                },
                reviewed_findings=(
                    context.get("prompt_payload", {}).get(
                        "reviewed_findings",
                        [],
                    )
                    if isinstance(context.get("prompt_payload"), dict)
                    else []
                ),
            )
        return answer

    def _complete_llm_prompt(self, system_prompt: str, prompt: str) -> str:
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

    def _repair_protocol_answer(
        self,
        *,
        system_prompt: str,
        prompt: str,
        answer: str,
        allowed_source_labels: set[str],
        reviewed_findings: list[dict[str, Any]],
    ) -> str:
        repair_prompt = (
            f"{prompt}\n\n"
            "Repair the protocol as structured data. Return only proposed variable "
            "manipulations and design risks. Lens derives measurements and controls "
            "deterministically from the curated Findings and variable matrix. "
            "Do not generate or restate source-backed facts; Lens derives those directly "
            "from the curated Findings. Proposed items must not invent numeric settings, "
            "sample counts, standards, or named methods. Do not copy source numbers, "
            "material identifiers, equipment names, or method acronyms into proposed "
            "items; Lens renders supported observations separately. A VED design may estimate a "
            "selected constituent-mediated path, but must not claim to isolate a "
            "universal VED-only effect or propose confirming one.\n"
            "Normalize the protocol into the required evidence/design fields."
            f"\n\nPrevious draft:\n<draft>\n{answer}\n</draft>"
        )
        try:
            completion = self.llm_client.beta.chat.completions.parse(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": repair_prompt},
                ],
                response_format=_StructuredProtocolDraft,
            )
            parsed = (
                completion.choices[0].message.parsed if completion.choices else None
            )
            draft = _StructuredProtocolDraft.model_validate(parsed)
            return self._render_protocol_draft(
                draft,
                allowed_source_labels=allowed_source_labels,
                reviewed_findings=reviewed_findings,
            )
        except Exception as exc:
            raise _ProtocolContractError(
                "goal copilot protocol repair failed validation"
            ) from exc

    def _render_protocol_draft(
        self,
        draft: _StructuredProtocolDraft,
        *,
        allowed_source_labels: set[str],
        reviewed_findings: list[dict[str, Any]],
    ) -> str:
        grounding = self._protocol_grounding(
            reviewed_findings,
            allowed_source_labels=allowed_source_labels,
        )
        ved_grounding = any(
            re.search(
                r"\bVED\b|volumetric\s+energy\s+density",
                item,
                flags=re.IGNORECASE,
            )
            for item in grounding["variable_observations"]
        )
        variable_items = [
            f"- Source-backed: {item}" for item in grounding["variable_observations"]
        ]
        proposed_variables: list[str] = []
        for item in draft.proposed_variable_manipulations:
            try:
                proposed_variables.append(self._proposed_protocol_text(item))
            except ValueError:
                continue
        if ved_grounding:
            candidate = "\n".join(
                [
                    "Variable matrix:",
                    *proposed_variables,
                    "Measurements:",
                    "Controls:",
                    "Risks or limits:",
                ]
            )
            if not proposed_variables or not ved_design_is_scientifically_consistent(
                candidate
            ):
                proposed_variables = [
                    "Vary laser power to create VED levels while holding scan speed, "
                    "hatch spacing, and layer thickness fixed; the expert selects "
                    "the levels."
                ]
        elif not proposed_variables:
            raise ValueError("protocol has no valid proposed variable manipulation")
        variable_items.extend(
            f"- Proposed design choice: {item}" for item in proposed_variables
        )
        measurement_items = [
            f"- Source-backed: {item}" for item in grounding["reported_outcomes"]
        ]
        measurement_items.append(
            "- Proposed design choice: The expert selects validated methods for "
            "the source-backed outcomes."
        )
        control_items = []
        if ved_grounding:
            control_items.append(
                "- Proposed design choice: Keep the VED constituents identified as "
                "fixed in the Variable matrix unchanged across conditions."
            )
        control_items.append(
            "- Proposed design choice: The expert defines controls for "
            "non-manipulated material, process, and test variables."
        )
        evidence_limits = [
            f"- Evidence limit: {item}" for item in grounding["evidence_limits"]
        ]
        design_risks = []
        for item in draft.design_risks:
            text = self._clean_protocol_text(item)
            if any(
                marker in text.lower()
                for marker in ("paper-level", "cross-paper", "generalization")
            ):
                continue
            if has_affirmative_ved_only_effect_claim(text):
                continue
            design_risks.append(f"- Design risk: {text}")
        if ved_grounding and not any(
            "does not isolate" in item.lower() for item in design_risks
        ):
            design_risks.append(
                "- Design risk: Changing one or more VED constituents estimates "
                "the selected constituent-mediated path; it does not isolate a "
                "universal VED-only effect."
            )
        if not design_risks:
            design_risks.append(
                "- Design risk: The proposed choices require expert validation for "
                "uncontrolled variables."
            )
        return "\n\n".join(
            [
                "**Hypothesis**\n" + "\n".join(grounding["hypotheses"]),
                "**Variable matrix**\n" + "\n".join(variable_items),
                "**Measurements**\n" + "\n".join(measurement_items),
                "**Controls**\n" + "\n".join(control_items),
                "**Risks or limits**\n" + "\n".join(evidence_limits + design_risks),
            ]
        )

    def _protocol_grounding(
        self,
        reviewed_findings: list[dict[str, Any]],
        *,
        allowed_source_labels: set[str],
    ) -> dict[str, list[str]]:
        hypotheses: list[str] = []
        variable_observations: list[str] = []
        reported_outcomes: list[str] = []
        evidence_limits: list[str] = []
        for finding in reviewed_findings:
            if not isinstance(finding, dict):
                continue
            statement = _clean_text(finding.get("statement"))
            evidence = finding.get("evidence")
            labels = self._stable_strings(
                [
                    ref.get("evidence_source")
                    for ref in evidence or []
                    if isinstance(ref, dict) and ref.get("evidence_source")
                ]
            )
            if not statement or not labels:
                continue
            unknown_labels = set(labels) - allowed_source_labels
            if unknown_labels:
                raise ValueError(
                    f"unknown protocol source labels: {sorted(unknown_labels)}"
                )
            citations = "".join(f"[{label}]" for label in labels)
            hypotheses.append(f"{self._clean_protocol_text(statement)} {citations}")

            factors = self._stable_strings(finding.get("factors"))
            outcome = _clean_text(finding.get("outcome"))
            direction = _clean_text(finding.get("direction"))
            attribution_scope = _clean_text(finding.get("attribution_scope"))
            relation = f"Observed relation: {', '.join(factors)} -> {outcome}"
            mechanisms = [
                (
                    f"{item.get('source_term')} {item.get('relation_type')} "
                    f"{item.get('target_term')}"
                ).strip()
                for item in finding.get("mechanisms", [])
                if isinstance(item, dict)
            ]
            mechanisms = [item for item in mechanisms if item]
            if mechanisms:
                relation += f"; mechanisms: {', '.join(mechanisms)}"
            if direction and direction.lower() not in {
                "compares",
                "comparison",
                "mixed",
                "unknown",
                "unspecified",
            }:
                relation += f"; direction: {direction}"
            if attribution_scope:
                relation += f"; attribution: {attribution_scope}"
            variable_observations.append(f"{relation}. {citations}")

            reported_outcomes.append(f"Reported outcome: {outcome}. {citations}")
            limits = self._stable_strings(finding.get("limitations"))
            synthesis_status = _clean_text(finding.get("synthesis_status"))
            if synthesis_status == "insufficient_confirmation" and not any(
                "one paper" in limit.lower() or "single-paper" in limit.lower()
                for limit in limits
            ):
                limits.append(
                    "Only one independent paper directly supports this Finding."
                )
            elif synthesis_status in {"conflict", "condition_dependent"}:
                limits.append(f"Cross-paper synthesis status: {synthesis_status}.")
            for limit in limits:
                cleaned = self._clean_protocol_text(limit)
                if cleaned and cleaned not in evidence_limits:
                    evidence_limits.append(cleaned)

        if not hypotheses or not variable_observations or not reported_outcomes:
            raise ValueError("reviewed Finding grounding is incomplete")
        if not evidence_limits:
            evidence_limits.append(
                "The reviewed Findings do not define a cross-paper generalization boundary."
            )
        return {
            "hypotheses": hypotheses,
            "variable_observations": variable_observations,
            "reported_outcomes": reported_outcomes,
            "evidence_limits": evidence_limits,
        }

    def _proposed_protocol_text(self, value: str) -> str:
        raw_text = " ".join(str(value or "").split()).strip()
        text = self._clean_protocol_text(raw_text)
        if re.search(
            r"(?:Source-backed|Proposed design choice|Evidence limit|Design risk)\s*:",
            text,
            flags=re.IGNORECASE,
        ):
            raise ValueError(
                "proposed protocol item contains an embedded category label"
            )
        if proposed_design_choice_has_unsupported_detail(text):
            raise ValueError("proposed protocol item contains an unsupported detail")
        return text

    def _clean_protocol_text(self, value: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            raise ValueError("protocol item text is required")
        text = re.sub(r"\[\s*Source\s+\d+\s*\]", "", text, flags=re.IGNORECASE)
        return re.sub(
            r"^(?:Source-backed|Proposed design choice|Evidence limit|Design risk)\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    def _protocol_contract_is_valid(self, answer: str) -> bool:
        required_headings = (
            "**Hypothesis**",
            "**Variable matrix**",
            "**Measurements**",
            "**Controls**",
            "**Risks or limits**",
        )
        if not all(heading in answer for heading in required_headings):
            return False
        source_pattern = re.compile(r"\[\s*Source\s+\d+\s*\]", re.IGNORECASE)
        source_lines = [
            line for line in answer.splitlines() if line.startswith("- Source-backed:")
        ]
        if not source_lines or any(
            not source_pattern.search(line) for line in source_lines
        ):
            return False
        hypothesis = answer.split("**Variable matrix**", 1)[0]
        if not source_pattern.search(hypothesis):
            return False
        category_pattern = re.compile(
            r"(?:Source-backed|Proposed design choice|Evidence limit|Design risk)\s*:",
            re.IGNORECASE,
        )
        for line in answer.splitlines():
            if not line.startswith("- Proposed design choice:"):
                continue
            item = line.split(":", 1)[1]
            if category_pattern.search(item):
                return False
        return proposed_design_choices_are_source_independent(
            answer
        ) and ved_design_is_scientifically_consistent(answer)

    def _is_protocol_draft(self, answer: str) -> bool:
        normalized = answer.lower()
        required_labels = (
            "hypothesis",
            "variable matrix",
            "measurements",
            "controls",
            "risks or limits",
        )
        return sum(label in normalized for label in required_labels) >= 4

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
        except _ProtocolContractError:
            return (
                "Lens could not verify the protocol draft contract. Review the "
                "reviewed findings and source evidence directly, then retry.",
                "goal_copilot_protocol_contract_invalid",
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
                "use expert-reviewed findings first and say when reviewed evidence is "
                "insufficient for a decision. Protocol draft requirements: "
                "write a structured protocol draft with these exact section labels: "
                "Hypothesis, Variable matrix, Measurements, Controls, and Risks or limits. "
                "For every independent variable, describe its operational manipulation "
                "in Variable matrix. If a proposed factor is a derived or composite variable, "
                "such as volumetric energy density derived from laser power, scan speed, "
                "hatch spacing, and layer thickness, identify which constituent parameters "
                "change and which remain fixed. Never say that a derived variable changes "
                "while every constituent parameter is fixed. If the cited evidence changes "
                "multiple constituent parameters, label it as a confounded comparison and "
                "propose a constituent-controlled or factorial validation. Changing one "
                "constituent estimates that constituent-mediated path; never call it an "
                "isolated or universal VED-only effect, and never make confirmation of a "
                "VED-only effect the validation target. Separate source-backed "
                "observations from protocol choices, and mark uncited variable "
                "manipulations as a proposed design choice. Lens derives Measurements "
                "from source-backed outcomes and Controls from the variable matrix plus "
                "expert-selection placeholders; do not invent measurement methods or "
                "control variables. In Variable matrix, Measurements, and "
                "Controls, prefix every bullet with exactly 'Source-backed:' and include "
                "exact bracket citations such as [Source 1], or prefix it with exactly "
                "'Proposed design choice:'. Do not leave these bullets unlabeled. For "
                "each item. A Source-backed line must include one or more exact bracket "
                "citations on that same line. Do not use Source-backed as a group heading. "
                "The Hypothesis must cite every evidence-backed direction with source "
                "labels. Only call an operational setting Source-backed when a provided "
                "evidence quote explicitly states that setting; general domain knowledge "
                "or this boundary example is not source evidence. For "
                "Risks or limits, distinguish 'Evidence limit:' from 'Design risk:'. Do "
                "not invent numeric levels, standards, sample sizes, or named methods; "
                "when they are not source-backed, say that the expert must select or "
                "confirm them. Never put source numbers, material identifiers, equipment "
                "names, or method acronyms in a Proposed design choice; source facts belong "
                "only in Source-backed lines. Boundary example: Bad: change VED while laser power, scan "
                "speed, hatch spacing, and layer thickness are fixed. Good: Proposed "
                "design choice: vary laser power to create VED levels, hold scan speed, "
                "hatch spacing, and layer thickness fixed, and have the expert select "
                "the levels. "
                "Do not collapse protocol answers into one paragraph. Attach source labels "
                "to each evidence-backed recommendation. "
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
            )
            if context.get("review_gate") != REVIEWED_FINDING_GATE:
                context_text = context_text[:_MAX_CONTEXT_CHARS]
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
        return str(collection.get("updated_at") or collection.get("created_at") or "")

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

    def _with_message_source_validity(
        self,
        session: GoalSessionRecord,
        message: dict[str, Any],
        *,
        revalidate: bool = True,
    ) -> dict[str, Any]:
        payload = dict(message)
        source_findings = tuple(
            item
            for item in payload.get("source_finding_refs", [])
            if isinstance(item, dict)
        )
        if payload.get("role") != "assistant" or not source_findings:
            payload["source_validity"] = None
            payload["source_validity_reasons"] = []
            return payload
        if not revalidate:
            validity, reasons = "current", []
        else:
            objective_ids = self._stable_strings(
                [item.get("objective_id") for item in source_findings]
            )
            if len(objective_ids) != 1:
                validity, reasons = "stale", ["source_objective_identity_invalid"]
            else:
                validity, reasons = (
                    self.finding_feedback_service.source_snapshot_validity(
                        collection_id=session.collection_id,
                        objective_id=objective_ids[0],
                        source_findings=source_findings,
                    )
                )
        payload["source_validity"] = validity
        payload["source_validity_reasons"] = reasons
        if validity == "stale":
            payload["source_mode"] = "collection_limited"
            payload["review_gate"] = None
            payload["warnings"] = self._stable_strings(
                [*payload.get("warnings", []), "source_finding_snapshot_stale"]
            )
        return payload

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
        compact = (
            value
            if isinstance(value, dict) and value.get("reviewed_findings")
            else self._compact_value(value)
        )
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
                if key_text in {
                    "used_evidence_ids",
                    "evidence_ids",
                    "anchor_ids",
                } or key_text.endswith("_evidence_ids"):
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
        cleaned = _THINK_BLOCK_RE.sub("", answer)
        closing_tags = list(_THINK_CLOSE_RE.finditer(cleaned))
        if closing_tags:
            cleaned = cleaned[closing_tags[-1].end() :]
        opening_tag = _THINK_OPEN_RE.search(cleaned)
        if opening_tag:
            cleaned = cleaned[: opening_tag.start()]
        return cleaned.strip()

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

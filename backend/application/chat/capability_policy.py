"""Capability availability, prerequisites, and exact approval boundaries.

These decisions inspect the current request and trajectory. They do not call
the model, execute capabilities, or persist messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from application.chat import intent_policy
from application.chat.capabilities import AgentContext, CapabilityRegistry
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)


@dataclass(frozen=True)
class AuthorizationDecision:
    may_execute: bool
    requires_approval: bool = False


def evaluate_authorization(risk: ToolRisk | str) -> AuthorizationDecision:
    normalized = ToolRisk(risk)
    if normalized in {ToolRisk.READ, ToolRisk.DRAFT}:
        return AuthorizationDecision(may_execute=True)
    if normalized is ToolRisk.WRITE:
        return AuthorizationDecision(may_execute=False, requires_approval=True)
    return AuthorizationDecision(may_execute=False)



def validate_batch(
    capabilities: CapabilityRegistry,
    requested,
    messages,
) -> tuple[tuple[str, str] | None, dict[str, BaseModel]]:
    successful_results = active_successful_results_by_name(messages)
    validated_arguments: dict[str, BaseModel] = {}
    for call, handler in requested:
        if handler is None:
            code = "capability_unavailable_for_turn" if capabilities.get(call.name) else "unknown_capability"
            return (
                (code, "The requested research capability is not available."),
                validated_arguments,
            )
        if call.risk is ToolRisk.UNKNOWN:
            return (
                ("capability_not_authorized", "The research capability is not authorized."),
                validated_arguments,
            )
        try:
            validated_arguments[call.tool_call_id] = (
                handler.spec.input_model.model_validate(call.arguments)
            )
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'arguments'} ({error['type']})"
                for error in exc.errors(include_input=False, include_url=False)[:8]
            )
            return (
                (
                    "invalid_tool_arguments",
                    f"Invalid research capability arguments: {details}.",
                ),
                validated_arguments,
            )
        if call.name == "inspect_published_finding":
            allowed = _published_finding_candidates(successful_results)
            finding = (str(call.arguments.get("objective_id") or "").strip(), str(call.arguments.get("finding_id") or "").strip())
            if allowed and finding not in allowed:
                return (
                    (
                        "finding_reference_not_in_query",
                        "Inspect a Finding identifier returned by the preceding query.",
                    ),
                    validated_arguments,
                )
        if call.name == "revise_research_plan":
            inspected_plans = {
                (str(result.get("objective_id") or ""), str(plan.get("plan_id") or ""))
                for result in successful_results.get("inspect_research_plans", ())
                for plan in ([result["plan"]] if result.get("plan") else result.get("plans", ()))
                if isinstance(plan, Mapping)
            }
            parent = (
                str(call.arguments.get("objective_id") or ""),
                str(call.arguments.get("parent_plan_id") or ""),
            )
            if parent not in inspected_plans:
                return (
                    ("research_plan_not_inspected", "Read the exact saved research-plan revision before proposing a change."),
                    validated_arguments,
                )
    if len(requested) > 1 and any(call.risk is not ToolRisk.READ for call, _ in requested):
        return (
            ("invalid_tool_batch", "Draft and write actions must be requested individually."),
            validated_arguments,
        )
    for call, _handler in requested:
        if call.name not in {"create_evidence_draft", "create_evidence_version"}:
            continue
        source_identity = (
            str(call.arguments.get("document_id") or "").strip(),
            str(call.arguments.get("source_kind") or "").strip(),
            str(call.arguments.get("source_ref") or "").strip(),
        )
        if not has_successful_exact_source_read(
            successful_results,
            (source_identity,),
            source_digest=str(call.arguments.get("source_digest") or ""),
        ):
            return (
                (
                    "source_read_incomplete",
                    "Read the complete canonical Source before recording Evidence.",
                ),
                validated_arguments,
            )
    return None, validated_arguments


def select_tool_specs(
    capabilities: CapabilityRegistry,
    messages: list[ChatMessage],
    calls: list[ChatToolCall],
    *,
    inherited_completed_writes: set[str] | None = None,
) -> tuple[Any, ...]:
    if any(
        call.risk is ToolRisk.WRITE and call.status is ToolCallStatus.FAILED
        and call.decision_user_id is not None
        for call in calls
    ):
        # A failed approved action needs an explanation before a new decision.
        return ()
    specs = capabilities.specs
    registered_names = {spec.name for spec in specs}
    if not registered_names.intersection(intent_policy.KNOWN_CAPABILITIES):
        return specs

    latest_user = next(
        (
            message
            for message in reversed(messages)
            if message.role is ChatMessageRole.USER
        ),
        None,
    )
    user_text = str(latest_user.content if latest_user is not None else "").casefold()
    successful_results = active_successful_results_by_name(messages)
    if intent_policy.mentions_terms(user_text, intent_policy.NO_TOOL_PHRASES):
        return ()
    requested_names = intent_policy.capability_names_for_intent(
            user_text,
            has_source_context=bool(
                latest_user is not None and latest_user.source_contexts
            ),
            prior_tool_names={
                request.name
                for message in messages
                for request in message.tool_calls
            },
    )
    loaded_names = {
        name
        for result in successful_results.get("discover_research_tools", ())
        if result.get("catalog_version") == capabilities.discovery.catalog_version
        for name in result.get("loaded_tool_names", ())
        if isinstance(name, str) and name in capabilities.discovery.tools
    }
    # Prerequisite readers are also loaded by the backend. Retain their schemas
    # for later decisions in this request, just like explicitly discovered tools.
    loaded_names.update(set(successful_results).intersection(capabilities.discovery.tools))
    allowed_names = loaded_names | requested_names.intersection(intent_policy.WRITE_CAPABILITIES)
    completed_writes = {
        call.name
        for call in calls
        if call.risk is ToolRisk.WRITE and call.status is ToolCallStatus.SUCCEEDED
    }
    completed_writes.update(inherited_completed_writes or ())
    allowed_names.difference_update(completed_writes)
    if (
        "revise_research_plan" in allowed_names
        and "inspect_research_plans" in registered_names
        and not successful_results.get("inspect_research_plans")
    ):
        allowed_names.discard("revise_research_plan")
    if not loaded_names and capabilities.discovery.tools:
        return (
            *(spec for spec in specs if spec.name in allowed_names),
            capabilities.discovery.spec,
        )
    mandatory_stage = False

    completed_browse = any(
        result.get("returned_paper_count", 0) > 0
        and result.get("next_offset") is None
        for result in successful_results.get("browse_collection_papers", ())
    )
    source_grounded_intent = any(
        result.get("source_inspection_required") is True
        and result.get("catalog_version") == capabilities.discovery.catalog_version
        for result in successful_results.get("discover_research_tools", ())
    )
    # Reviewing an existing conclusion starts with that conclusion and its
    # Evidence. Only then can the researcher identify a passage to recheck.
    finding_review_pending = bool(
        loaded_names.intersection({"query_published_findings", "inspect_published_finding"})
        and not successful_results.get("inspect_published_finding")
    )
    source_grounded_intent = source_grounded_intent and not finding_review_pending
    has_attached_source_context = bool(
        latest_user is not None and latest_user.source_contexts
    )
    if source_grounded_intent and "browse_collection_papers" in registered_names and not successful_results.get(
        "browse_collection_papers"
    ) and not has_attached_source_context:
        allowed_names = registered_names.intersection({"browse_collection_papers"})
        mandatory_stage = True
    elif source_grounded_intent and has_attached_source_context:
        # The caller already supplied a canonical Source context; do not
        # force a redundant collection survey before discussing it.
        allowed_names.discard("browse_collection_papers")
    if completed_browse:
        allowed_names.discard("browse_collection_papers")
        allowed_names.discard("get_collection_context")

    # A source search is a navigation step. Once it returns matches, the
    # next scientific action must read one of those exact Sources rather
    # than broadening the search or inspecting arbitrary pages.
    source_candidates = _pending_source_search_candidates(successful_results)
    has_exact_source_read = not source_candidates and has_successful_exact_source_read(successful_results)
    # Recovery applies only until navigation succeeds again. An older failed
    # reference must not waive inspection of newly located Sources.
    last_source_navigation = max(
        (
            index for index, call in enumerate(calls)
            if call.status is ToolCallStatus.SUCCEEDED
            and call.name in {"search_sources", "inspect_document_sources"}
        ),
        default=-1,
    )
    failed_source_read = any(
        call.status is ToolCallStatus.FAILED
        and call.name in {"read_source", "inspect_table", "inspect_document_sources"}
        for call in calls[last_source_navigation + 1:]
    )
    if source_candidates and not has_exact_source_read:
        if not failed_source_read:
            return tuple(spec for spec in specs if spec.name in {"read_source", "inspect_table"})

    # A cross-paper comparison or support claim needs source-backed facts,
    # not only the paper map. Once the map is complete, require a focused
    # Source search before allowing the model to answer or choose a broad
    # inspection path.
    if (
        source_grounded_intent
        and successful_results.get("browse_collection_papers")
        and not successful_results.get("search_sources")
        and not has_exact_source_read
    ):
        allowed_names = registered_names.intersection({"search_sources"})
        mandatory_stage = True

    # Process status is only a paper-preparation view. If the collection
    # has a confirmed Objective, its canonical analysis state is the next
    # required read before the Agent reports progress to the researcher.
    if (
        successful_results.get("get_collection_context")
        and intent_policy.mentions_terms(user_text, intent_policy.PROCESS_TERMS)
        and not successful_results.get("inspect_research_process")
    ):
        allowed_names = registered_names.intersection({"inspect_research_process"})
        mandatory_stage = True
    confirmed_objective_ids = _confirmed_objective_ids(successful_results)
    if (
        successful_results.get("inspect_research_process")
        and confirmed_objective_ids
        and not successful_results.get("inspect_objective_analysis")
    ):
        allowed_names = registered_names.intersection({"inspect_objective_analysis"})
        mandatory_stage = True

    # A published Finding summary is only a navigation result. Any
    # collection-level conclusion review must inspect one exact Finding
    # returned by that query before the model can judge its basis.
    finding_candidates = _published_finding_candidates(successful_results)
    plan_intent = "propose_research_plan" in loaded_names or bool(
        requested_names.intersection({"create_research_plan", "revise_research_plan"})
    )
    if (
        successful_results.get("query_published_findings")
        and finding_candidates
        and not successful_results.get("inspect_published_finding")
        and not plan_intent
    ):
        remaining_candidates = tuple(
            candidate
            for candidate in finding_candidates
            if candidate not in _failed_finding_candidates(calls)
        )
        allowed_names = registered_names.intersection(
            {"inspect_published_finding"} if remaining_candidates else set()
        )
        mandatory_stage = True

    inspected_finding = bool(
        successful_results.get("inspect_published_finding")
    )
    persist_requested = (
        intent_policy.mentions_terms(user_text, intent_policy.PERSIST_TERMS)
        or bool(requested_names.intersection({"create_research_plan", "revise_research_plan"}))
    ) and (
        not intent_policy.mentions_terms(user_text, intent_policy.NO_WRITE_PHRASES)
        or intent_policy.has_explicit_immutable_write(user_text)
    )
    proposed_plan = bool(successful_results.get("propose_research_plan"))
    proposed_plan_this_turn = any(
        call.name == "propose_research_plan"
        and call.status is ToolCallStatus.SUCCEEDED
        for call in calls
    )
    finding_draft_this_turn = any(
        call.name == "create_finding_draft"
        and call.status is ToolCallStatus.SUCCEEDED
        for call in calls
    )
    finding_draft_requested = inspected_finding and intent_policy.mentions_terms(
        user_text, ("结论草案", "修订草案", "finding draft", "draft finding"),
    )
    # A completed plan proposal belongs to the request that asked for it.
    # Do not let an older turn force its write capability onto a later,
    # unrelated review or reading request in the same Chat trajectory.
    plan_revision_requested = intent_policy.mentions_terms(
        user_text, ("修改", "修订", "调整", "revise", "update")
    )
    plan_read_requested = intent_policy.mentions_terms(user_text, intent_policy.PLAN_READ_TERMS)
    if (
        plan_revision_requested
        and plan_intent
        and "inspect_research_plans" in registered_names
        and not successful_results.get("inspect_research_plans")
    ):
        allowed_names = {"inspect_research_plans"}
        mandatory_stage = True
    elif (
        plan_read_requested
        and plan_intent
        and not persist_requested
        and not plan_revision_requested
    ):
        allowed_names = {"inspect_research_plans"}
    elif proposed_plan_this_turn:
        mandatory_stage = True
        latest_plan = successful_results["propose_research_plan"][-1]
        plan_calls = [call for call in calls if call.name == "propose_research_plan"]
        # Schema errors before the first evaluated draft do not consume the
        # separate opportunity to correct that draft's scientific references.
        first_evaluated = next(
            (index for index, call in enumerate(plan_calls) if call.status is ToolCallStatus.SUCCEEDED),
            len(plan_calls),
        )
        plan_calls = plan_calls[first_evaluated:]
        # An unlinked citation is a correctable draft input, not a finished plan.
        correctable_basis = (
            latest_plan.get("draft_status") == "abstained"
            and bool(latest_plan.get("missing_evidence_ids") or latest_plan.get("missing_finding_ids"))
            and bool(latest_plan.get("available_finding_ids"))
            and bool(latest_plan.get("available_evidence_ids"))
            and latest_plan.get("source_analysis_version") is not None
            and not any(latest_plan.get(key) for key in (
                "rejected_finding_ids", "failed_evidence_ids",
            ))
            and (
                len(plan_calls) == 1
                or (len(plan_calls) == 2 and plan_calls[-1].error_code == "invalid_tool_arguments")
            )
        )
        if correctable_basis:
            allowed_names = {"propose_research_plan"}
        elif latest_plan.get("draft_status") == "abstained":
            allowed_names = set()
        elif persist_requested:
            allowed_names = {
                "revise_research_plan"
                if plan_revision_requested
                else "create_research_plan"
            }
        else:
            allowed_names = set()
    elif finding_draft_this_turn:
        allowed_names = set()
        mandatory_stage = True
    elif proposed_plan and plan_intent and persist_requested:
        allowed_names = {
            "revise_research_plan"
            if plan_revision_requested
            else "create_research_plan"
        }
    elif (
        plan_read_requested
        and plan_revision_requested
        and persist_requested
        and not successful_results.get("inspect_research_plans")
        and "inspect_research_plans" in registered_names
        and plan_intent
    ):
        allowed_names = {"inspect_research_plans"}
    elif plan_revision_requested and persist_requested and plan_intent:
        allowed_names = {"revise_research_plan"}
    elif finding_draft_requested and not mandatory_stage:
        # A Finding is the starting point of review, not proof that its Sources
        # have been checked. Keep discovered readers and discovery available.
        allowed_names = {"create_finding_draft"} | loaded_names.intersection(
            intent_policy.SOURCE_READ_CAPABILITIES | {"inspect_published_finding"}
        )
    elif inspected_finding and plan_intent:
        allowed_names = {"propose_research_plan"}
    elif plan_intent:
        assessed_quality = bool(
            successful_results.get("assess_objective_quality")
        )
        queried_findings = bool(
            successful_results.get("query_published_findings")
        )
        plan_prerequisites = {
            "assess_objective_quality",
            "query_published_findings",
        }
        if plan_prerequisites.issubset(registered_names):
            allowed_names = plan_prerequisites | registered_names.intersection({"get_collection_context"})
            mandatory_stage = True
            if successful_results.get("get_collection_context"):
                allowed_names.discard("get_collection_context")
            if assessed_quality:
                allowed_names.discard("assess_objective_quality")
            if queried_findings:
                allowed_names.discard("query_published_findings")
            if assessed_quality and queried_findings:
                finding_candidates = _published_finding_candidates(
                    successful_results
                )
                failed_finding_candidates = _failed_finding_candidates(calls)
                remaining_candidates = tuple(
                    candidate
                    for candidate in finding_candidates
                    if candidate not in failed_finding_candidates
                )
                allowed_names = (
                    {"inspect_published_finding"}
                    if remaining_candidates
                    else set()
                )

    # Prevent an approved write from being repeated within this bounded
    # model continuation. A later user message starts a new decision turn
    # and may legitimately create another immutable version with the same
    # capability name.
    allowed_names.difference_update(completed_writes)
    selected = tuple(spec for spec in specs if spec.name in allowed_names)
    if (
        not mandatory_stage
        and capabilities.discovery.tools
        and (finding_draft_requested or failed_source_read or required_tool_before_answer(
            tuple(spec.name for spec in selected), successful_results=successful_results,
        ) is None)
    ):
        return (*selected, capabilities.discovery.spec)
    return selected


def required_tool_before_answer(
    tool_names: tuple[str, ...],
    *,
    successful_results: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> str | None:
    if (
        "create_finding_draft" in tool_names
        and successful_results is not None
        and successful_results.get("inspect_published_finding")
        and not successful_results.get("create_finding_draft")
    ):
        return "create_finding_draft"
    reader_names = {"read_source", "inspect_table"}
    source_reader_names = {*reader_names, "inspect_document_sources"}
    if (
        set(tool_names)
        and set(tool_names).issubset(source_reader_names)
        and (
            set(tool_names).issubset(reader_names)
            or (successful_results is not None and successful_results.get("search_sources"))
        )
    ):
        if (
            successful_results is not None
            and not _pending_source_search_candidates(successful_results)
            and has_successful_exact_source_read(successful_results)
        ):
            return None
        return next((name for name in tool_names if name in source_reader_names), None)
    if len(tool_names) != 1:
        return None
    required_tool = tool_names[0]
    if required_tool in {
        "browse_collection_papers",
        "search_sources",
        "read_source",
        "inspect_table",
        "inspect_research_process",
        "inspect_objective_analysis",
        "inspect_published_finding",
        "inspect_research_plans",
        "create_finding_draft",
        "propose_research_plan",
    }:
        if successful_results is not None and successful_results.get(required_tool):
            if (
                required_tool == "propose_research_plan"
                and successful_results[required_tool][-1].get("draft_status") == "abstained"
            ):
                return required_tool
            return None
        return required_tool
    return None


def _pending_source_search_candidates(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[tuple[str, str, str], ...]:
    # Each query in the latest navigation batch needs one exact read. Search
    # matches remain alternatives, not a requirement to read every result.
    for result in successful_results.get("search_sources", ()):
        candidates: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        inspected = False
        for item in result.get("matches") or ():
            if not isinstance(item, Mapping):
                continue
            candidate = (
                str(item.get("document_id") or "").strip(),
                str(item.get("source_kind") or "").strip(),
                str(item.get("source_ref") or "").strip(),
            )
            if all(candidate) and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
                inspected = inspected or has_successful_exact_source_read(
                    successful_results, (candidate,), source_digest=item.get("source_digest"),
                )
        if candidates and not inspected:
            return tuple(candidates)
    return ()


def has_successful_exact_source_read(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
    candidates: tuple[tuple[str, str, str], ...] = (),
    *,
    source_digest: str | None = None,
) -> bool:
    candidate_set = set(candidates)
    return any(
        (not candidate_set or (document_id, kind, ref) in candidate_set)
        and (source_digest is None or digest == source_digest)
        for document_id, kind, ref, digest in complete_source_reads(successful_results)
    )


def complete_source_reads(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
) -> set[tuple[str, str, str, str]]:
    """Collect whole Sources, including same-version text pages or table rows."""
    completed: set[tuple[str, str, str, str]] = set()
    pages: dict[tuple[str, str, str, str, str, int], list[tuple[int, int]]] = {}

    def collect(
        item: Mapping[str, Any], *, table: bool = False, parent_document_id: str = "",
        paginated: bool = False,
    ) -> None:
        document_id = str(parent_document_id or item.get("document_id") or "").strip()
        source_ref = str(item.get("source_ref") or item.get("table_ref") or "").strip()
        source_kind = str(item.get("source_kind") or ("table" if table else "")).strip()
        identity = (document_id, source_kind, source_ref)
        digest = str(item.get("source_digest") or "")
        if not document_id or not source_ref or not digest:
            return
        if paginated and "content_offset" in item:
            offset = item.get("content_offset")
            total = item.get("canonical_length")
            content = item.get("content")
            if (
                type(offset) is int and type(total) is int and isinstance(content, str)
                and 0 <= offset <= offset + len(content) <= total
            ):
                pages.setdefault((*identity, digest, "characters", total), []).append((offset, offset + len(content)))
        elif table and item.get("complete_table") is False:
            offset = item.get("row_offset")
            total = item.get("data_row_count")
            count = item.get("returned_row_count")
            # The handler counts only intact rows. An oversized row preview
            # has count zero and cannot fill a gap in the reading record.
            if (
                type(offset) is int and type(total) is int and type(count) is int
                and count > 0 and 0 <= offset < offset + count <= total
            ):
                pages.setdefault((*identity, digest, "rows", total), []).append((offset, offset + count))
        elif (
            item.get("content_truncated") is False
            and (not table or (item.get("complete_table") is not False and item.get("row_offset", 0) == 0))
        ):
            completed.add((*identity, digest))

    for item in successful_results.get("read_source", ()):
        collect(item, paginated=True)
    for item in successful_results.get("inspect_table", ()):
        collect(item, table=True)
    for result in successful_results.get("inspect_document_sources", ()):
        document = result.get("document")
        if not isinstance(document, Mapping):
            continue
        for item in result.get("sources") or ():
            if isinstance(item, Mapping):
                collect(item, parent_document_id=str(document.get("document_id") or ""))
    for (document_id, source_kind, source_ref, digest, _unit, total), intervals in pages.items():
        covered = 0
        for start, end in sorted(intervals):
            if start > covered:
                break
            covered = max(covered, end)
            if covered == total:
                completed.add((document_id, source_kind, source_ref, digest))
                break
    return completed


def _confirmed_objective_ids(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[str, ...]:
    ids: list[str] = []
    for result in successful_results.get("get_collection_context", ()):
        for item in result.get("objectives") or ():
            if not isinstance(item, Mapping):
                continue
            objective_id = str(item.get("objective_id") or "").strip()
            if (
                objective_id
                and (
                    str(item.get("confirmation_status") or "") == "confirmed"
                    or item.get("published_analysis_version") is not None
                )
                and objective_id not in ids
            ):
                ids.append(objective_id)
    return tuple(ids[:12])


def _published_finding_candidates(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for result in successful_results.get("query_published_findings", ()):
        for objective in result.get("objectives") or ():
            if not isinstance(objective, Mapping):
                continue
            objective_id = str(objective.get("objective_id") or "").strip()
            for finding in objective.get("findings") or ():
                if not isinstance(finding, Mapping):
                    continue
                finding_id = str(finding.get("finding_id") or "").strip()
                candidate = (objective_id, finding_id)
                if all(candidate) and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
    return tuple(candidates[:24])


def _failed_finding_candidates(
    calls: list[ChatToolCall],
) -> set[tuple[str, str]]:
    failed: set[tuple[str, str]] = set()
    for call in calls:
        if call.name != "inspect_published_finding" or call.status is not ToolCallStatus.FAILED:
            continue
        objective_id = str(call.arguments.get("objective_id") or "").strip()
        finding_id = str(call.arguments.get("finding_id") or "").strip()
        if objective_id and finding_id:
            failed.add((objective_id, finding_id))
    return failed


def stage_instruction(
    tool_names: tuple[str, ...],
    calls: list[ChatToolCall],
    *,
    successful_results: Mapping[str, list[Mapping[str, Any]]],
) -> str | None:
    content: str | None = None
    source_candidates = _pending_source_search_candidates(successful_results)
    if (
        source_candidates
        and tool_names
        and set(tool_names).issubset({"read_source", "inspect_table"})
    ):
        content = (
            "The prior Source search returned the following exact reading "
            "candidates. Read one of these records now; do not call a broad "
            "page inspection and do not invent identifiers:\n"
            + "\n".join(
                f"- document_id={document_id}, source_kind={source_kind}, "
                f"source_ref={source_ref}"
                for document_id, source_kind, source_ref in source_candidates[:12]
            )
        )
    elif tool_names == ("inspect_objective_analysis",):
        objective_ids = _confirmed_objective_ids(successful_results)
        if objective_ids:
            content = (
                "The preparation status is already known. Read the canonical "
                "analysis state for one confirmed Objective before answering. "
                "Use exactly one of these Objective IDs:\n"
                + "\n".join(f"- objective_id={item}" for item in objective_ids)
            )
    elif tool_names == ("inspect_published_finding",):
        candidates = tuple(
            candidate
            for candidate in _published_finding_candidates(successful_results)
            if candidate not in _failed_finding_candidates(calls)
        )
        if candidates:
            content = (
                "Inspect one exact published Finding returned by the prior "
                "query. Use only these allowed (objective_id, finding_id) pairs; "
                "do not invent Finding IDs:\n"
                + "\n".join(
                    f"- objective_id={objective_id}, finding_id={finding_id}"
                    for objective_id, finding_id in candidates
                )
            )
    elif tool_names == ("propose_research_plan",):
        previous = next(iter(reversed(successful_results.get("propose_research_plan", ()))), {})
        if previous.get("draft_status") == "abstained":
            content = (
                "No reviewable plan exists yet. Correct the citation selection once using "
                "only the valid previously selected Findings and their linked Evidence below. "
                "Recheck the scientific choices against those retained references; removing an "
                "invalid ID does not by itself support its associated claims. Submit the full "
                "corrected transient draft, not a promise to resubmit.\n"
                f"Finding IDs: {previous.get('available_finding_ids', [])}\n"
                f"Evidence IDs: {previous.get('available_evidence_ids', [])}"
            )
        else:
            references = []
            for result in successful_results.get("inspect_published_finding", ()):
                finding = result.get("finding")
                if not isinstance(finding, Mapping) or not finding.get("finding_id"):
                    continue
                evidence_ids = [
                    item["evidence_id"] for item in result.get("evidence", ())
                    if isinstance(item, Mapping) and item.get("evidence_id")
                ]
                references.append(
                    f"objective_id={result.get('objective_id')}, "
                    f"analysis_version={result.get('analysis_version')}, "
                    f"finding_id={finding['finding_id']}, evidence_ids={evidence_ids}"
                )
            if references:
                content = (
                    "Build the requested plan from these inspected Finding/Evidence relationships. "
                    "Choose one Objective and analysis version. A current Evidence ID from the "
                    "collection overview may belong to a different Finding; it cannot be attached "
                    "to a selected Finding without that relationship. Use only the Evidence IDs "
                    "listed for the Findings you select below, and only for choices their inspected "
                    "content supports. Retain the distinction between literature support, the "
                    "researcher's constraints, and proposed choices.\n" + "\n".join(references)
                )
    return content


def completed_write_names(messages: list[ChatMessage]) -> set[str]:
    """Find writes completed before an approval continuation resumed.

    A fresh user message starts a new intent turn, so its call list is empty
    and these names are intentionally not carried over by ``run_turn``.
    Approval resumption has no new user message, though, and must preserve
    the same trajectory's write boundary while the model chooses its next
    read or draft step.
    """
    names_by_call_id = {
        request.tool_call_id: request.name
        for message in messages
        for request in message.tool_calls
    }
    return {
        name
        for message in messages
        if message.role is ChatMessageRole.TOOL
        and message.tool_result is not None
        and message.tool_result.status
        in {ToolResultStatus.SUCCEEDED, ToolResultStatus.QUEUED}
        for name in (names_by_call_id.get(message.tool_call_id),)
        if name in intent_policy.WRITE_CAPABILITIES
    }


def _successful_results_by_name(
    messages: list[ChatMessage],
) -> dict[str, list[Mapping[str, Any]]]:
    names_by_call_id = {
        request.tool_call_id: request.name
        for message in messages
        for request in message.tool_calls
    }
    batches_by_call_id = {
        request.tool_call_id: message.message_id
        for message in messages
        for request in message.tool_calls
    }
    latest_search_batch = None
    results: dict[str, list[Mapping[str, Any]]] = {}
    for message in messages:
        if (
            message.role is not ChatMessageRole.TOOL
            or message.tool_result is None
            or message.tool_result.status
            not in {ToolResultStatus.SUCCEEDED, ToolResultStatus.QUEUED}
        ):
            continue
        name = names_by_call_id.get(message.tool_call_id)
        if name:
            if name == "search_sources":
                batch = batches_by_call_id[message.tool_call_id]
                if batch != latest_search_batch:
                    # New successful navigation replaces the previous query's
                    # candidates; retain all independent searches in this batch.
                    results[name] = []
                    latest_search_batch = batch
            results.setdefault(name, []).append(message.tool_result.data)
    return results


def active_successful_results_by_name(
    messages: list[ChatMessage],
) -> dict[str, list[Mapping[str, Any]]]:
    """Return this request's reads, with searches scoped to their latest batch."""
    last_user_index = max(
        (
            index
            for index, message in enumerate(messages)
            if message.role is ChatMessageRole.USER
        ),
        default=-1,
    )
    return _successful_results_by_name(messages[last_user_index:])


def validate_claimed_call(context: AgentContext, call: ChatToolCall) -> None:
    if call.session_id != context.session_id:
        raise ValueError("approved tool call belongs to another session")
    if call.status is not ToolCallStatus.RUNNING:
        raise ValueError("tool call is not claimed for execution")
    if call.decision_user_id != context.user_id:
        raise ValueError("tool call was approved by another user")

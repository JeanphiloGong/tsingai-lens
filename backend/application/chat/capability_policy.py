"""Capability availability, prerequisites, and exact approval boundaries.

These decisions inspect the current request and trajectory. They do not call
the model, execute capabilities, or persist messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

from pydantic import BaseModel, ValidationError

from application.chat import intent_policy
from application.chat.capabilities import AgentContext, CapabilityRegistry, ToolSpec
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
    ToolPermissionMode,
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
    *,
    permission_mode: ToolPermissionMode | str = ToolPermissionMode.CONFIRM,
) -> tuple[tuple[str, str] | None, dict[str, BaseModel]]:
    permission_mode = ToolPermissionMode(permission_mode)
    successful_results = active_successful_results_by_name(messages)
    latest_user = next(
        (message for message in reversed(messages) if message.role is ChatMessageRole.USER),
        None,
    )
    request_text = str(latest_user.content if latest_user is not None else "").casefold()
    _, forbidden_writes = intent_policy._write_request_scope(request_text)
    validated_arguments: dict[str, BaseModel] = {}
    for call, handler in requested:
        if handler is None and call.risk is ToolRisk.UNKNOWN:
            return (
                ("unknown_capability", "The requested research capability is not available."),
                validated_arguments,
            )
        if permission_mode is ToolPermissionMode.NONE or (
            permission_mode is ToolPermissionMode.READ_ONLY
            and call.risk is ToolRisk.WRITE
        ):
            return (
                (
                    "tool_permission_denied",
                    "The current tool permission mode does not allow this research action.",
                ),
                validated_arguments,
            )
        if call.risk is ToolRisk.WRITE and call.name in forbidden_writes:
            return (
                (
                    "current_request_prohibits_tool",
                    "The current request prohibits this research action.",
                ),
                validated_arguments,
            )
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
                f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: "
                f"{error['type']}: {str(error.get('msg') or error['type'])[:240]}"
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
    permission_mode: ToolPermissionMode | str = ToolPermissionMode.CONFIRM,
) -> tuple[ToolSpec, ...]:
    """Select currently available tool definitions for the next model turn.

    Visibility is derived from the active discovery/results trajectory. The
    request permission mode and same-continuation write de-duplication remain
    deterministic backend boundaries; research-stage ordering is left to the
    model.
    """
    permission_mode = ToolPermissionMode(permission_mode)
    if permission_mode is ToolPermissionMode.NONE:
        return ()

    specs = capabilities.specs

    def select_names(names: set[str] | frozenset[str]) -> tuple[ToolSpec, ...]:
        return tuple(
            spec
            for spec in specs
            if spec.name in names
            and not (
                permission_mode is ToolPermissionMode.READ_ONLY
                and spec.risk is ToolRisk.WRITE
            )
        )

    successful_results = active_successful_results_by_name(messages)
    loaded_names = {
        name
        for result in successful_results.get("discover_research_tools", ())
        for name in result.get("loaded_tool_names", ())
        if isinstance(name, str) and name in capabilities.discovery.tools
    }
    loaded_names.update(
        set(successful_results).intersection(capabilities.discovery.tools)
    )

    latest_user = next(
        (
            message
            for message in reversed(messages)
            if message.role is ChatMessageRole.USER
        ),
        None,
    )
    user_text = str(latest_user.content if latest_user is not None else "").casefold()
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
    if permission_mode is ToolPermissionMode.READ_ONLY:
        requested_names.difference_update(intent_policy.WRITE_CAPABILITIES)
        loaded_names.difference_update(
            name
            for name in loaded_names
            if (handler := capabilities.get(name)) is not None
            and handler.spec.risk is ToolRisk.WRITE
        )

    completed_writes = {
        call.name
        for call in calls
        if call.risk is ToolRisk.WRITE
        and call.status is ToolCallStatus.SUCCEEDED
    }
    completed_writes.update(inherited_completed_writes or ())
    allowed_names = loaded_names | requested_names.intersection(
        intent_policy.WRITE_CAPABILITIES
    )
    allowed_names.difference_update(completed_writes)

    selected = select_names(allowed_names)
    if capabilities.discovery.tools:
        return (*selected, capabilities.discovery.spec)
    return selected


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


def _pending_document_overviews(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
    calls: list[ChatToolCall] | tuple[ChatToolCall, ...] = (),
) -> tuple[str, ...]:
    if not successful_results.get("inspect_published_finding") or not any(
        item.get("source_inspection_required") is True
        for item in successful_results.get("discover_research_tools", ())
    ):
        return ()
    inspected = {
        str(item.get("document", {}).get("document_id") or "")
        for item in successful_results.get("inspect_document_sources", ())
        if "document_outline" in item
    }
    failed = {
        str(call.arguments.get("document_id") or "") for call in calls
        if call.name == "inspect_document_sources" and call.status is ToolCallStatus.FAILED
    }
    documents = []
    for result in successful_results.get("inspect_published_finding", ()):
        items = [*result.get("evidence", ()), *result.get("replacement_evidence", ())]
        finding = result.get("finding")
        if isinstance(finding, Mapping):
            items.extend(finding.get("paper_contributions", ()))
        documents.extend(str(item.get("document_id") or "") for item in items if isinstance(item, Mapping))
    documents.extend(str(item.get("document_id") or "")
                     for item in successful_results.get("read_source", ()))
    documents.extend(str(document_id)
                     for item in successful_results.get("search_sources", ())
                     for document_id in item.get("document_ids", ()))
    return tuple(dict.fromkeys(item for item in documents if item and item not in inspected | failed))


def _pending_finding_sources(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
    calls: list[ChatToolCall] | tuple[ChatToolCall, ...] = (),
) -> tuple[tuple[str, str, str], ...]:
    if not any(item.get("source_inspection_required") is True
               for item in successful_results.get("discover_research_tools", ())):
        return ()
    failed = {
        tuple(str(call.arguments.get(key) or "") for key in ("document_id", "source_kind", "source_ref"))
        for call in calls if call.name == "read_source" and call.status is ToolCallStatus.FAILED
    }
    pending = []
    for result in successful_results.get("inspect_published_finding", ()):
        for item in (*result.get("evidence", ()), *result.get("replacement_evidence", ())):
            candidate = tuple(str(item.get(key) or "") for key in ("document_id", "source_kind", "source_ref"))
            if (all(candidate) and candidate not in failed and candidate not in pending
                    and not has_successful_exact_source_read(successful_results, (candidate,))):
                pending.append(candidate)
        finding = result.get("finding")
        contribution_documents = {
            str(item.get("document_id") or "").strip()
            for item in (finding.get("paper_contributions", ()) if isinstance(finding, Mapping) else ())
            if isinstance(item, Mapping) and item.get("document_id")
        }
        read_documents = {identity[0] for identity in complete_source_reads(successful_results)}
        failed_documents = {
            str(call.arguments.get("document_id") or "").strip()
            for call in calls
            if call.name in {"read_source", "inspect_table"}
            and call.status is ToolCallStatus.FAILED
            and call.arguments.get("document_id")
        }
        # Contributions without Evidence still need one bounded Source check;
        # otherwise a challenged paper such as ELI could be silently skipped.
        for overview in successful_results.get("inspect_document_sources", ()):
            document = overview.get("document")
            document_id = str(document.get("document_id") or "").strip() if isinstance(document, Mapping) else ""
            if not document_id or document_id not in contribution_documents or document_id in read_documents | failed_documents:
                continue
            for source in overview.get("sources", ()):
                if not isinstance(source, Mapping):
                    continue
                candidate = tuple(str(source.get(key) or "").strip() for key in ("document_id", "source_kind", "source_ref"))
                if all(candidate) and candidate not in pending:
                    pending.append(candidate)
                    break
    return tuple(pending)


def _section_reading_progress(
    successful_results: Mapping[str, list[Mapping[str, Any]]],
    *,
    calls: list[ChatToolCall] | tuple[ChatToolCall, ...] = (),
) -> list[dict[str, Any]]:
    completed = complete_source_reads(successful_results)
    documents: set[str] = set()
    failed_outlines: set[str] = set()
    failed_reads: dict[str, int] = {}
    # Search candidates are scoped to the latest batch elsewhere. Reading scope
    # must retain earlier requested papers even if later searches narrow it.
    for call in calls:
        if call.name == "search_sources":
            requested_ids = call.arguments.get("document_ids")
            if isinstance(requested_ids, (list, tuple)):
                documents.update(item.strip() for item in requested_ids if isinstance(item, str))
        elif call.name in {"inspect_document_sources", "read_source", "inspect_table"}:
            document_id = call.arguments.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                continue
            document_id = document_id.strip()
            documents.add(document_id)
            if call.status is ToolCallStatus.FAILED:
                if call.name == "inspect_document_sources":
                    failed_outlines.add(document_id)
                else:
                    failed_reads[document_id] = failed_reads.get(document_id, 0) + 1
    for result in successful_results.get("search_sources", ()):
        documents.update(str(item) for item in result.get("document_ids", ()))
    for result in successful_results.get("inspect_published_finding", ()):
        items = [*result.get("evidence", ()), *result.get("replacement_evidence", ())]
        finding = result.get("finding")
        if isinstance(finding, Mapping):
            items.extend(finding.get("paper_contributions", ()))
        documents.update(str(item.get("document_id") or "") for item in items)
    outlines = {}
    sections: dict[tuple[str, str], set[tuple[str, str]]] = {}
    headings: dict[tuple[str, str], set[tuple[str, str]]] = {}
    section_batches: dict[tuple[str, str], dict[str, Any]] = {}
    incomplete_sources: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    read_pages: dict[str, set[int]] = {}
    sources = []
    for result in successful_results.get("inspect_document_sources", ()):
        document_id = str(result.get("document", {}).get("document_id") or "")
        documents.add(document_id)
        if "document_outline" in result:
            outlines[document_id] = result
        if result.get("heading_path") is not None:
            filters = {key: result[key] for key in ("heading_path", "page", "query", "source_ref", "source_types")
                       if result.get(key) not in (None, "", [], ())}
            section_batches[(document_id, json.dumps(filters, sort_keys=True))] = {
                "arguments": {"document_id": document_id, **filters, "offset": result.get("next_offset")},
                "last_batch_block_types": sorted({str(item.get("block_type") or item.get("source_type") or "unknown")
                                                  for item in result.get("sources", ())}),
            }
        sources.extend({**item, "document_id": document_id} for item in result.get("sources", ()))
    sources.extend(successful_results.get("read_source", ()))
    sources.extend({**item, "source_kind": "table", "source_ref": item.get("table_ref")}
                   for item in successful_results.get("inspect_table", ()))
    for source in sources:
        identity = tuple(str(source.get(key) or "") for key in
                         ("document_id", "source_kind", "source_ref", "source_digest"))
        documents.add(identity[0])
        if source.get("content_truncated") is True and all(identity) and identity not in completed:
            incomplete_sources[identity] = source
        if identity in completed:
            key = (identity[0], " ".join(str(source.get("heading_path") or "").split()))
            sections.setdefault(key, set()).add((identity[1], identity[2]))
            if source.get("block_type") == "heading":
                headings.setdefault(key, set()).add((identity[1], identity[2]))
            if type(source.get("page")) is int:
                read_pages.setdefault(identity[0], set()).add(source["page"])
    progress = []
    for document_id in sorted(documents - {""}):
        overview = outlines.get(document_id)
        section_progress = [{
            "heading_path": section["heading_path"],
            "pages": section["pages"],
            "available_passages": section["source_count"],
            "completely_read_passages": len(sections.get((document_id, section["heading_path"]), ())),
            "completely_read_heading_passages": len(headings.get((document_id, section["heading_path"]), ())),
        } for section in overview["document_outline"]] if overview is not None else None
        pending = []
        for (doc, _filters), batch in section_batches.items():
            if doc != document_id or type(batch["arguments"]["offset"]) is not int:
                continue
            if any(section["heading_path"] == batch["arguments"]["heading_path"]
                   and section["completely_read_passages"] >= section["available_passages"]
                   for section in section_progress or ()):
                continue
            pending.append(batch)
        progress.append({
            "document_id": document_id,
            "outline_status": ("inspected" if overview is not None else
                               "inspection_failed" if document_id in failed_outlines else "not_inspected"),
            "outline_truncated": overview.get("outline_truncated", False) if overview is not None else None,
            "prepared_source_pages": overview.get("prepared_source_pages") if overview is not None else None,
            "completely_read_passages": len({(kind, ref) for doc, kind, ref, _digest in completed if doc == document_id}),
            "pages_with_complete_passage_reads": sorted(read_pages.get(document_id, ())),
            "failed_read_attempts": failed_reads.get(document_id, 0),
            "sections": section_progress,
            "pending_section_reads": pending,
            "pending_source_reads": [{
                "tool_name": "inspect_table" if kind == "table" else "read_source",
                "arguments": ({"document_id": doc, "table_ref": ref,
                               **({"row_offset": source["next_row_offset"]} if type(source.get("next_row_offset")) is int else {})}
                              if kind == "table" else
                              {"document_id": doc, "source_kind": kind, "source_ref": ref,
                               **({"offset": source["next_offset"]} if "content_offset" in source
                                  and type(source.get("next_offset")) is int else {})}),
            } for (doc, kind, ref, _digest), source in incomplete_sources.items() if doc == document_id],
        })
    return progress


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
    """Return factual execution observations without prescribing a route."""
    observations: dict[str, Any] = {}
    if "inspect_document_sources" in tool_names:
        coverage = _section_reading_progress(successful_results, calls=calls)
        if coverage:
            observations["reading_ledger"] = coverage

    drafts = {}
    for name in (
        "create_evidence_draft",
        "create_finding_draft",
        "propose_research_plan",
    ):
        values = successful_results.get(name, ())
        if values:
            drafts[name] = values[-1]
    if drafts:
        observations["latest_transient_results"] = drafts

    if calls and calls[-1].status is ToolCallStatus.FAILED:
        observations["latest_failure"] = {
            "tool": calls[-1].name,
            "error_code": calls[-1].error_code,
        }

    if not observations:
        return None
    return (
        "Execution observations, not a prescribed next step. Complete passage reads do not "
        "certify a paper or scientific conclusion. Unknown coverage is not unavailable text. "
        "Transient drafts are not saved or approved. Use the prior paired tool results for "
        "source locators and repair details; choose the next action for the active request.\n"
        + json.dumps(observations, ensure_ascii=False)
    )

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

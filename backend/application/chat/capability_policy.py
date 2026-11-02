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

from application.chat.capabilities.contracts import AgentContext, ToolSpec
from application.chat.capabilities.registry import CapabilityRegistry
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
    validated_arguments: dict[str, BaseModel] = {}
    for call, handler in requested:
        if (
            call.name == "discover_research_tools"
            and permission_mode is ToolPermissionMode.READ_ONLY
            and any(
                isinstance(name, str)
                and (candidate := capabilities.get(name)) is not None
                and candidate.spec.risk is ToolRisk.WRITE
                for name in (call.arguments.get("tool_names") or ())
            )
        ):
            return (
                (
                    "tool_permission_denied",
                    "The current read-only permission does not allow discovery of write actions.",
                ),
                validated_arguments,
            )
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
        if call.name != "propose_paper_experiment_draft":
            continue
        document_id = str(call.arguments.get("document_id") or "").strip()
        if not any(
            item[0] == document_id
            for item in complete_source_reads(_successful_results_by_name(messages))
        ):
            return (
                (
                    "source_read_incomplete",
                    "Read the complete canonical Sources supporting the experiment before proposing its draft. "
                    "Completed reads from this session can be reused when their content is unchanged. "
                    "Keep the experiment facts while repairing the read prerequisites; do not delete measurements or comparisons to bypass them.",
                ),
                validated_arguments,
            )
    return None, validated_arguments


def select_tool_specs(
    capabilities: CapabilityRegistry,
    messages: list[ChatMessage],
    calls: list[ChatToolCall],
    *,
    permission_mode: ToolPermissionMode | str = ToolPermissionMode.CONFIRM,
) -> tuple[ToolSpec, ...]:
    """Select currently available tool definitions for the next model turn.

    Visibility is derived from the active discovery/results trajectory. The
    permission mode is a deterministic backend boundary; research-stage
    ordering and whether another resource needs the same capability remain
    model decisions.
    """
    permission_mode = ToolPermissionMode(permission_mode)
    if permission_mode is ToolPermissionMode.NONE:
        return ()

    specs = (*capabilities.specs, capabilities.execution_plan.spec)

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
    loaded_names.update(spec.name for spec in specs if spec.initially_available)
    if any(spec.initially_available for spec in capabilities.specs):
        loaded_names.add(capabilities.execution_plan.spec.name)
    loaded_names.update(
        set(successful_results).intersection(capabilities.discovery.tools)
    )

    if permission_mode is ToolPermissionMode.READ_ONLY:
        write_names = {
            name
            for name in loaded_names
            if (handler := capabilities.get(name)) is not None
            and handler.spec.risk is ToolRisk.WRITE
        }
        loaded_names.difference_update(write_names)

    allowed_names = loaded_names

    selected = select_names(allowed_names)
    missing_names = {spec.name for spec in select_names(set(capabilities.discovery.tools))} - loaded_names
    if missing_names:
        return (
            *selected,
            capabilities.discovery.spec_for_names(missing_names),
        )
    return selected


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
        # None is the supported collection-wide search scope. Only returned
        # matches identify candidate papers; a search hit is not an exact read.
        documents.update(result.get("document_ids") or ())
        documents.update(item["document_id"] for item in result.get("matches", ()))
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
            previous = outlines.get(document_id)
            version_changed = (previous is not None and result.get("source_version")
                               and previous.get("source_version")
                               and result["source_version"] != previous["source_version"])
            if (previous is None or version_changed
                    or not (result.get("heading_path") or result.get("section_id"))):
                outlines[document_id] = result
            else:
                # A selected section is a partial view, not a replacement for
                # the known document outline and its unread sibling sections.
                known_sections = {section["heading_path"]: section for section in previous["document_outline"]}
                known_sections.update((section["heading_path"], section) for section in result["document_outline"])
                outlines[document_id] = {**previous, "document_outline": list(known_sections.values())}
        if "offset" in result or result.get("heading_path") is not None or result.get("section_id") is not None:
            filters = {key: result[key] for key in ("section_id", "heading_path", "page", "query", "source_ref", "source_types", "source_version")
                       if result.get(key) not in (None, "", [], ())}
            key = (document_id, json.dumps(filters, sort_keys=True))
            entry = section_batches.setdefault(key, {"ranges": []})
            offset = result.get("offset", 0)
            entry["ranges"].append((offset, offset + len(result.get("sources", ()))))
            covered = 0
            for start, end in sorted(entry["ranges"]):
                if start > covered:
                    break
                covered = max(covered, end)
            next_offset = result.get("next_offset")
            if "match_total" in result:
                next_offset = None if covered == result["match_total"] else covered
            entry["arguments"] = {**(result.get("continuation") or {"document_id": document_id, **filters}), "offset": next_offset}
            entry["last_batch_block_types"] = sorted({str(item.get("block_type") or item.get("source_type") or "unknown")
                                                      for item in result.get("sources", ())})
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
            pending.append({key: value for key, value in batch.items() if key != "ranges"})
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
                               **({"source_version": source["source_version"]} if source.get("source_version") else {}),
                               **({"row_offset": source["next_row_offset"]} if type(source.get("next_row_offset")) is int else {})}
                              if kind == "table" else
                              {"document_id": doc, "source_kind": kind, "source_ref": ref,
                               **({"source_version": source["source_version"]} if source.get("source_version") else {}),
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


def stage_instruction(
    tool_names: tuple[str, ...],
    calls: list[ChatToolCall],
    *,
    successful_results: Mapping[str, list[Mapping[str, Any]]],
    prior_experiment_draft: Mapping[str, Any] | None = None,
) -> str | None:
    """Return factual execution observations without prescribing a route."""
    observations: dict[str, Any] = {}
    browsing: dict[tuple[Any, ...], dict[str, Any]] = {}
    for page in successful_results.get("browse_collection_papers", ()):
        key = (page.get("query"), page.get("catalog_digest"), page.get("paper_total"))
        ledger = browsing.setdefault(key, {
            "query": page.get("query"), "paper_total": page.get("paper_total"),
            "covered_ranges": [], "papers": {},
        })
        papers = page.get("papers", ())
        offset = page.get("offset", 0)
        if papers:
            ledger["covered_ranges"].append([offset, offset + len(papers)])
        for paper in papers:
            document_id = paper.get("document_id")
            if document_id:
                ledger["papers"][document_id] = {
                    "document_id": document_id,
                    "title": str(paper.get("title") or paper.get("filename") or "")[:240],
                }
    for ledger in browsing.values():
        merged: list[list[int]] = []
        for start, end in sorted(ledger["covered_ranges"]):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        covered = merged[0][1] if merged and merged[0][0] == 0 else 0
        ledger["covered_ranges"] = merged
        ledger["next_unread_offset"] = None if covered == ledger["paper_total"] else covered
        ledger["seen_document_count"] = len(ledger["papers"])
        ledger["omitted_paper_count"] = max(0, len(ledger["papers"]) - 100)
        ledger["papers"] = list(ledger["papers"].values())[-100:]
    if browsing:
        observations["paper_browsing"] = list(browsing.values())[-3:]
    if successful_results.get("discover_research_tools"):
        observations["loaded_tools"] = list(tool_names)
    plans = successful_results.get("update_execution_plan", ())
    if (len(plans) > 1 and calls and calls[-1].name == "update_execution_plan"
            and all(plans[-1].get(key) == plans[-2].get(key) for key in ("steps", "status"))):
        observations["unchanged_plan"] = (
            "This plan state was already accepted. Continue the active step with available research tools; "
            "another explanation or plan submission does not inspect evidence. Update it when the phase, "
            "remaining work or final disposition changes."
        )
    if calls:
        latest = calls[-1]
        previous_count = sum(
            call.name == latest.name and call.arguments_digest == latest.arguments_digest
            and call.status is ToolCallStatus.SUCCEEDED
            for call in calls[:-1]
        )
        if previous_count:
            observations["repeated_action"] = {
                "tool": latest.name, "arguments": dict(latest.arguments),
                "previous_successful_count": previous_count,
                "note": "These exact arguments already succeeded. Reuse the result unless a new check requires rereading it.",
            }
    if "inspect_document_sources" in tool_names:
        coverage = _section_reading_progress(successful_results, calls=calls)
        if coverage:
            observations["reading_ledger"] = coverage

    drafts = {}
    for name in ("create_finding_draft", "propose_paper_experiment_draft", "propose_research_plan"):
        values = successful_results.get(name, ())
        if values:
            # Full payloads remain in paired tool results and durable drafts.
            # Repeating them in a pinned instruction can exhaust the context.
            keys = ("draft_id", "draft_digest", "document_id", "objective_id", "draft_status",
                    "experiment_count", "source_fingerprint", "source_snapshots", "persistence")
            latest = values[-1]
            drafts[name] = {key: latest[key] for key in keys if key in latest}
            if isinstance(latest.get("draft"), Mapping):
                drafts[name]["draft"] = {
                    key: latest["draft"][key]
                    for key in ("draft_id", "source_analysis_version", "selection_ids", "finding_id")
                    if key in latest["draft"]
                }
    experiment_drafts = successful_results.get("propose_paper_experiment_draft", ())
    if experiment_drafts:
        by_document = {}
        for draft in experiment_drafts:
            if draft.get("document_id"):
                by_document[draft["document_id"]] = {
                    key: draft[key] for key in ("document_id", "draft_id", "draft_digest", "experiment_count", "source_fingerprint")
                    if key in draft
                }
        observations["paper_experiment_drafts"] = list(by_document.values())
    saved_revisions = successful_results.get("create_paper_experiment_revision", ())
    if saved_revisions:
        observations["saved_paper_experiments"] = [
            {key: revision[key] for key in ("document_id", "experiment_id", "experiment_version") if key in revision}
            for result in saved_revisions
            for revision in result.get("revisions", ()) if isinstance(revision, Mapping)
        ]
    if drafts:
        observations["latest_transient_results"] = drafts
    elif prior_experiment_draft and set(tool_names).intersection({
        "propose_paper_experiment_draft", "create_paper_experiment_revision",
    }):
        observations["prior_experiment_draft"] = {
            key: prior_experiment_draft[key]
            for key in ("draft_id", "draft_digest", "objective_id", "document_id", "experiment_count")
            if key in prior_experiment_draft
        }

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
        "Transient drafts are not saved or approved. Continuations describe available "
        "unread content, not mandatory work beyond the research question.\n"
        + json.dumps(observations, ensure_ascii=False)
    )

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

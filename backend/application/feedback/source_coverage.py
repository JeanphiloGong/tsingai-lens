"""Project durable Chat audit facts into feedback evidence coverage.

The feedback worker must describe what the Chat trajectory proves.  A selected
``ChatSourceContext`` is a request signal, while a successful, complete source
tool result is an execution fact.  Keeping this projection separate from the
worker makes that distinction easy to test and prevents the analysis engine
from quietly inventing evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from application.chat.capability_policy import complete_source_reads
from domain.chat import ChatMessage, ChatMessageRole
from domain.feedback import EvidenceCoverage


_SOURCE_TOOL_NAMES = frozenset(
    {"read_source", "inspect_table", "inspect_document_sources"}
)
_NAVIGATION_TOOL_NAMES = frozenset({"search_sources", "browse_collection_papers"})


@dataclass(frozen=True)
class ChatCoverageAudit:
    """The already-read audit records needed by the projection.

    ``None`` means that the repository could not provide that audit surface;
    an empty tuple/mapping means the surface was available and contained no
    matching records.  This distinction lets legacy trajectories remain
    ``unknown``/``partial`` without treating missing storage as a successful
    read.
    """

    model_calls: Sequence[Any] | None = None
    tool_calls: Mapping[str, Any] | None = None
    tool_audit_error: bool = False


@dataclass
class _SourceObservation:
    record: dict[str, Any]
    name: str
    tool_call_id: str
    complete: bool = False


def build_evidence_coverage(
    messages: Sequence[ChatMessage],
    answer: ChatMessage,
    *,
    audit: ChatCoverageAudit | None = None,
) -> EvidenceCoverage:
    """Build a conservative coverage projection for one persisted answer.

    Only messages in the answer's latest user turn are considered.  Source
    contexts selected by a user are retained in ``requested_scope`` but never
    promoted to ``inspected_sources``.  The latter is populated solely from
    successful complete Source reads recorded as tool results.
    """

    audit = audit or ChatCoverageAudit()
    ordered = tuple(messages)
    # Tool-request assistant messages and the final answer can share the
    # response identity in an in-flight trajectory.  The last occurrence is
    # the durable answer boundary; using the first one would discard all
    # preceding tool results.
    answer_positions = [
        index for index, message in enumerate(ordered)
        if message.message_id == answer.message_id
    ]
    answer_index = answer_positions[-1] if answer_positions else len(ordered)
    before_answer = ordered[:answer_index]
    active_user_index = max(
        (
            index for index, message in enumerate(before_answer)
            if message.role is ChatMessageRole.USER
        ),
        default=0,
    )
    active_messages = before_answer[active_user_index:]
    active_user = next(
        (
            message for message in reversed(active_messages)
            if message.role is ChatMessageRole.USER
        ),
        None,
    )

    request_by_id = {
        request.tool_call_id: request
        for message in active_messages
        for request in message.tool_calls
    }
    result_messages = tuple(
        message for message in active_messages
        if message.role is ChatMessageRole.TOOL and message.tool_result is not None
    )
    durable_tool_calls = audit.tool_calls or {}

    requested: list[dict[str, Any]] = []
    requested_keys: set[tuple[str, str, str, str]] = set()

    def add_requested(record: Mapping[str, Any], *, origin: str) -> None:
        normalized = _requested_record(record, origin=origin)
        key = _coverage_key(normalized)
        if not key[0] and not key[1]:
            return
        if key in requested_keys:
            return
        requested_keys.add(key)
        requested.append(normalized)

    if active_user is not None:
        for source in active_user.source_contexts:
            add_requested(source.to_record(), origin="user_selected_context")

    observations: list[_SourceObservation] = []
    successful_results: dict[str, list[Mapping[str, Any]]] = {}
    source_attempts: list[dict[str, Any]] = []
    failed_attempts: list[dict[str, Any]] = []

    for message in result_messages:
        result = message.tool_result
        if result is None:
            continue
        request = request_by_id.get(result.tool_call_id)
        durable_call = durable_tool_calls.get(result.tool_call_id)
        name = str(
            getattr(durable_call, "name", None)
            or (request.name if request is not None else "")
        )
        arguments = _mapping(
            getattr(durable_call, "arguments", None)
            or (request.arguments if request is not None else {})
        )
        if name in _SOURCE_TOOL_NAMES:
            source_attempts.append({
                "tool_call_id": result.tool_call_id,
                "tool_name": name,
                "arguments": dict(arguments),
            })
        elif name in _NAVIGATION_TOOL_NAMES:
            _add_navigation_scope(add_requested, name=name, arguments=arguments, data=result.data)

        result_status = _enum_value(result.status)
        durable_status = _enum_value(getattr(durable_call, "status", None))
        failed = result_status == "failed" or durable_status in {"failed", "rejected"}
        if name in _SOURCE_TOOL_NAMES and failed:
            attempt = _failed_source_record(
                name=name,
                arguments=arguments,
                data=result.data,
                tool_call_id=result.tool_call_id,
                error_code=result.error_code or getattr(durable_call, "error_code", None),
            )
            if attempt:
                failed_attempts.append(attempt)
            continue
        if name not in _SOURCE_TOOL_NAMES or result_status != "succeeded":
            continue
        data = _mapping(result.data)
        successful_results.setdefault(name, []).append(data)
        for record in _source_records(name, data):
            observations.append(
                _SourceObservation(
                    record=record,
                    name=name,
                    tool_call_id=result.tool_call_id,
                )
            )

        # A successful exact request is itself a requested scope signal.  It
        # does not become proof until complete_source_reads confirms it.
        _add_exact_tool_scope(add_requested, name=name, arguments=arguments, data=data)
        if name == "inspect_document_sources":
            _add_document_scope(add_requested, arguments=arguments, data=data)

    # A requested source call can be persisted before its result message is
    # appended (for example after a worker interruption).  Keep that durable
    # request visible as an unresolved attempt instead of silently treating it
    # as no work having been requested.
    observed_tool_ids = {item["tool_call_id"] for item in source_attempts}
    for tool_call_id, request in request_by_id.items():
        durable_call = durable_tool_calls.get(tool_call_id)
        name = str(
            getattr(durable_call, "name", None) or getattr(request, "name", "")
        )
        if name not in _SOURCE_TOOL_NAMES or tool_call_id in observed_tool_ids:
            continue
        arguments = _mapping(
            getattr(durable_call, "arguments", None) or request.arguments
        )
        source_attempts.append({
            "tool_call_id": tool_call_id,
            "tool_name": name,
            "arguments": dict(arguments),
        })
        status = _enum_value(getattr(durable_call, "status", None))
        if status in {"failed", "rejected"}:
            attempt = _failed_source_record(
                name=name,
                arguments=arguments,
                data={},
                tool_call_id=tool_call_id,
                error_code=getattr(durable_call, "error_code", None),
            )
            if attempt:
                failed_attempts.append(attempt)
            continue

        # The request is durable even when the worker stopped before its
        # result message was appended.  Preserve its exact scope so the
        # annotator sees an unresolved read rather than an empty trajectory.
        _add_exact_tool_scope(
            add_requested,
            name=name,
            arguments=arguments,
            data={},
        )
        if name == "inspect_document_sources":
            _add_document_scope(
                add_requested,
                arguments=arguments,
                data={},
            )

    complete = complete_source_reads(successful_results)
    for observation in observations:
        identity = _source_identity(observation.record)
        observation.complete = bool(identity and identity in complete)

    inspected = _inspected_records(observations)
    omitted: list[dict[str, Any]] = []
    omitted_keys: set[tuple[str, str, str, str]] = set()

    def add_omitted(record: Mapping[str, Any], *, reason: str) -> None:
        item = dict(record)
        item["reason"] = reason
        key = _coverage_key(item)
        if not key[0] and not key[1]:
            return
        # A complete read wins over an incomplete/failed observation for the
        # same source identity.  The complete record is the authoritative
        # execution fact for this projection.
        if any(_same_source_identity(item, inspected_item) for inspected_item in inspected):
            return
        if key in omitted_keys:
            return
        omitted_keys.add(key)
        omitted.append(item)

    for observation in observations:
        if observation.complete:
            continue
        record = _candidate_record(observation.record)
        add_omitted(record, reason="source_read_incomplete")

    for attempt in failed_attempts:
        add_omitted(attempt, reason="source_read_failed")

    # Search matches and selected contexts describe candidates.  They remain
    # omitted until a matching complete exact read is present.
    for item in requested:
        if _requested_item_has_complete_read(item, inspected):
            continue
        origin = str(item.get("origin") or "")
        if origin == "user_selected_context":
            add_omitted(item, reason="selected_context_not_verified")
        elif origin == "search_result":
            add_omitted(item, reason="search_match_not_read")
        elif origin in {"tool_requested", "document_scope"}:
            # Document-only requests cannot be certified by a single source
            # read.  Keep the unresolved scope visible to the annotator.
            if not item.get("source_ref"):
                add_omitted(item, reason="document_scope_not_exactly_read")
            else:
                add_omitted(item, reason="source_read_not_verified")

    matching_model_calls = _matching_model_calls(
        audit.model_calls, answer, active_user
    )
    gaps = _coverage_gaps(
        audit=audit,
        model_calls=matching_model_calls,
        source_attempts=source_attempts,
        failed_attempts=failed_attempts,
        inspected=inspected,
        requested=requested,
    )
    status = _coverage_status(
        audit=audit,
        model_calls=matching_model_calls,
        requested=requested,
        inspected=inspected,
        omitted=omitted,
        source_attempts=source_attempts,
        failed_attempts=failed_attempts,
        successful_source_count=len(observations),
    )
    return EvidenceCoverage(
        requested_scope=tuple(requested),
        inspected_sources=tuple(inspected),
        omitted_candidates=tuple(omitted),
        # A tool read establishes execution coverage, not that a particular
        # answer claim was bound to that Source.  Claim-level linkage remains
        # empty until a separate, deterministic attribution record exists.
        claim_support=(),
        gaps=tuple(gaps),
        coverage_status=status,
    )


def _matching_model_calls(
    model_calls: Sequence[Any] | None,
    answer: ChatMessage,
    active_user: ChatMessage | None,
) -> tuple[Any, ...]:
    if model_calls is None:
        return ()
    trigger_id = active_user.message_id if active_user is not None else None
    matched: list[Any] = []
    for call in model_calls:
        if str(getattr(call, "session_id", "")) != answer.session_id:
            continue
        purpose = _enum_value(getattr(call, "purpose", None))
        if purpose == "compaction":
            continue
        response_id = getattr(call, "response_message_id", None)
        call_trigger = getattr(call, "trigger_message_id", None)
        if response_id != answer.message_id and call_trigger != trigger_id:
            continue
        matched.append(call)
    return tuple(matched)


def _coverage_gaps(
    *,
    audit: ChatCoverageAudit,
    model_calls: Sequence[Any],
    source_attempts: Sequence[Mapping[str, Any]],
    failed_attempts: Sequence[Mapping[str, Any]],
    inspected: Sequence[Mapping[str, Any]],
    requested: Sequence[Mapping[str, Any]],
) -> list[str]:
    gaps: list[str] = []
    if audit.model_calls is None:
        gaps.append(
            "model Source-read audit is unavailable; selected context is only a coverage signal"
        )
    elif not model_calls:
        gaps.append("no model call audit matched the answer")
    else:
        non_success = sorted(
            {
                _enum_value(getattr(call, "status", None)) or "unknown"
                for call in model_calls
                if _enum_value(getattr(call, "status", None)) != "provider_succeeded"
            }
        )
        if non_success:
            gaps.append("model call audit contains non-success status: " + ", ".join(non_success))
    if failed_attempts:
        codes = sorted({str(item.get("error_code") or "unknown") for item in failed_attempts})
        gaps.append("source tool failed: " + ", ".join(codes))
    if source_attempts and not inspected:
        gaps.append("no successful exact Source read was recorded")
    if inspected:
        gaps.append("claim-level Source bindings are not recorded on the answer")
    if requested and not inspected and not source_attempts:
        gaps.append("requested Source scope was not verified by a model tool read")
    if audit.tool_audit_error:
        gaps.append("durable tool-call audit could not be read")
    return list(dict.fromkeys(gaps))


def _coverage_status(
    *,
    audit: ChatCoverageAudit,
    model_calls: Sequence[Any],
    requested: Sequence[Mapping[str, Any]],
    inspected: Sequence[Mapping[str, Any]],
    omitted: Sequence[Mapping[str, Any]],
    source_attempts: Sequence[Mapping[str, Any]],
    failed_attempts: Sequence[Mapping[str, Any]],
    successful_source_count: int,
) -> str:
    if inspected:
        model_ok = bool(model_calls) and all(
            _enum_value(getattr(call, "status", None)) == "provider_succeeded"
            for call in model_calls
        )
        exact_requested = [
            item for item in requested
            if item.get("source_ref") and item.get("source_kind")
        ]
        all_requested_read = bool(exact_requested) and all(
            _requested_item_has_complete_read(item, inspected)
            for item in exact_requested
        )
        if (
            audit.model_calls is not None
            and model_ok
            and all_requested_read
            and not omitted
            and not failed_attempts
        ):
            return "complete"
        return "partial"
    if failed_attempts and successful_source_count == 0:
        return "failed"
    if requested and any(item.get("origin") == "user_selected_context" for item in requested):
        # Preserve the P1 behavior for legacy trajectories with selected
        # contexts but no persisted model-call audit: the result is partial,
        # never a fabricated successful inspection.
        return "partial"
    if source_attempts:
        if successful_source_count > 0:
            return "partial"
        return "failed" if failed_attempts else "unknown"
    return "unknown"


def _inspected_records(
    observations: Sequence[_SourceObservation],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for observation in observations:
        if not observation.complete:
            continue
        identity = _source_identity(observation.record)
        if not identity:
            continue
        record = _candidate_record(observation.record)
        record.update(
            audit_basis="successful_source_tool_result",
            tool_call_ids=[observation.tool_call_id],
        )
        key = identity
        previous = grouped.get(key)
        if previous is None:
            grouped[key] = record
            continue
        previous["tool_call_ids"] = list(dict.fromkeys([
            *previous.get("tool_call_ids", []), observation.tool_call_id
        ]))
        if len(str(record.get("quote") or "")) > len(str(previous.get("quote") or "")):
            previous["quote"] = record.get("quote")
            previous["quote_truncated"] = record.get("quote_truncated", True)
    return list(grouped.values())


def _source_records(name: str, data: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if name in {"read_source", "inspect_table"}:
        record = dict(data)
        if name == "inspect_table":
            record.setdefault("source_kind", "table")
            record.setdefault("source_ref", record.get("table_ref"))
            if "content" not in record and record.get("table_markdown") is not None:
                record["content"] = record.get("table_markdown")
        return (record,)
    document = _mapping(data.get("document"))
    document_id = str(document.get("document_id") or "")
    document_title = str(document.get("title") or "")
    values: list[dict[str, Any]] = []
    for item in data.get("sources") or ():
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        if document_id:
            record.setdefault("document_id", document_id)
        if document_title:
            record.setdefault("document_title", document_title)
        values.append(record)
    return tuple(values)


def _add_exact_tool_scope(
    add_requested: Any,
    *,
    name: str,
    arguments: Mapping[str, Any],
    data: Mapping[str, Any],
) -> None:
    if name == "read_source":
        add_requested({
            "document_id": arguments.get("document_id"),
            "source_kind": arguments.get("source_kind"),
            "source_ref": arguments.get("source_ref"),
            "source_digest": data.get("source_digest"),
        }, origin="tool_requested")
    elif name == "inspect_table":
        add_requested({
            "document_id": arguments.get("document_id"),
            "source_kind": "table",
            "source_ref": arguments.get("table_ref"),
            "source_digest": data.get("source_digest"),
        }, origin="tool_requested")


def _add_document_scope(
    add_requested: Any,
    *,
    arguments: Mapping[str, Any],
    data: Mapping[str, Any],
) -> None:
    document = _mapping(data.get("document"))
    document_id = str(arguments.get("document_id") or document.get("document_id") or "")
    if not document_id:
        return
    # A filtered inspect with an exact Source reference is represented by its
    # source-level observation.  Add a document candidate only when the
    # returned page explicitly says that more prepared Sources remain (or no
    # source rows were returned at all).
    if arguments.get("source_ref"):
        return
    if data.get("next_offset") is None and not data.get("outline_truncated") and data.get("sources"):
        return
    add_requested({
        "document_id": document_id,
        "document_title": document.get("title"),
        "source_ref": arguments.get("source_ref"),
        "heading_path": arguments.get("heading_path"),
        "source_types": arguments.get("source_types") or (),
        "page": arguments.get("page"),
    }, origin="document_scope")


def _add_navigation_scope(
    add_requested: Any,
    *,
    name: str,
    arguments: Mapping[str, Any],
    data: Mapping[str, Any],
) -> None:
    if name == "search_sources":
        for document_id in arguments.get("document_ids") or ():
            add_requested({"document_id": document_id}, origin="tool_requested")
        for match in data.get("matches") or ():
            if isinstance(match, Mapping):
                add_requested(dict(match), origin="search_result")
    elif name == "browse_collection_papers":
        for paper in data.get("papers") or ():
            if isinstance(paper, Mapping):
                add_requested(dict(paper), origin="tool_requested")


def _failed_source_record(
    *,
    name: str,
    arguments: Mapping[str, Any],
    data: Mapping[str, Any],
    tool_call_id: str,
    error_code: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "document_id": arguments.get("document_id") or data.get("document_id"),
        "source_kind": (
            arguments.get("source_kind")
            if name == "read_source"
            else "table"
            if name == "inspect_table"
            else data.get("source_kind")
        ),
        "source_ref": (
            arguments.get("source_ref")
            if name == "read_source"
            else arguments.get("table_ref")
            if name == "inspect_table"
            else arguments.get("source_ref")
        ),
        "tool_call_id": tool_call_id,
        "error_code": error_code,
    }
    return {key: value for key, value in record.items() if value not in (None, "", ())}


def _requested_record(record: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
    item = dict(record)
    item["origin"] = origin
    item["verified_by_tool"] = False
    return item


def _candidate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(record)
    content = item.pop("content", None)
    if content is None:
        content = item.pop("table_markdown", None)
    if isinstance(content, str):
        item["quote"] = content[:1600]
        item["quote_truncated"] = len(content) > 1600 or bool(item.get("content_truncated"))
    for key in ("_canonical_content", "estimated_tokens", "support_is_evidence"):
        item.pop(key, None)
    return {
        key: value for key, value in item.items()
        if value not in (None, "", (), [], {})
    }


def _coverage_key(record: Mapping[str, Any], *, include_digest: bool = False) -> tuple[str, str, str, str]:
    return (
        str(record.get("document_id") or ""),
        str(record.get("source_kind") or ""),
        str(record.get("source_ref") or record.get("table_ref") or ""),
        str(record.get("source_digest") or "") if include_digest else "",
    )


def _source_identity(record: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    key = _coverage_key(record, include_digest=True)
    return key if all(key) else None


def _same_source_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_key = _coverage_key(left)
    right_key = _coverage_key(right)
    return left_key[:3] == right_key[:3] and bool(left_key[0] and left_key[2])


def _requested_item_has_complete_read(
    requested: Mapping[str, Any], inspected: Sequence[Mapping[str, Any]]
) -> bool:
    document_id = str(requested.get("document_id") or "")
    source_kind = str(requested.get("source_kind") or "")
    source_ref = str(requested.get("source_ref") or requested.get("table_ref") or "")
    if not document_id or not source_kind or not source_ref:
        return False
    digest = str(requested.get("source_digest") or "")
    return any(
        str(item.get("document_id") or "") == document_id
        and str(item.get("source_kind") or "") == source_kind
        and str(item.get("source_ref") or item.get("table_ref") or "") == source_ref
        and (not digest or str(item.get("source_digest") or "") == digest)
        for item in inspected
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


__all__ = ["ChatCoverageAudit", "build_evidence_coverage"]

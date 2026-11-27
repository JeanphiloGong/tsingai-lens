"""Bind model citation markers to verified Source reads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re

from agent.domain.models import Operation
from conversation.domain import AnswerCitation


_MARKER = re.compile(r"\[\[cite:([^\]\r\n]*)\]\]")


def bind_answer_citations(
    content: str, operations: tuple[Operation, ...]
) -> tuple[str, tuple[AnswerCitation, ...]]:
    targets: dict[str, Mapping[str, Any]] = {}
    for operation in operations:
        result = operation.result
        if operation.status != "succeeded" or not isinstance(result, Mapping):
            continue
        if result.get("status") != "succeeded":
            continue
        data = result.get("data")
        if not isinstance(data, Mapping):
            continue

        records = _records_for_operation(operation.name, data)
        if not records:
            continue
        resource_keys = _source_resource_keys(result.get("resource_refs"))
        for record in records:
            document_id = str(record.get("document_id") or "").strip()
            source_ref = str(
                record.get("source_ref") or record.get("table_ref") or ""
            ).strip()
            if not document_id or not source_ref:
                continue
            if f"{document_id}:{source_ref}" not in resource_keys:
                continue
            targets[f"{document_id}/{source_ref}"] = record

    parts: list[str] = []
    citations: list[AnswerCitation] = []
    previous_end = 0
    offset = 0
    for match in _MARKER.finditer(content):
        text = content[previous_end : match.start()]
        parts.append(text)
        offset += _utf16_length(text)
        target = targets.get(match.group(1).strip())
        if target is not None:
            citations.append(_citation_at(offset, target))
        previous_end = match.end()

    parts.append(content[previous_end:])
    return "".join(parts), tuple(citations)


def _records_for_operation(
    name: str, data: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    if name == "read_source":
        if not data.get("complete_source") or data.get("content_truncated"):
            return ()
        return (data,)
    if name == "inspect_table":
        if not data.get("complete_table") or data.get("content_truncated"):
            return ()
        return ({**data, "source_ref": data.get("table_ref"), "source_kind": "table"},)
    if name == "inspect_document_sources":
        document = data.get("document")
        document = document if isinstance(document, Mapping) else {}
        records = []
        for item in data.get("sources") or ():
            if not isinstance(item, Mapping) or not item.get("content"):
                continue
            if item.get("content_truncated"):
                continue
            records.append(
                {
                    **item,
                    "document_id": item.get("document_id") or document.get("document_id"),
                    "document_title": item.get("document_title") or document.get("title"),
                }
            )
        return tuple(records)
    return ()


def _source_resource_keys(value: object) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or item.get("resource_type") != "source":
            continue
        resource_id = str(item.get("resource_id") or "").strip()
        if ":" not in resource_id:
            continue
        document_id, source_ref = resource_id.split(":", 1)
        keys.add(f"{document_id}:{source_ref}")
        source_parts = source_ref.split(":")
        if len(source_parts) > 1:
            keys.add(f"{document_id}:{source_parts[-1]}")
    return keys


def _citation_at(offset: int, record: Mapping[str, Any]) -> AnswerCitation:
    return AnswerCitation(
        offset=offset,
        document_id=str(record["document_id"]),
        source_ref=str(record.get("source_ref") or record["table_ref"]),
        source_kind=str(record.get("source_kind") or record.get("source_type") or "text_window"),
        document_title=str(record.get("document_title") or ""),
        page=record.get("page"),
        heading_path=str(record["heading_path"]) if record.get("heading_path") else None,
        caption=str(record["caption"]) if record.get("caption") else None,
        figure_label=str(record["figure_label"]) if record.get("figure_label") else None,
    )


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


__all__ = ["bind_answer_citations"]

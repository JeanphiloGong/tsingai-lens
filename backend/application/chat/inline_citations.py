"""Bind Research Agent source markers to readable, verified inline links."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import re
from typing import Any

from domain.chat import ChatMessage, ChatMessageRole, ChatToolCall, ChatToolResult, ToolResultStatus


_CITATION_MARKER = re.compile(r"\[\[cite:(?P<references>[^\]\r\n]+)\]\]")
_MARKDOWN_LINK = re.compile(r"(?<!\!)\[[^\]\r\n]*\]\([^)\r\n]*\)")
_BACKTICK = re.compile(r"`(?P<reference>[^`\r\n]+)`")
_LOCATOR = re.compile(r"(?<![\w-])(?P<reference>[A-Za-z0-9][A-Za-z0-9_.:/-]{8,})(?![\w-])")
_INTERNAL_SOURCE_ID = re.compile(
    r"(?<![A-Za-z0-9_-])(?:blk|tbl|fig)_doc_[A-Za-z0-9]+(?:[_-][A-Za-z0-9.-]+)+(?![A-Za-z0-9_-])"
)
_LABEL = re.compile(
    r"(?i)(?:\b(?:table|tab\.?|figure|fig\.?)\s*[A-Za-z]?\s*\d+[A-Za-z]?\b|(?:表|图)\s*\d+[A-Za-z]?)"
)


@dataclass(frozen=True)
class _CitationTarget:
    document_id: str
    source_ref: str
    document_title: str
    source_kind: str
    page: int | str | None
    heading_path: str | None
    caption: str | None
    figure_label: str | None
    href: str | None
    eligible: bool

    @property
    def key(self) -> str:
        return f"{self.document_id}:{self.source_ref}"

    @property
    def label(self) -> str:
        title = _short_text(self.document_title, 100) or "Supporting source"
        kind = self.source_kind.strip().lower()
        locator = ""
        if kind == "table":
            match = _LABEL.search(str(self.caption or ""))
            locator = match.group(0) if match else "Table"
        elif kind == "figure":
            figure_text = self.figure_label or self.caption or ""
            match = _LABEL.search(str(figure_text))
            locator = match.group(0) if match else "Figure"
        else:
            heading = " > ".join(
                part.strip()
                for part in re.split(r"\s*(?:>|/)\s*", str(self.heading_path or ""))
                if part.strip()
            )
            locator = _short_text(heading, 80) or "Passage"
        parts = [title, locator]
        if self.page is not None and str(self.page).strip():
            parts.append(f"p. {self.page}")
        if not self.eligible:
            parts.append("preview")
        return " · ".join(parts)


def format_inline_citations(
    content: str,
    *,
    calls: Iterable[ChatToolCall | Any] = (),
    results: Iterable[ChatToolResult] = (),
    messages: Iterable[ChatMessage] = (),
) -> str:
    """Replace model citation markers and known raw locators with safe links.

    The model sees canonical Source locators so it can bind a claim to the
    exact passage it inspected. Those locators are an internal trace identity;
    this function is the only boundary that turns them into user-facing text.
    Only successful Source reads are eligible for a supporting citation. Search
    results and truncated previews remain readable as previews when an old
    answer contains their locator, but are never rendered as supporting links.
    """

    text = str(content or "")
    if not text:
        return text

    call_names: dict[str, str] = {}
    for call in calls:
        call_id = str(getattr(call, "tool_call_id", "") or "").strip()
        name = str(getattr(call, "name", "") or "").strip()
        if call_id and name:
            call_names[call_id] = name
    all_results: list[ChatToolResult] = [item for item in results]
    for message in messages:
        if message.tool_result is not None:
            all_results.append(message.tool_result)
        for request in message.tool_calls:
            call_names.setdefault(request.tool_call_id, request.name)

    targets = _build_targets(all_results, call_names)

    aliases: dict[str, list[_CitationTarget]] = {}
    for target in targets.values():
        for alias in (target.source_ref, target.key, f"{target.document_id}/{target.source_ref}"):
            aliases.setdefault(alias, []).append(target)

    # Hold generated links outside the raw-locator pass. Their href contains
    # the internal Source ref by design, and must not be rewritten again.
    placeholders: dict[str, str] = {}

    def marker_replacement(match: re.Match[str]) -> str:
        rendered: list[str] = []
        for reference in (part.strip().strip("`") for part in match.group("references").split(",")):
            target = _resolve(reference, aliases)
            if target is None:
                continue
            rendered.append(_render_target(target))
        if not rendered:
            return ""
        token = f"\x00CITATION_{len(placeholders)}\x00"
        placeholders[token] = " ".join(rendered)
        return token

    text = _CITATION_MARKER.sub(marker_replacement, text)

    def backtick_replacement(match: re.Match[str]) -> str:
        target = _resolve(match.group("reference").strip(), aliases)
        if target is None:
            return match.group(0)
        token = f"\x00CITATION_{len(placeholders)}\x00"
        placeholders[token] = _render_target(target)
        return token

    text = _BACKTICK.sub(backtick_replacement, text)

    # Existing Markdown links are already presentation-safe; leave their URL
    # and label intact while replacing plain locator text elsewhere.
    pieces = _MARKDOWN_LINK.split(text)
    for index in range(0, len(pieces), 2):
        pieces[index] = _LOCATOR.sub(
            lambda match: _render_raw_locator(match.group("reference"), aliases),
            pieces[index],
        )
        pieces[index] = _redact_unresolved_source_ids(pieces[index])
    text = "".join(pieces)
    for token, rendered in placeholders.items():
        text = text.replace(token, rendered)
    return text


def format_message_citations(messages: Iterable[ChatMessage]) -> tuple[ChatMessage, ...]:
    """Format assistant messages for a user-facing trajectory response.

    Stored messages remain the canonical audit/model record. This projection is
    deliberately read-only: it gives older answers the same inline citation
    treatment as newly generated answers without rewriting the trajectory.
    """

    materialized = tuple(messages)
    return tuple(
        replace(
            message,
            content=format_inline_citations(message.content, messages=materialized),
        )
        if message.role is ChatMessageRole.ASSISTANT
        else message
        for message in materialized
    )


def _build_targets(
    results: Iterable[ChatToolResult],
    call_names: Mapping[str, str],
) -> dict[str, _CitationTarget]:
    targets: dict[str, _CitationTarget] = {}
    for result in results:
        if result.status is not ToolResultStatus.SUCCEEDED:
            continue
        name = call_names.get(result.tool_call_id, "")
        if name not in {"read_source", "inspect_table", "inspect_document_sources", "search_sources"}:
            continue
        data = result.data if isinstance(result.data, Mapping) else {}
        records: list[Mapping[str, Any]] = []
        if name == "inspect_document_sources":
            document = data.get("document") if isinstance(data.get("document"), Mapping) else {}
            document_id = str(document.get("document_id") or "").strip()
            document_title = str(document.get("title") or "").strip()
            for item in data.get("sources") or ():
                if isinstance(item, Mapping):
                    records.append({
                        **item,
                        "document_id": item.get("document_id") or document_id,
                        "document_title": item.get("document_title") or document_title,
                    })
        elif name == "search_sources":
            records.extend(item for item in data.get("matches") or () if isinstance(item, Mapping))
        else:
            records.append(data)
        hrefs: dict[str, str | None] = {}
        for ref in result.resource_refs:
            if ref.resource_type != "source":
                continue
            resource_id = str(ref.resource_id or "").strip()
            if ":" not in resource_id:
                continue
            document_ref, *source_parts = resource_id.split(":")
            if not document_ref or not source_parts:
                continue
            source_key = f"{document_ref}:{':'.join(source_parts)}"
            hrefs[source_key] = ref.href
            # Some older capability results include source_kind in the
            # resource identity. Keep the final locator usable either way.
            hrefs.setdefault(f"{document_ref}:{source_parts[-1]}", ref.href)
        for item in records:
            document_id = str(item.get("document_id") or "").strip()
            source_ref = str(item.get("source_ref") or item.get("table_ref") or "").strip()
            if not document_id or not source_ref:
                continue
            key = f"{document_id}:{source_ref}"
            href = hrefs.get(key)
            if href is None:
                source_kind = str(item.get("source_kind") or item.get("source_type") or "").strip()
                if source_kind:
                    href = hrefs.get(f"{document_id}:{source_kind}:{source_ref}")
            if href is None:
                # A result may be reconstructed in tests or from an older
                # checkpoint without resource_refs. Never invent a URL.
                href = None
            complete = not bool(item.get("content_truncated"))
            if name == "read_source":
                complete = complete and bool(item.get("complete_source"))
            elif name == "inspect_table":
                complete = complete and bool(item.get("complete_table"))
            elif name == "inspect_document_sources":
                complete = complete and bool(item.get("content"))
            candidate = _CitationTarget(
                document_id=document_id,
                source_ref=source_ref,
                document_title=str(item.get("document_title") or "").strip(),
                source_kind=str(item.get("source_kind") or item.get("source_type") or "text_window"),
                page=item.get("page"),
                heading_path=(str(item.get("heading_path")) if item.get("heading_path") else None),
                caption=(str(item.get("caption")) if item.get("caption") else None),
                figure_label=(str(item.get("figure_label")) if item.get("figure_label") else None),
                href=href,
                eligible=name != "search_sources" and complete,
            )
            existing = targets.get(key)
            if existing is None or (not existing.eligible and candidate.eligible):
                targets[key] = candidate
    return targets


def _resolve(reference: str, aliases: Mapping[str, list[_CitationTarget]]) -> _CitationTarget | None:
    normalized = reference.strip().strip("`")
    candidates = aliases.get(normalized)
    if candidates and len(candidates) == 1:
        return candidates[0]
    return None


def _render_raw_locator(reference: str, aliases: Mapping[str, list[_CitationTarget]]) -> str:
    target = _resolve(reference, aliases)
    if target is None:
        return reference
    # Short words such as ``results`` are only replaced when explicitly
    # marked or wrapped in backticks; long compound locators are safe to bind
    # in ordinary prose as a backwards-compatible cleanup for old answers.
    if len(reference) < 12 and not any(char in reference for char in "_-:"):
        return reference
    return _render_target(target)


def _render_target(target: _CitationTarget) -> str:
    label = _escape_label(target.label)
    if target.eligible and target.href and target.href.startswith("/collections/"):
        return f"[{label}]({target.href})"
    return label


def _redact_unresolved_source_ids(value: str) -> str:
    """Keep internal source identities out of prose when no target is known."""

    return _INTERNAL_SOURCE_ID.sub("supporting source", value)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _short_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 3)].rstrip() + "..."


__all__ = ["format_inline_citations", "format_message_citations"]

"""Restore parser-fragmented table layout without changing Source values."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from hashlib import sha256
from typing import Any

from application.core.objectives.analysis.diagnostics import record_analysis_diagnostic
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_text import NUMBER_PATTERN
from application.core.objectives.analysis.source_validation import _objective_row_matches_headers
from application.core.paper_facts.extraction import PaperFactsExtractor
from domain.source import render_markdown_table

logger = logging.getLogger(__name__)

_TABLE_MATRIX_REPAIR_PROMPT_TOKEN_LIMIT = 12_000
_TABLE_NUMBER = re.compile(
    r"^(?:table|tab\.?)\s+([A-Za-z0-9][A-Za-z0-9.\-]*)", re.IGNORECASE,
)
_CONTINUED_TABLE = re.compile(
    r"^(?:table|tab\.?)\s+([A-Za-z0-9][A-Za-z0-9.\-]*)"
    r"\s*(?:\(\s*continued\s*\)|continued)$", re.IGNORECASE,
)
_TABLE_READING_CONTEXT_CHAR_LIMIT = 8_000
_TABLE_READING_CONTEXT_BLOCK_LIMIT = 6


def build_table_reading_context(
    *, table: Any, tables: list[Any], blocks: list[Any], caption_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Read bounded neighbors; their prose is not part of the table's grid."""
    page = getattr(table, "page", None)
    if page is None:
        return [], []
    neighbors = sorted(
        (block for block in blocks
         if getattr(block, "document_id", None) == table.document_id
         and getattr(block, "page", None) in (page - 1, page, page + 1)),
        key=lambda block: getattr(block, "block_order", 0),
    )
    caption_block_id = getattr(table, "caption_block_id", None)
    caption_index = next((index for index, block in enumerate(neighbors)
        if (caption_block_id and block.block_id == caption_block_id)
        or (caption_text and block.text.strip() == caption_text.strip())), None)
    selected: dict[str, tuple[Any, str]] = {}
    if caption_index is not None:
        for step, relation in ((-1, "preceding_text"), (1, "following_text")):
            for distance in (1, 2):
                index = caption_index + step * distance
                if index < 0 or index >= len(neighbors):
                    break
                block = neighbors[index]
                if getattr(block, "block_type", "paragraph") not in ("paragraph", "list_item"):
                    break
                selected[block.block_id] = (block, relation)
    number = _TABLE_NUMBER.match(caption_text.strip())
    if number:
        table_number = number.group(1).rstrip(".")
        mention = re.compile(
            r"\b(?:table|tab\.?)\s+" + re.escape(table_number) + r"(?![\w\-]|\.\d)",
            re.IGNORECASE,
        )
        for block in neighbors:
            if getattr(block, "block_type", "paragraph") in ("paragraph", "list_item") and mention.search(block.text):
                selected.setdefault(block.block_id, (block, "table_reference"))
    context: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    chars = 0
    for block, relation in sorted(selected.values(), key=lambda item: getattr(item[0], "block_order", 0)):
        text = block.text.strip()
        if not text:
            continue
        if len(context) >= _TABLE_READING_CONTEXT_BLOCK_LIMIT or chars + len(text) > _TABLE_READING_CONTEXT_CHAR_LIMIT:
            omitted.append({"source_ref": block.block_id, "reason": "context_budget"})
            continue
        context.append({
            "source_kind": "text_window", "source_ref": block.block_id,
            "page": block.page, "relation": relation, "text": text,
        })
        chars += len(text)
    order = getattr(table, "table_order", None)
    candidates = [candidate for candidate in tables
        if candidate.document_id == table.document_id
        and order is not None and getattr(candidate, "table_order", None) == order + 1
        and getattr(candidate, "page", None) in (page, page + 1)]
    if number and len(candidates) == 1:
        candidate = candidates[0]
        labels = [str(candidate.caption_text or ""),
                  *(str(cell) for row in candidate.table_matrix[:2] for cell in row)]
        markers = [match for label in labels
                   if (match := _CONTINUED_TABLE.fullmatch(label.strip()))]
        headers = [" ".join(header.split()).casefold() for header in table.column_headers]
        donor_headers = [" ".join(header.rsplit(">", 1)[-1].split()).casefold()
                         for header in candidate.column_headers]
        if (headers and headers == donor_headers and markers
            and all(match.group(1).rstrip(".").casefold() == table_number.casefold()
                    for match in markers)):
            markdown = render_markdown_table(
                candidate.table_matrix, candidate.column_headers,
                header_row_count=candidate.header_row_count,
            )
            if chars + len(markdown) <= _TABLE_READING_CONTEXT_CHAR_LIMIT:
                context.append({
                    "source_kind": "table", "source_ref": candidate.table_id,
                    "page": candidate.page, "relation": "printed_table_continuation",
                    "table_markdown": markdown,
                })
            else:
                omitted.append({"source_ref": candidate.table_id, "reason": "context_budget"})
    return context, omitted


def find_table_label_continuation(
    *,
    table: Any,
    tables: list[Any],
    caption_text: str,
) -> dict[str, Any] | None:
    """Locate an explicit label-only carryover, never infer a specimen name."""
    number = _TABLE_NUMBER.match(caption_text.strip())
    matrix = normalize_table_matrix(list(getattr(table, "table_matrix", ()) or ()))
    if number is None or len(matrix) < 2:
        return None
    table_number = number.group(1).rstrip(".").casefold()
    last_row = matrix[-1]
    fragment = re.sub(r"\s+", "", last_row[0]).casefold() if last_row else ""
    if (
        not fragment
        or any(char.isalpha() for char in fragment)
        or not any(char.isdigit() for char in fragment)
        or not any(last_row[1:])
    ):
        return None
    page = getattr(table, "page", None)
    order = getattr(table, "table_order", None)
    if page is None or order is None:
        return None
    candidates = [
        candidate for candidate in tables
        if getattr(candidate, "document_id", None) == getattr(table, "document_id", None)
        and getattr(candidate, "table_order", None) == order + 1
        and getattr(candidate, "page", None) in (page, page + 1)
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    headers = [
        " ".join(str(value).split()).casefold()
        for value in getattr(table, "column_headers", ())
    ]
    donor_headers = [
        " ".join(str(value).rsplit(">", 1)[-1].split()).casefold()
        for value in getattr(candidate, "column_headers", ())
    ]
    if not headers or headers != donor_headers or len(headers) != len(last_row):
        return None
    donor_matrix = normalize_table_matrix(
        list(getattr(candidate, "table_matrix", ()) or ())
    )
    marker = _CONTINUED_TABLE.fullmatch(
        str(getattr(candidate, "caption_text", "") or "").strip()
    )
    for donor_row_index, row in enumerate(donor_matrix):
        cells = [" ".join(cell.split()) for cell in row if cell]
        markers = [_CONTINUED_TABLE.fullmatch(cell) for cell in cells]
        if markers and all(markers):
            if any(
                item.group(1).rstrip(".").casefold() != table_number
                for item in markers
            ):
                return None
            marker = markers[0]
            continue
        if [cell.casefold() for cell in cells] == headers:
            continue
        break
    else:
        return None
    if marker is None or marker.group(1).rstrip(".").casefold() != table_number:
        return None
    donor_row = donor_matrix[donor_row_index]
    if len(donor_row) != len(headers) or not donor_row[0] or any(donor_row[1:]):
        return None
    label = re.sub(r"\s+", "", donor_row[0]).casefold()
    if (
        not label.endswith(fragment)
        or not any(char.isalpha() for char in label)
        or _objective_cell_text_looks_structurally_fragmented(donor_row[0])
        or NUMBER_PATTERN.findall(label) != NUMBER_PATTERN.findall(fragment)
    ):
        return None
    return {
        "source_ref": str(candidate.table_id),
        "page": candidate.page,
        "row_index": donor_row_index,
        "row": donor_row,
    }


def repair_table_source(
    *,
    collection_id: str,
    route: EvidenceCandidate,
    source: dict[str, Any],
    paper_facts_extractor: PaperFactsExtractor | None,
) -> tuple[dict[str, Any], Exception | None]:
    if not _objective_table_source_needs_llm_structural_repair(
        route=route,
        source=source,
    ):
        return source, None
    original_matrix = normalize_table_matrix(source.get("table_matrix"))
    canonical_matrix = _canonical_objective_table_matrix(
        source=source,
        matrix=original_matrix,
    )
    raw_canonical_matrix = canonical_matrix
    continuation = source.get("table_label_continuation")
    repair_source = source
    if continuation:
        canonical_matrix = [*canonical_matrix, list(continuation["row"])]
        repair_source = {
            **source, "table_matrix": canonical_matrix, "header_row_count": 1,
        }
    model_request_count = 0
    model_row_count: int | None = None
    final_row_count: int | None = None
    model_repair_count = 0
    deterministic_rebind_count = 0
    number_sequence_verified: bool | None = None
    warnings: list[str] = []

    def record_trace(status: str, failure_reason: str | None = None) -> None:
        record_analysis_diagnostic(
            {
                "trace_type": "table_matrix_repair",
                "collection_id": collection_id,
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "table_id": route.source_ref,
                "page": source.get("page"),
                "status": status,
                "original_row_count": len(raw_canonical_matrix),
                "model_row_count": model_row_count,
                "final_row_count": final_row_count,
                "model_request_count": model_request_count,
                "model_repair_count": model_repair_count,
                "fragment_row_reduction_count": (
                    max(0, len(raw_canonical_matrix) - final_row_count)
                    if final_row_count is not None
                    else 0
                ),
                "deterministic_rebind_count": deterministic_rebind_count,
                "number_sequence_verified": number_sequence_verified,
                "warnings": list(dict.fromkeys(warnings)),
                "failure_reason": failure_reason,
                **({
                    "continuation_source_ref": continuation["source_ref"],
                    "continuation_row_index": continuation["row_index"],
                    "repair_input_row_count": len(canonical_matrix),
                } if continuation else {}),
                **({
                    "reading_context_source_refs": [
                        item["source_ref"] for item in source["table_reading_context"]
                    ],
                } if source.get("table_reading_context") else {}),
                **({
                    "reading_context_omissions": source["table_reading_context_omissions"],
                } if source.get("table_reading_context_omissions") else {}),
            }
        )

    try:
        if paper_facts_extractor is None:
            raise RuntimeError("table repair extractor is unavailable")
        repair_payloads = _build_objective_table_matrix_repair_payloads(
            route=route,
            source=repair_source,
            paper_facts_extractor=paper_facts_extractor,
        )
        parsed_repair_items = []
        for repair_payload in repair_payloads:
            model_request_count += 1
            parsed_repair_items.append(
                (
                    repair_payload,
                    paper_facts_extractor.repair_table_matrix(repair_payload),
                )
            )
        parsed_repairs = tuple(parsed_repair_items)
    except Exception as exc:
        logger.exception(
            "Research objective table matrix repair failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_ref=%s",
            collection_id,
            route.source_ref,
            route.objective_id,
            route.document_id,
            route.source_ref,
        )
        record_trace("provider_failed", f"{exc.__class__.__name__}: {exc}")
        return source, exc

    repair_records = []
    for repair_payload, parsed in parsed_repairs:
        repairs = getattr(parsed, "repairs", None)
        if repairs:
            row_offset = int(
                repair_payload["source"]["table_slice"]["first_source_row_index"]
            )
            for repair_item in repairs:
                repair_record = (
                    repair_item.model_dump()
                    if hasattr(repair_item, "model_dump")
                    else dict(repair_item)
                )
                if repair_record.get("row_index") is not None:
                    repair_record["row_index"] = (
                        int(repair_record["row_index"]) + row_offset - 1
                    )
                repair_records.append(repair_record)
        warnings.extend(
            str(warning)
            for warning in getattr(parsed, "warnings", None) or ()
            if str(warning).strip()
        )
    model_repair_count = len(repair_records)
    repaired_matrix = _merge_objective_table_matrix_repairs(
        source=source,
        canonical_matrix=canonical_matrix,
        parsed_repairs=parsed_repairs,
    )
    model_row_count = len(repaired_matrix)
    if not repaired_matrix:
        reason = "table matrix repair returned no usable matrix"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if continuation and (
        len(repaired_matrix) > len(raw_canonical_matrix)
        or re.sub(r"\s+", "", repaired_matrix[-1][0]).casefold()
        != re.sub(r"\s+", "", continuation["row"][0]).casefold()
    ):
        reason = "table matrix repair did not bind the continuation label to the final row"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    repaired_matrix, residual_repairs = (
        _cleanup_objective_repaired_table_matrix_residual_fragments(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
            column_headers=source.get("column_headers", ()),
        )
    )
    repaired_matrix, uncertainty_repairs = (
        _rebind_objective_table_mean_uncertainty_columns(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
            column_headers=source.get("column_headers", ()),
        )
    )
    deterministic_rebind_count = len(uncertainty_repairs)
    final_row_count = len(repaired_matrix)
    if (
        repaired_matrix == canonical_matrix
        and _objective_table_matrix_has_structural_fragments(canonical_matrix)
    ):
        reason = "table matrix repair left the fragmented matrix unchanged"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if _objective_table_matrix_has_structural_fragments(repaired_matrix):
        reason = "table matrix repair returned a structurally fragmented matrix"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    number_sequence_verified = (
        _objective_table_repair_preserves_result_number_sequences(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
        )
    )
    if not number_sequence_verified:
        reason = "table matrix repair changed or reordered source result numbers"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if not _objective_table_repair_preserves_source_tokens(
        original_matrix=canonical_matrix,
        repaired_matrix=repaired_matrix,
        visual_text=(
            str(source.get("table_visual_text") or "")
            + ("\n" + continuation["row"][0] if continuation else "")
        ),
    ):
        reason = "table matrix repair introduced tokens not present in source"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if not _objective_table_repair_preserves_row_label_order(
        original_matrix=canonical_matrix,
        repaired_matrix=repaired_matrix,
    ):
        reason = "table matrix repair changed or reordered source row labels"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    repaired_source = dict(source)
    repaired_source["raw_table_matrix"] = source.get("table_matrix", [])
    repaired_source["table_matrix"] = repaired_matrix
    repaired_source["table_matrix_structural_repair_applied"] = True
    repair_attestation = {
        "schema_version": "objective_table_repair_attestation.v1",
        "raw_matrix_sha256": _objective_table_matrix_sha256(raw_canonical_matrix),
        "repaired_matrix_sha256": _objective_table_matrix_sha256(repaired_matrix),
    }
    if continuation:
        repaired_source["table_label_continuation"] = {
            **continuation, "target_row_index": len(repaired_matrix) - 1,
        }
    visual_text = str(source.get("table_visual_text") or "").strip()
    if visual_text:
        repair_attestation["visual_text_sha256"] = sha256(
            visual_text.encode("utf-8")
        ).hexdigest()
    repaired_source["table_matrix_repair_attestation"] = repair_attestation
    repair_records.extend(residual_repairs)
    repair_records.extend(uncertainty_repairs)
    if repair_records:
        repaired_source["table_matrix_repairs"] = repair_records
    if warnings:
        repaired_source["table_matrix_repair_warnings"] = list(
            dict.fromkeys(warnings)
        )
    record_trace("verified")
    return repaired_source, None


def _objective_table_matrix_sha256(matrix: Any) -> str:
    return sha256(
        json.dumps(
            matrix,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _build_objective_table_matrix_repair_payloads(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    paper_facts_extractor: PaperFactsExtractor,
) -> tuple[dict[str, Any], ...]:
    matrix = normalize_table_matrix(source.get("table_matrix"))
    canonical_matrix = _canonical_objective_table_matrix(source=source, matrix=matrix)
    if not canonical_matrix:
        return ()
    headers = canonical_matrix[0]
    body_rows = canonical_matrix[1:]

    def payload(start: int, end: int) -> dict[str, Any]:
        return _build_objective_table_matrix_repair_payload(
            route=route,
            source=source,
            headers=headers,
            body_rows=body_rows,
            start=start,
            end=end,
        )

    estimator = getattr(
        paper_facts_extractor,
        "estimate_table_matrix_repair_prompt_tokens",
        None,
    )
    if not callable(estimator):
        return (payload(0, len(body_rows)),)

    bounded: list[dict[str, Any]] = []

    def append_bounded(start: int, end: int) -> None:
        candidate = payload(start, end)
        if (
            int(estimator(candidate)) <= _TABLE_MATRIX_REPAIR_PROMPT_TOKEN_LIMIT
            or end - start <= 1
        ):
            bounded.append(candidate)
            return
        midpoint = start + max(1, (end - start) // 2)
        append_bounded(start, midpoint)
        append_bounded(midpoint, end)

    append_bounded(0, len(body_rows))
    return tuple(bounded)


def _build_objective_table_matrix_repair_payload(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    headers: list[str],
    body_rows: list[list[str]],
    start: int,
    end: int,
) -> dict[str, Any]:
    first_source_row_index = start + 1
    compact_source = {
        "source_kind": source.get("source_kind"),
        "source_ref": source.get("source_ref"),
        "document_id": source.get("document_id"),
        "page": source.get("page"),
        "caption_text": source.get("caption_text"),
        "heading_path": source.get("heading_path"),
        "column_headers": headers,
        "table_markdown": render_markdown_table(
            [headers, *body_rows[start:end]],
            headers,
            header_row_count=1,
        ),
        "table_visual_text": str(source.get("table_visual_text") or "").strip()
        or None,
        "reading_context": source.get("table_reading_context", []),
        "table_slice": {
            "first_source_row_index": first_source_row_index,
            "end_source_row_index": end + 1,
            "total_body_rows": len(body_rows),
        },
    }
    return {
        "table_role": route.role,
        "repair_focus": [
            "repair parser-split cells",
            "preserve table width",
            "preserve numeric result cells exactly",
        ],
        "source": {
            key: value
            for key, value in compact_source.items()
            if value not in (None, "", [], {})
        },
    }


def _canonical_objective_table_matrix(
    *,
    source: dict[str, Any],
    matrix: list[list[str]],
) -> list[list[str]]:
    if not matrix:
        return []
    headers = [str(value).strip() for value in source.get("column_headers", ())]
    if not any(headers):
        headers = list(matrix[0])
    header_row_count = source.get("header_row_count", 1)
    try:
        body_start = max(0, min(int(header_row_count), len(matrix)))
    except (TypeError, ValueError):
        body_start = 1
    return [headers, *matrix[body_start:]]


def _merge_objective_table_matrix_repairs(
    *,
    source: dict[str, Any],
    canonical_matrix: list[list[str]],
    parsed_repairs: tuple[tuple[dict[str, Any], Any], ...],
) -> list[list[str]]:
    if not canonical_matrix or not parsed_repairs:
        return []
    headers = canonical_matrix[0]
    merged = [headers]
    for _repair_payload, parsed in parsed_repairs:
        repaired_slice = _validated_objective_repaired_table_matrix(
            source={**source, "column_headers": headers},
            repaired_table_matrix=getattr(parsed, "repaired_table_matrix", None),
        )
        if not repaired_slice:
            return []
        slice_rows = repaired_slice[1:] if _objective_row_matches_headers(
            tuple(repaired_slice[0]), tuple(headers)
        ) else repaired_slice
        merged.extend(slice_rows)
    # A layout parser may spill more than one logical row (for example when a
    # wrapped specimen label and its uncertainty land on separate grid rows).
    # The repair contract already verifies column width, source-token
    # conservation, and every numeric column sequence below.  Rejecting every
    # row-count reduction except one therefore discarded valid complete tables
    # for no scientific reason.  Keep only the monotonic bound here: a repair
    # may merge parser fragments, but it may never invent additional rows.
    if len(merged) < 2 or len(merged) > len(canonical_matrix):
        return []
    return merged


def _objective_table_repair_preserves_result_number_sequences(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
) -> bool:
    if not original_matrix or not repaired_matrix:
        return False
    expected_width = len(original_matrix[0])
    if expected_width != len(repaired_matrix[0]):
        return False
    if any(len(row) != expected_width for row in original_matrix):
        return False
    if any(len(row) != expected_width for row in repaired_matrix):
        return False
    return all(
        _objective_column_numeric_tokens(original_matrix, column_index)
        == _objective_column_numeric_tokens(repaired_matrix, column_index)
        for column_index in range(1, expected_width)
    )


_OBJECTIVE_TABLE_TOKEN_PATTERN = re.compile(
    r"[^\W_]+(?:[-_][^\W_]+)*",
    re.UNICODE,
)


def _objective_table_repair_preserves_source_tokens(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    visual_text: str = "",
) -> bool:
    """Reject repair text that cannot be assembled from the supplied table.

    Structural repair may move a parser-spilled label or join adjacent cells, but
    it must not create a new specimen name, process label, or numeric level. A
    multiset check is deliberately conservative: omission is allowed so the
    existing residual-fragment cleanup can remove a carried prefix. If the grid
    lost label characters, the exact ordered labels need independent support
    in the supplied clipped PDF view; other cells cannot acquire new tokens.
    """
    if not original_matrix or not repaired_matrix:
        return False
    original_tokens = Counter(
        token
        for row in original_matrix[1:]
        for cell in row
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(
            " ".join(str(cell or "").split()).casefold()
        )
    )
    repaired_tokens = Counter(
        token
        for row in repaired_matrix[1:]
        for cell in row
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(
            " ".join(str(cell or "").split()).casefold()
        )
    )
    if all(
        repaired_tokens[token] <= original_tokens[token]
        for token in repaired_tokens
    ):
        return True
    if not visual_text.strip():
        return False
    # A parser can omit characters from a wrapped specimen label. Accept
    # them only when every full label is present, in order, in the same
    # table's PDF view. Non-label content still uses the original grid.
    original_values = Counter(
        token for row in original_matrix[1:] for cell in row[1:]
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(cell.casefold())
    )
    repaired_values = Counter(
        token for row in repaired_matrix[1:] for cell in row[1:]
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(cell.casefold())
    )
    if repaired_values - original_values:
        return False
    position = 0
    for row in repaired_matrix[1:]:
        label = re.sub(r"\s+", "", row[0])
        if not label or not any(char.isalpha() for char in label):
            return False
        pattern = (
            r"(?<![\w-])"
            + r"\s*".join(re.escape(char) for char in label)
            + r"(?![\w-])"
        )
        match = re.search(pattern, visual_text[position:], flags=re.IGNORECASE)
        if match is None:
            return False
        position += match.end()
    return True


def _objective_table_repair_preserves_row_label_order(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
) -> bool:
    if not original_matrix or not repaired_matrix:
        return False

    def semantic_label_tokens(matrix: list[list[str]]) -> tuple[str, ...]:
        return tuple(
            token.casefold()
            for row in matrix[1:]
            if row
            for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(str(row[0] or ""))
            if any(character.isalpha() for character in token)
        )

    original_tokens = semantic_label_tokens(original_matrix)
    repaired_tokens = semantic_label_tokens(repaired_matrix)
    return bool(original_tokens) and original_tokens == repaired_tokens


def _objective_column_numeric_tokens(
    matrix: list[list[str]],
    column_index: int,
) -> tuple[str, ...]:
    return tuple(
        match.group(0)
        for row in matrix[1:]
        for match in NUMBER_PATTERN.finditer(str(row[column_index] or ""))
    )


def _rebind_objective_table_mean_uncertainty_columns(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    column_headers: Any,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    if len(repaired_matrix) < 2 or not original_matrix:
        return repaired_matrix, []
    width = len(repaired_matrix[0])
    if width < 2 or any(len(row) != width for row in repaired_matrix):
        return repaired_matrix, []
    if any(len(row) != width for row in original_matrix):
        return repaired_matrix, []

    body_row_count = len(repaired_matrix) - 1
    headers = [str(value).strip() for value in column_headers or ()]
    rebound_matrix = [list(row) for row in repaired_matrix]
    repairs: list[dict[str, Any]] = []
    for column_index in range(1, width):
        source_cells = [row[column_index] for row in original_matrix[1:]]
        source_tokens = _objective_column_numeric_tokens(
            original_matrix,
            column_index,
        )
        if len(source_tokens) != body_row_count * 2:
            continue
        if not any(
            len(tuple(NUMBER_PATTERN.finditer(cell))) != 2
            for cell in source_cells
        ):
            continue
        uncertainty_cell_count = sum(
            1
            for cell in source_cells
            if re.search(r"(?:±|\+/-|\+-)", cell)
        )
        if uncertainty_cell_count < max(2, body_row_count // 2):
            continue
        repaired_cells = [row[column_index] for row in repaired_matrix[1:]]

        for body_index, repaired_cell in enumerate(repaired_cells):
            expected_tokens = source_tokens[body_index * 2 : body_index * 2 + 2]
            actual_tokens = tuple(
                match.group(0) for match in NUMBER_PATTERN.finditer(repaired_cell)
            )
            if actual_tokens == expected_tokens:
                continue
            rebound = f"{expected_tokens[0]} ( ± {expected_tokens[1]})"
            rebound_matrix[body_index + 1][column_index] = rebound
            repairs.append(
                {
                    "row_index": body_index + 1,
                    "column": (
                        headers[column_index]
                        if column_index < len(headers)
                        else str(column_index)
                    ),
                    "before": repaired_cell,
                    "after": rebound,
                    "reason": (
                        "Rebound a parser-split uncertainty using the complete "
                        "top-to-bottom numeric sequence of this result column."
                    ),
                }
            )
    return rebound_matrix, repairs


def _validated_objective_repaired_table_matrix(
    *,
    source: dict[str, Any],
    repaired_table_matrix: Any,
) -> list[list[str]]:
    if not isinstance(repaired_table_matrix, list) or not repaired_table_matrix:
        return []
    headers = [
        str(header).strip()
        for header in source.get("column_headers", ())
        if str(header).strip()
    ]
    expected_width = len(headers)
    repaired_rows: list[list[str]] = []
    for row in repaired_table_matrix:
        if not isinstance(row, (list, tuple)):
            return []
        repaired_row = [str(cell).strip() for cell in row]
        if expected_width and len(repaired_row) != expected_width:
            return []
        repaired_rows.append(repaired_row)
    if expected_width and not _objective_row_matches_headers(
        tuple(repaired_rows[0]),
        tuple(headers),
    ):
        repaired_rows.insert(0, headers)
    return repaired_rows


def normalize_table_matrix(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [
        [str(cell).strip() for cell in row]
        for row in value
        if isinstance(row, (list, tuple))
    ]


def _cleanup_objective_repaired_table_matrix_residual_fragments(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    column_headers: Any,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    if not original_matrix or not repaired_matrix:
        return repaired_matrix, []
    headers = [str(value).strip() for value in column_headers or ()]
    cleaned_matrix: list[list[str]] = []
    repairs: list[dict[str, Any]] = []
    for row_index, repaired_row in enumerate(repaired_matrix):
        original_row = (
            original_matrix[row_index] if row_index < len(original_matrix) else []
        )
        cleaned_row: list[str] = []
        for col_index, repaired_cell in enumerate(repaired_row):
            original_cell = (
                original_row[col_index] if col_index < len(original_row) else ""
            )
            cleaned_cell = _cleanup_objective_repaired_cell_residual_prefix(
                original_cell=original_cell,
                repaired_cell=repaired_cell,
            )
            cleaned_row.append(cleaned_cell)
            if cleaned_cell != repaired_cell:
                repairs.append(
                    {
                        "row_index": row_index,
                        "column": (
                            headers[col_index]
                            if col_index < len(headers)
                            else str(col_index)
                        ),
                        "before": repaired_cell,
                        "after": cleaned_cell,
                        "reason": (
                            "Removed a leading closing-fragment prefix that "
                            "belonged to the previous parser-split row label."
                        ),
                    }
                )
        cleaned_matrix.append(cleaned_row)
    return cleaned_matrix, repairs


def _cleanup_objective_repaired_cell_residual_prefix(
    *,
    original_cell: str,
    repaired_cell: str,
) -> str:
    original = " ".join(str(original_cell or "").split())
    repaired = " ".join(str(repaired_cell or "").split())
    if not original or not repaired:
        return repaired_cell
    if not _objective_cell_text_looks_structurally_fragmented(original):
        return repaired_cell
    match = re.match(r"^([^\s()[\]{}|]{1,32}\))\s+(.+)$", original)
    if match is None:
        return repaired_cell
    prefix = f"{match.group(1)} "
    original_remainder = match.group(2).strip()
    if not _objective_cell_text_looks_structurally_fragmented(original_remainder):
        return repaired_cell
    if not repaired.startswith(prefix):
        return repaired_cell
    candidate = repaired[len(prefix) :].strip()
    if not candidate:
        return repaired_cell
    if _objective_cell_text_looks_structurally_fragmented(candidate):
        return repaired_cell
    return candidate


def _objective_table_matrix_has_structural_fragments(
    table_matrix: list[list[str]],
) -> bool:
    return any(
        _objective_cell_text_looks_structurally_fragmented(cell)
        for row in table_matrix
        for cell in row
    )


def _objective_table_source_needs_llm_structural_repair(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
) -> bool:
    if route.source_kind != "table":
        return False
    if route.role not in {
        "current_experimental_evidence",
        "process_or_treatment",
        "condition_context",
    }:
        return False
    matrix = source.get("table_matrix")
    if isinstance(matrix, list) and _objective_table_matrix_has_structural_fragments(
        normalize_table_matrix(matrix)
    ):
        return True
    cells = source.get("table_cells")
    if not isinstance(cells, list):
        return False
    return any(
        _objective_cell_text_looks_structurally_fragmented(
            str(cell.get("cell_text") or "")
        )
        for cell in cells
        if isinstance(cell, dict)
    )


def _objective_cell_text_looks_structurally_fragmented(text: str) -> bool:
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if value.count("(") != value.count(")"):
        return True
    if value.count("[") != value.count("]"):
        return True
    if value.endswith(("/", "(", "[", "{")):
        return True
    if value.startswith((")", "]", "}")):
        return True
    return False

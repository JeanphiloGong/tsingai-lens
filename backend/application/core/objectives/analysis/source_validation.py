"""Validate model-authored facts against their exact Source."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from domain.core import ResearchObjective

OBJECTIVE_SOURCE_GROUNDING_VERSION = "objective-source-grounding.v1"

_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_NO_CHANGE_RESULT_KEYS = (
    "no_change",
    "no_significant_change",
    "no_significant_difference",
    "no_statistically_significant_difference",
    "not_significantly_different",
    "not_statistically_different",
    "remained_constant",
    "remained_relatively_unchanged",
    "remained_unchanged",
    "unchanged",
)


def _objective_table_matrix_rows(
    source: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[tuple[int, tuple[str, ...]], ...]]:
    headers = tuple(
        str(header).strip()
        for header in source.get("column_headers", ())
        if str(header).strip()
    )
    matrix = tuple(
        tuple(str(cell).strip() for cell in row)
        for row in source.get("table_matrix", ())
        if isinstance(row, (list, tuple))
    )
    if not headers or not matrix:
        return (), ()
    candidate_rows = (
        matrix[1:] if _objective_row_matches_headers(matrix[0], headers) else matrix
    )
    filtered_rows = tuple(
        row
        for row in candidate_rows
        if any(cell for cell in row)
        and not _objective_table_matrix_continuation_header_row(
            headers=headers,
            row=row,
        )
    )
    data_rows = tuple(
        (row_index, row) for row_index, row in enumerate(filtered_rows, start=1)
    )
    return headers, data_rows


def _objective_table_matrix_continuation_header_row(
    *,
    headers: tuple[str, ...],
    row: tuple[str, ...],
) -> bool:
    if not headers or not row:
        return False
    first_header_key = _objective_column_key(headers[0])
    if first_header_key not in {"sample", "sample_id", "sample_number"}:
        return False
    first_cell = str(row[0] if row else "").strip()
    matches_header = _objective_column_key(first_cell) == first_header_key
    continues_header = not first_cell and any(str(cell).strip() for cell in row[1:])
    return matches_header or continues_header


def _objective_row_matches_headers(
    row: tuple[str, ...],
    headers: tuple[str, ...],
) -> bool:
    return tuple(
        _objective_column_key(value) for value in row[: len(headers)]
    ) == tuple(_objective_column_key(value) for value in headers)


def _objective_table_row_values(
    *,
    headers: tuple[str, ...],
    row: tuple[str, ...],
) -> dict[str, str]:
    return {
        header: row[index]
        for index, header in enumerate(headers)
        if index < len(row) and row[index] not in (None, "")
    }


def validate_source_fact(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    extracted_record: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    record = _objective_complete_extracted_variable_endpoints(
        extracted_record,
        source=source,
    )
    record = _objective_retain_source_grounded_context(
        record,
        source=source,
    )
    record = _objective_recover_source_bound_objective_material(
        record,
        source=source,
        objective_context=objective_context,
    )
    record = _objective_normalize_explicit_no_change_direction(record)
    reported_result = record.get("reported_result")
    if isinstance(reported_result, Mapping):
        normalized_result = dict(reported_result)
        result_value = normalized_result.get("value")
        direction = str(normalized_result.get("direction") or "unknown")
        result_text = (
            f"_{_objective_column_key(result_value)}_"
            f"{_objective_column_key(normalized_result.get('result_text'))}_"
        )
        direction_terms = {
            "increase": (
                "increase",
                "increased",
                "increases",
                "increasing",
                "higher",
                "greater",
                "larger",
                "more",
            ),
            "decrease": (
                "decrease",
                "decreased",
                "decreases",
                "decreasing",
                "lower",
                "less",
                "reduce",
                "reduced",
                "reduces",
                "reducing",
                "reduction",
                "smaller",
            ),
            "improve": (
                "improve",
                "improved",
                "improves",
                "improving",
                "better",
                "enhance",
                "enhanced",
            ),
            "worsen": (
                "worsen",
                "worsened",
                "worsens",
                "worsening",
                "worse",
                "degrade",
                "degraded",
                "deteriorate",
                "deteriorated",
            ),
            "no_change": (
                "no_change",
                "no_significant_difference",
                "similar",
                "unchanged",
                "remained_constant",
            ),
        }
        explicit_directions = [
            candidate_direction
            for candidate_direction, terms in direction_terms.items()
            if any(f"_{term}_" in result_text for term in terms)
        ]
        if direction == "unknown" and len(explicit_directions) == 1:
            direction = explicit_directions[0]
            normalized_result["direction"] = direction
        if (
            not _NUMBER_PATTERN.search(str(result_value or ""))
            and direction in direction_terms
            and not any(
                f"_{term}_" in result_text for term in direction_terms[direction]
            )
        ):
            normalized_result["direction"] = "unknown"
        record["reported_result"] = normalized_result
        reported_result = normalized_result
    if not isinstance(reported_result, Mapping):
        record["changed_variables"] = []
        record["comparison"] = None
    if isinstance(reported_result, Mapping):
        source_text = _objective_source_grounding_text(source)
        result_grounding_errors = _objective_evidence_result_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        )
        if result_grounding_errors:
            return ()
        variable_grounding_errors = _objective_evidence_variable_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        )
        comparison_grounding_errors = _objective_evidence_comparison_grounding_errors(
            record,
            source_text=source_text,
        )
        if (
            not variable_grounding_errors
            and not comparison_grounding_errors
            and source.get("source_kind") == "table"
            and source.get("table_matrix")
            and not _objective_extracted_table_result_is_row_grounded(
                record,
                source=source,
            )
        ):
            return ()
        if variable_grounding_errors or comparison_grounding_errors:
            record["changed_variables"] = []
            record["resolution_status"] = "partial"
            if comparison_grounding_errors:
                record["comparison"] = None
                record["attribution_scope"] = "descriptive_only"
                record["selection_reason"] = (
                    "Grounded result retained without a source-grounded "
                    "comparison binding."
                )
            else:
                comparison = record.get("comparison")
                record["attribution_scope"] = (
                    "association_only"
                    if isinstance(comparison, Mapping)
                    and comparison.get("comparable") is True
                    else "not_attributable"
                )
                record["selection_reason"] = (
                    "Grounded result retained pending same-study process "
                    "context binding."
                )
        outcome = property_matching.normalize_objective_unit_property(
            reported_result.get("outcome"),
            objective_context=objective_context,
        )
        if not outcome:
            return ()
        if (
            objective_context is not None
            and objective_context.outcomes
            and not property_matching.property_matches_target_axes(
                outcome,
                target_axes=property_matching.objective_outcomes(objective_context),
            )
        ):
            return ()
        normalized_result = dict(reported_result)
        normalized_result["outcome"] = outcome
        record["reported_result"] = normalized_result
    else:
        scientific_context = record.get("scientific_context")
        if not isinstance(scientific_context, Mapping) or not any(
            scientific_context.get(group)
            for group in ("material", "sample", "process", "test")
        ):
            return ()
    supported_fields: list[str] = []
    if record.get("changed_variables"):
        supported_fields.extend(("changed_variables", "comparison.axis_names"))
    if isinstance(record.get("comparison"), Mapping):
        supported_fields.append("comparison.labels")
    if isinstance(record.get("reported_result"), Mapping):
        supported_fields.append("reported_result")
    scientific_context = record.get("scientific_context")
    if isinstance(scientific_context, Mapping):
        supported_fields.extend(
            f"scientific_context.{group}"
            for group in ("material", "sample", "process", "test")
            if scientific_context.get(group)
        )
    record.update(
        {
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_refs": _objective_route_source_refs(
                route=route,
                source=source,
                source_excerpt=(
                    _objective_source_grounding_text(source)
                    if source.get("source_kind") == "text_window"
                    and isinstance(record.get("reported_result"), Mapping)
                    and not isinstance(record.get("comparison"), Mapping)
                    else None
                ),
                supports=tuple(supported_fields),
            ),
        }
    )
    if record.get("confidence") is None:
        record["confidence"] = route.confidence
    return (record,)


def _objective_normalize_explicit_no_change_direction(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(record)
    result = normalized.get("reported_result")
    if not isinstance(result, Mapping):
        return normalized

    normalized_result = dict(result)
    result_text = str(normalized_result.get("result_text") or "").strip()
    result_key = _objective_column_key(result_text)
    explicitly_unchanged = any(
        phrase in result_key for phrase in _NO_CHANGE_RESULT_KEYS
    )
    if not explicitly_unchanged:
        return normalized
    if str(normalized_result.get("direction") or "unknown") == "unknown":
        normalized_result["direction"] = "no_change"
        normalized["reported_result"] = normalized_result
    return normalized


def _objective_complete_extracted_variable_endpoints(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    completed = dict(record)
    variables = completed.get("changed_variables")
    comparison = completed.get("comparison")
    if (
        not isinstance(variables, list)
        or len(variables) != 1
        or not isinstance(variables[0], Mapping)
        or not isinstance(comparison, Mapping)
    ):
        return completed
    variable = dict(variables[0])
    axis_names = comparison.get("axis_names")
    if (
        not isinstance(axis_names, list)
        or len(axis_names) != 1
        or not property_matching.axis_values_match(
            str(variable.get("name") or ""),
            str(axis_names[0] or ""),
        )
    ):
        return completed
    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return completed
    endpoints = (
        ("baseline_value", comparison.get("baseline_label")),
        ("target_value", comparison.get("target_label")),
    )
    comparison_labels_are_grounded = all(
        str(label or "").strip()
        and property_matching.axis_label_is_mentioned(
            source_text,
            str(label).strip(),
        )
        for _field, label in endpoints
    )
    variable_unit = str(variable.get("unit") or "").strip()
    variable_values_are_grounded = all(
        _objective_value_is_source_grounded(variable.get(field), source_text)
        for field, _label in endpoints
    )
    variable_unit_is_grounded = not variable_unit or (
        _objective_column_key(variable_unit) in _objective_column_key(source_text)
    )
    if comparison_labels_are_grounded and (
        not variable_values_are_grounded or not variable_unit_is_grounded
    ):
        for field, label in endpoints:
            variable[field] = str(label).strip()
        variable["unit"] = None
        completed["changed_variables"] = [variable]
        return completed
    for field, label in endpoints:
        label_text = str(label or "").strip()
        if (
            variable.get(field) in (None, "")
            and label_text
            and property_matching.axis_label_is_mentioned(source_text, label_text)
        ):
            variable[field] = label_text
    if variable.get("baseline_value") == variable.get("target_value"):
        return completed
    completed["changed_variables"] = [variable]
    return completed


def _objective_extracted_result_is_source_grounded(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> bool:
    return not _objective_evidence_grounding_errors(record, source=source)


def _objective_evidence_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return ("source has no text or table content for grounding",)
    errors = [
        *_objective_evidence_variable_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        ),
        *_objective_evidence_comparison_grounding_errors(
            record,
            source_text=source_text,
        ),
        *_objective_evidence_result_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        ),
    ]
    if (
        not errors
        and source.get("source_kind") == "table"
        and source.get("table_matrix")
        and record.get("reported_result") is not None
        and not _objective_extracted_table_result_is_row_grounded(
            record,
            source=source,
        )
    ):
        errors.append(
            "table_rows do not bind the reported result to the selected "
            "comparison endpoints in SOURCE"
        )
    return tuple(errors)


def _objective_evidence_variable_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
) -> tuple[str, ...]:
    errors: list[str] = []
    for position, variable in enumerate(record.get("changed_variables") or ()):
        path = f"changed_variables[{position}]"
        if not isinstance(variable, Mapping):
            errors.append(f"{path} is not a structured variable")
            continue
        if not _objective_axis_is_source_grounded(
            variable.get("name"),
            source=source,
            source_text=source_text,
        ):
            errors.append(
                f"{path}.name={variable.get('name')!r} is not grounded in SOURCE"
            )
        for field in ("baseline_value", "target_value"):
            value = variable.get(field)
            if not _objective_value_is_source_grounded(value, source_text):
                errors.append(f"{path}.{field}={value!r} is not grounded in SOURCE")
        variable_unit = str(variable.get("unit") or "").strip()
        if variable_unit and _objective_column_key(
            variable_unit
        ) not in _objective_column_key(source_text):
            errors.append(f"{path}.unit={variable_unit!r} is not grounded in SOURCE")
    return tuple(errors)


def _objective_evidence_comparison_grounding_errors(
    record: Mapping[str, Any],
    *,
    source_text: str,
) -> tuple[str, ...]:
    comparison = record.get("comparison")
    if not isinstance(comparison, Mapping):
        return ()
    errors: list[str] = []
    for field in ("baseline_label", "target_label"):
        value = comparison.get(field)
        if not _objective_value_is_source_grounded(value, source_text):
            errors.append(f"comparison.{field}={value!r} is not grounded in SOURCE")
    return tuple(errors)


def _objective_evidence_result_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
) -> tuple[str, ...]:
    reported_result = record.get("reported_result")
    if not isinstance(reported_result, Mapping):
        return ()
    errors: list[str] = []
    outcome = reported_result.get("outcome")
    if not _objective_axis_is_source_grounded(
        outcome,
        source=source,
        source_text=source_text,
    ):
        errors.append(f"reported_result.outcome={outcome!r} is not grounded in SOURCE")
    unit = str(reported_result.get("unit") or "").strip()
    if unit and _objective_column_key(unit) not in _objective_column_key(source_text):
        errors.append(f"reported_result.unit={unit!r} is not grounded in SOURCE")
    for field in ("value", "baseline_value", "target_value"):
        result_value = reported_result.get(field)
        if result_value in (None, "") or _objective_value_is_source_grounded(
            result_value,
            source_text,
        ):
            continue
        errors.append(
            f"reported_result.{field}={result_value!r} is not grounded in SOURCE"
        )
    result_text = str(reported_result.get("result_text") or "").strip()
    if _NUMBER_PATTERN.search(result_text):
        result_text_is_grounded = _objective_value_is_source_grounded(
            result_text,
            source_text,
        )
    else:
        result_text_is_grounded = property_matching.axis_label_is_mentioned(
            source_text,
            result_text,
        )
    if not result_text_is_grounded:
        errors.append(
            f"reported_result.result_text={result_text!r} is not grounded in SOURCE"
        )
    return tuple(errors)


def _objective_extracted_table_result_is_row_grounded(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> bool:
    headers, data_rows = _objective_table_matrix_rows(dict(source))
    reported_result = record.get("reported_result")
    if not headers or not data_rows or not isinstance(reported_result, Mapping):
        return False
    outcome = str(reported_result.get("outcome") or "").strip()
    result_unit = _objective_column_key(str(reported_result.get("unit") or ""))
    outcome_headers: list[str] = []
    for header in headers:
        property_name, header_unit = _split_property_unit(header)
        if not property_matching.axis_values_match(property_name, outcome):
            continue
        if (
            result_unit
            and header_unit
            and (_objective_column_key(header_unit) != result_unit)
        ):
            continue
        outcome_headers.append(header)
    if not outcome_headers:
        return False

    variable_headers: dict[str, tuple[str, ...]] = {}
    for variable in record.get("changed_variables") or ():
        if not isinstance(variable, Mapping):
            return False
        name = str(variable.get("name") or "").strip()
        matching_headers = tuple(
            header
            for header in headers
            if property_matching.axis_values_match(
                _split_property_unit(header)[0],
                name,
            )
            or any(
                property_matching.axis_values_match(axis, name)
                for axis in property_matching.process_column_axis_keys(header)
            )
        )
        if not matching_headers:
            return False
        variable_headers[name] = matching_headers

    row_values = [
        _objective_table_row_values(headers=headers, row=row)
        for _row_index, row in data_rows
    ]

    def matching_rows(value_field: str) -> list[dict[str, str]]:
        matches: list[dict[str, str]] = []
        for values in row_values:
            if all(
                any(
                    _objective_table_cell_matches_value(
                        values.get(header),
                        variable.get(value_field),
                    )
                    for header in variable_headers[
                        str(variable.get("name") or "").strip()
                    ]
                )
                for variable in record.get("changed_variables") or ()
                if isinstance(variable, Mapping)
            ):
                matches.append(values)
        return matches

    baseline_rows = matching_rows("baseline_value")
    target_rows = matching_rows("target_value")
    if record.get("changed_variables") and (not baseline_rows or not target_rows):
        return False
    if not target_rows:
        target_rows = row_values
    if not baseline_rows:
        baseline_rows = target_rows
    for baseline in baseline_rows:
        for target in target_rows:
            if not any(
                _objective_value_is_source_grounded(
                    reported_result.get("value"),
                    target.get(header, ""),
                )
                for header in outcome_headers
            ):
                continue
            bound_text = "\n".join(
                str(value) for value in (*baseline.values(), *target.values())
            )
            result_text = str(reported_result.get("result_text") or "")
            if not _NUMBER_PATTERN.search(
                result_text
            ) or _objective_value_is_source_grounded(result_text, bound_text):
                return True
    return False


def _objective_retain_source_grounded_context(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    grounded_record = dict(record)
    scientific_context = record.get("scientific_context")
    if not isinstance(scientific_context, Mapping):
        grounded_record["scientific_context"] = {
            "material": [],
            "sample": [],
            "process": [],
            "test": [],
        }
        return grounded_record
    source_text = _objective_source_grounding_text(source)
    grounded_context: dict[str, list[dict[str, Any]]] = {}
    for group in ("material", "sample", "process", "test"):
        grounded_attributes: list[dict[str, Any]] = []
        for attribute in scientific_context.get(group) or ():
            if not isinstance(attribute, Mapping):
                continue
            if not _objective_axis_is_source_grounded(
                attribute.get("name"),
                source=source,
                source_text=source_text,
            ):
                continue
            value = attribute.get("value")
            if value not in (None, "") and not _objective_value_is_source_grounded(
                value,
                source_text,
            ):
                continue
            unit = str(attribute.get("unit") or "").strip()
            if unit and _objective_column_key(unit) not in _objective_column_key(
                source_text
            ):
                continue
            grounded_attributes.append(dict(attribute))
        grounded_context[group] = grounded_attributes
    grounded_record["scientific_context"] = grounded_context
    return grounded_record


def _objective_recover_source_bound_objective_material(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> dict[str, Any]:
    recovered = dict(record)
    scientific_context = recovered.get("scientific_context")
    if (
        objective_context is None
        or not objective_context.material_scope
        or not isinstance(record.get("reported_result"), Mapping)
        or not isinstance(scientific_context, Mapping)
        or scientific_context.get("material")
    ):
        return recovered

    reported_result = record["reported_result"]
    binding_text = "\n".join(
        value
        for value in (
            str(source.get("heading_path") or "").strip(),
            str(source.get("caption_text") or "").strip(),
            str(reported_result.get("result_text") or "").strip(),
        )
        if value
    )
    matching_materials = tuple(
        material
        for material in objective_context.material_scope
        if property_matching.axis_label_is_mentioned(binding_text, material)
        or property_matching.material_value_matches_objective_comparison_scope(
            binding_text,
            material,
        )
    )
    if len(matching_materials) != 1:
        return recovered

    context = {
        group: [dict(item) for item in scientific_context.get(group) or ()]
        for group in ("material", "sample", "process", "test")
    }
    context["material"] = [
        {
            "name": "material",
            "value": matching_materials[0],
            "unit": None,
        }
    ]
    recovered["scientific_context"] = context
    return recovered


def _objective_table_cell_matches_value(cell: Any, value: Any) -> bool:
    if value in (None, ""):
        return True
    cell_text = str(cell or "").strip()
    value_text = str(value).strip()
    if not cell_text:
        return False
    if _NUMBER_PATTERN.search(value_text):
        return _objective_value_is_source_grounded(
            value_text,
            cell_text,
        )
    cell_key = _objective_column_key(cell_text)
    value_key = _objective_column_key(value_text)
    return bool(cell_key and value_key and cell_key == value_key)


def _objective_axis_is_source_grounded(
    value: Any,
    *,
    source: Mapping[str, Any],
    source_text: str,
) -> bool:
    axis = str(value or "").strip()
    if not axis:
        return False
    if property_matching.source_text_mentions_axis(source_text, axis):
        return True
    labels = [
        *source.get("column_headers", ()),
        *(
            cell.get("header_path")
            for cell in source.get("table_cells", ())
            if isinstance(cell, Mapping)
        ),
    ]
    for label in labels:
        label_text = str(label or "").strip()
        if not label_text:
            continue
        symbol_axes = property_matching.process_column_axis_keys(label_text)
        if any(property_matching.axis_values_match(axis, item) for item in symbol_axes):
            return True
        if (
            property_matching.axis_values_match(label_text, axis)
            or property_matching.axis_label_is_mentioned(label_text, axis)
            or property_matching.axis_label_is_mentioned(axis, label_text)
        ):
            return True
    return any(
        property_matching.axis_values_match(token, axis)
        for token in re.findall(r"[A-Za-z\u0370-\u03ff]+", source_text)
    )


def _objective_source_grounding_text(source: Mapping[str, Any]) -> str:
    values: list[str] = []
    for field in ("text", "caption_text", "heading_path"):
        value = str(source.get(field) or "").strip()
        if value:
            values.append(value)
    values.extend(
        str(value).strip()
        for value in source.get("column_headers", ())
        if str(value).strip()
    )
    values.extend(
        str(cell).strip()
        for row in source.get("table_matrix", ())
        if isinstance(row, (list, tuple))
        for cell in row
        if str(cell).strip()
    )
    values.extend(
        str(cell.get("cell_text") or "").strip()
        for cell in source.get("table_cells", ())
        if isinstance(cell, Mapping) and str(cell.get("cell_text") or "").strip()
    )
    return "\n".join(values)


def _objective_value_is_source_grounded(value: Any, source_text: str) -> bool:
    expected = {
        float(match.group(0))
        for match in _NUMBER_PATTERN.finditer(
            str("" if value is None else value).replace(",", "").replace("\u2212", "-")
        )
    }
    if not expected:
        value_key = _objective_column_key(str("" if value is None else value))
        source_key = _objective_column_key(source_text)
        return bool(value_key and value_key in source_key)
    actual = {
        float(match.group(0))
        for match in _NUMBER_PATTERN.finditer(
            source_text.replace(",", "").replace("\u2212", "-")
        )
    }
    return expected <= actual


def _objective_column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _split_property_unit(value: str) -> tuple[str, str | None]:
    text = str(value or "").strip()
    text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
    if text.endswith("]") and "[" in text:
        name, _, suffix = text.rpartition("[")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    if text.endswith(")") and "(" in text:
        name, _, suffix = text.rpartition("(")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    return text, None


def _objective_route_source_refs(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    row_index: int | None = None,
    col_index: int | None = None,
    header_path: str | None = None,
    source_excerpt: str | None = None,
    supports: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    ref = {
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "role": route.role,
        "evidence_role": route.join_plan.get("evidence_role"),
        "page": source.get("page"),
        "row_index": row_index,
        "col_index": col_index,
        "header_path": header_path,
        "source_excerpt": source_excerpt,
        "supports": list(supports),
    }
    return (
        {key: value for key, value in ref.items() if value not in (None, "", [], {})},
    )

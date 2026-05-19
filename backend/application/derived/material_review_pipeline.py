from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from infra.persistence.file._json import write_json


StageCallback = Callable[[str, str], None]

_EVIDENCE_ID_PATTERN = re.compile(r"\bE\d{2,}\b")
_JSON_FENCE_PATTERN = re.compile(r"^```(?:json|markdown)?\s*|\s*```$", re.DOTALL)
_NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_MAX_TABLE_ROWS = 80
_MAX_REVISION_ROUNDS = 2

_PROCESS_PARAMETER_ORDER = [
    "energy_density_j_mm3",
    "laser_power_w",
    "scan_speed_mm_s",
    "hatch_spacing_um",
    "layer_thickness_um",
    "scan_strategy",
]
_CORE_PROPERTY_ORDER = [
    "density",
    "hardness",
    "yield_strength",
    "tensile_strength",
    "elongation",
]
_PROPERTY_ALIASES = {
    "relative_density": "density",
    "density": "density",
    "hardness": "hardness",
    "yield_strength": "yield_strength",
    "tensile_strength": "tensile_strength",
    "elongation": "elongation",
}
_PROCESS_PARAMETER_LABELS = {
    "zh": {
        "energy_density_j_mm3": "能量密度 (J/mm3)",
        "laser_power_w": "激光功率 (W)",
        "scan_speed_mm_s": "扫描速度",
        "hatch_spacing_um": "道间距 (um)",
        "layer_thickness_um": "层厚 (um)",
        "scan_strategy": "扫描策略",
    },
    "en": {
        "energy_density_j_mm3": "Energy density (J/mm3)",
        "laser_power_w": "Laser power (W)",
        "scan_speed_mm_s": "Scan speed",
        "hatch_spacing_um": "Hatch spacing (um)",
        "layer_thickness_um": "Layer thickness (um)",
        "scan_strategy": "Scan strategy",
    },
}
_PROPERTY_LABELS = {
    "zh": {
        "density": "致密度",
        "hardness": "硬度",
        "yield_strength": "屈服强度",
        "tensile_strength": "抗拉强度",
        "elongation": "延伸率",
    },
    "en": {
        "density": "Density",
        "hardness": "Hardness",
        "yield_strength": "Yield strength",
        "tensile_strength": "Tensile strength",
        "elongation": "Elongation",
    },
}
_GENERIC_PATTERNS = [
    "significant impact",
    "significant effect",
    "significant difference",
    "complex relationship",
    "显著影响",
    "显著差异",
    "复杂关系",
    "重要影响",
]
_SINGLE_PAPER_OVERSTATEMENTS = [
    "cross-paper consensus",
    "literature consensus",
    "studies consistently",
    "the literature shows",
    "跨文献一致",
    "文献一致表明",
    "已有大量研究",
    "广泛研究表明",
]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _markdown_cell(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return "--"
    return text.replace("|", "\\|").replace("\n", "<br>")


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    header_line = "| " + " | ".join(_markdown_cell(header) for header in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    row_lines = [
        "| " + " | ".join(_markdown_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator, *row_lines])


def _process_parameter_label(key: str, language: str) -> str:
    labels = _PROCESS_PARAMETER_LABELS.get(language, _PROCESS_PARAMETER_LABELS["en"])
    return labels.get(key, key.replace("_", " "))


def _property_label(key: str, language: str) -> str:
    labels = _PROPERTY_LABELS.get(language, _PROPERTY_LABELS["en"])
    return labels.get(key, key.replace("_", " "))


def _canonical_property_name(value: Any) -> str:
    text = _safe_text(value)
    normalized = text.lower()
    normalized = normalized.replace("-", "_").replace("/", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    if "relative_density" in normalized:
        return "density"
    if "density" in normalized and "energy" not in normalized:
        return "density"
    if "hardness" in normalized or normalized in {"hv", "vickers"}:
        return "hardness"
    if "yield" in normalized:
        return "yield_strength"
    if "tensile" in normalized or "uts" in normalized:
        return "tensile_strength"
    if "elongation" in normalized or "ductility" in normalized:
        return "elongation"
    return _PROPERTY_ALIASES.get(normalized, text)


def _property_sort_key(key: str) -> tuple[int, str]:
    return (
        _CORE_PROPERTY_ORDER.index(key)
        if key in _CORE_PROPERTY_ORDER
        else len(_CORE_PROPERTY_ORDER),
        key,
    )


def _process_sort_key(key: str) -> tuple[int, str]:
    return (
        _PROCESS_PARAMETER_ORDER.index(key)
        if key in _PROCESS_PARAMETER_ORDER
        else len(_PROCESS_PARAMETER_ORDER),
        key,
    )


def _extract_number(value: Any) -> float | None:
    match = _NUMBER_PATTERN.search(_safe_text(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _evidence_label(evidence_ids: Any) -> str:
    ids = [_safe_text(item) for item in _safe_list(evidence_ids) if _safe_text(item)]
    return f"[{', '.join(ids)}]" if ids else ""


def _collect_evidence_ids(payload: Any) -> set[str]:
    if isinstance(payload, dict):
        ids: set[str] = set()
        for key, value in payload.items():
            if key == "evidence_ids":
                ids.update(_safe_text(item) for item in _safe_list(value) if _safe_text(item))
            else:
                ids.update(_collect_evidence_ids(value))
        return ids
    if isinstance(payload, list):
        ids: set[str] = set()
        for item in payload:
            ids.update(_collect_evidence_ids(item))
        return ids
    return set()


def _coerce_message_content(content: Any) -> str:
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


class MaterialReviewDataPackBuilder:
    """Build a writing-oriented data pack from the material review context."""

    def build(self, context_pack: dict[str, Any]) -> dict[str, Any]:
        sample_rows = self._sample_rows(context_pack)
        sample_by_id = {
            _safe_text(row.get("sample_id")): row
            for row in sample_rows
            if _safe_text(row.get("sample_id"))
        }
        property_rows = self._property_rows(context_pack, sample_by_id)
        process_parameters = self._process_parameter_keys(context_pack, sample_rows)
        property_ranges = self._property_ranges(property_rows)
        paired_comparisons = self._paired_comparisons(property_ranges)
        trend_candidates = self._trend_candidates(paired_comparisons)
        evidence_index = {
            _safe_text(item.get("id")): item
            for item in _safe_list(context_pack.get("evidence_table"))
            if _safe_text(_safe_dict(item).get("id"))
        }
        literature_scope = self._literature_scope(context_pack)
        quality_flags = self._quality_flags(
            literature_scope=literature_scope,
            sample_rows=sample_rows,
            property_rows=property_rows,
            property_ranges=property_ranges,
            comparison_clusters=_safe_list(context_pack.get("comparison_clusters")),
            evidence_index=evidence_index,
        )
        return {
            "material": deepcopy(_safe_dict(context_pack.get("material"))),
            "literature_scope": literature_scope,
            "sample_design": {
                "sample_count": len(sample_rows),
                "process_parameters": process_parameters,
                "process_parameter_space": self._process_parameter_space(
                    process_parameters,
                    sample_rows,
                ),
                "sample_rows": sample_rows,
            },
            "property_matrix": {
                "property_count": len(property_rows),
                "properties": sorted(
                    {
                        _safe_text(row.get("property"))
                        for row in property_rows
                        if _safe_text(row.get("property"))
                    },
                    key=_property_sort_key,
                ),
                "rows": property_rows,
            },
            "comparison_clusters": deepcopy(
                _safe_list(context_pack.get("comparison_clusters"))
            ),
            "computed_summaries": {
                "property_ranges": property_ranges,
                "best_values": [
                    deepcopy(item["max"])
                    for item in property_ranges
                    if _safe_dict(item.get("max"))
                ],
                "worst_values": [
                    deepcopy(item["min"])
                    for item in property_ranges
                    if _safe_dict(item.get("min"))
                ],
                "paired_comparisons": paired_comparisons,
                "trend_candidates": trend_candidates,
            },
            "evidence_index": evidence_index,
            "limitations": deepcopy(_safe_list(context_pack.get("limitations"))),
            "research_gaps": deepcopy(_safe_list(context_pack.get("research_gaps"))),
            "quality_flags": quality_flags,
        }

    def _sample_rows(self, context_pack: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(_safe_list(context_pack.get("sample_process_matrix")), 1):
            record = _safe_dict(row)
            sample_id = _safe_text(record.get("sample_id")) or f"S{index:03d}"
            rows.append(
                {
                    "sample_id": sample_id,
                    "paper": _safe_text(record.get("paper")) or "--",
                    "material": _safe_text(record.get("material"))
                    or _safe_text(_safe_dict(context_pack.get("material")).get("canonical_name")),
                    "variable_axis": _safe_text(record.get("variable_axis")),
                    "variable_value": record.get("variable_value"),
                    "process_parameters": deepcopy(
                        _safe_dict(record.get("process_parameters"))
                    ),
                    "evidence_ids": [
                        _safe_text(item)
                        for item in _safe_list(record.get("evidence_ids"))
                        if _safe_text(item)
                    ],
                }
            )
        return rows

    def _property_rows(
        self,
        context_pack: dict[str, Any],
        sample_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in _safe_list(context_pack.get("property_matrix")):
            record = _safe_dict(row)
            sample_id = _safe_text(record.get("sample_id"))
            property_name = _canonical_property_name(record.get("property"))
            value = _safe_text(record.get("value"))
            sample = sample_by_id.get(sample_id, {})
            rows.append(
                {
                    "sample_id": sample_id,
                    "paper": _safe_text(record.get("paper")) or "--",
                    "property": property_name,
                    "source_property": _safe_text(record.get("property")) or property_name,
                    "label": _property_label(property_name, "en"),
                    "value": value,
                    "value_number": _extract_number(value),
                    "unit": _safe_text(record.get("unit")),
                    "status": _safe_text(record.get("status")) or "observed",
                    "confidence": record.get("confidence"),
                    "process_parameters": deepcopy(
                        _safe_dict(sample.get("process_parameters"))
                    ),
                    "evidence_ids": [
                        _safe_text(item)
                        for item in _safe_list(record.get("evidence_ids"))
                        if _safe_text(item)
                    ],
                }
            )
        return rows

    def _literature_scope(self, context_pack: dict[str, Any]) -> dict[str, Any]:
        source_scope = deepcopy(_safe_dict(context_pack.get("literature_scope")))
        paper_count = int(source_scope.get("paper_count") or 0)
        if paper_count <= 0:
            paper_count = len(_safe_list(source_scope.get("included_papers")))
        if paper_count <= 1:
            scope_warning = "single_paper_only"
        elif paper_count < 3:
            scope_warning = "limited_paper_count"
        else:
            scope_warning = None
        return {
            **source_scope,
            "paper_count": paper_count,
            "scope_warning": scope_warning,
        }

    def _process_parameter_keys(
        self,
        context_pack: dict[str, Any],
        sample_rows: list[dict[str, Any]],
    ) -> list[str]:
        taxonomy_keys = [
            _safe_text(item)
            for item in _safe_list(
                _safe_dict(context_pack.get("taxonomy")).get("process_parameters")
            )
            if _safe_text(item)
        ]
        row_keys = sorted(
            {
                key
                for row in sample_rows
                for key in _safe_dict(row.get("process_parameters")).keys()
                if _safe_text(key)
            }
        )
        return sorted(taxonomy_keys or row_keys, key=_process_sort_key)

    def _process_parameter_space(
        self,
        process_parameters: list[str],
        sample_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        spaces: list[dict[str, Any]] = []
        for key in process_parameters:
            values = [
                _safe_dict(row.get("process_parameters")).get(key)
                for row in sample_rows
                if key in _safe_dict(row.get("process_parameters"))
                and _safe_text(_safe_dict(row.get("process_parameters")).get(key))
            ]
            display_values = sorted({_safe_text(value) for value in values if _safe_text(value)})
            numeric_values = [
                number
                for number in (_extract_number(value) for value in values)
                if number is not None
            ]
            if numeric_values and len(numeric_values) == len(values):
                spaces.append(
                    {
                        "parameter": key,
                        "label": _process_parameter_label(key, "en"),
                        "kind": "numeric",
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "values": display_values,
                    }
                )
            else:
                spaces.append(
                    {
                        "parameter": key,
                        "label": _process_parameter_label(key, "en"),
                        "kind": "categorical",
                        "values": display_values,
                    }
                )
        return spaces

    def _property_ranges(self, property_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_property: dict[str, list[dict[str, Any]]] = {}
        for row in property_rows:
            if row.get("value_number") is None:
                continue
            property_name = _safe_text(row.get("property"))
            if property_name:
                by_property.setdefault(property_name, []).append(row)

        ranges: list[dict[str, Any]] = []
        for property_name in sorted(by_property.keys(), key=_property_sort_key):
            rows = sorted(
                by_property[property_name],
                key=lambda item: float(item.get("value_number") or 0),
            )
            minimum = rows[0]
            maximum = rows[-1]
            ranges.append(
                {
                    "property": property_name,
                    "label": _property_label(property_name, "en"),
                    "count": len(rows),
                    "unit": _safe_text(minimum.get("unit")) or _safe_text(maximum.get("unit")),
                    "min": self._value_ref(minimum),
                    "max": self._value_ref(maximum),
                    "span": (
                        float(maximum["value_number"]) - float(minimum["value_number"])
                        if maximum.get("value_number") is not None
                        and minimum.get("value_number") is not None
                        else None
                    ),
                }
            )
        return ranges

    def _paired_comparisons(self, property_ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        comparisons: list[dict[str, Any]] = []
        for index, item in enumerate(property_ranges, 1):
            low = _safe_dict(item.get("min"))
            high = _safe_dict(item.get("max"))
            if not low or not high:
                continue
            if _safe_text(low.get("sample_id")) == _safe_text(high.get("sample_id")):
                continue
            comparisons.append(
                {
                    "id": f"PC{index:02d}",
                    "comparison_type": "property_extreme",
                    "property": item.get("property"),
                    "label": item.get("label"),
                    "low": low,
                    "high": high,
                    "delta": item.get("span"),
                    "evidence_ids": sorted(
                        {
                            *[
                                _safe_text(eid)
                                for eid in _safe_list(low.get("evidence_ids"))
                                if _safe_text(eid)
                            ],
                            *[
                                _safe_text(eid)
                                for eid in _safe_list(high.get("evidence_ids"))
                                if _safe_text(eid)
                            ],
                        }
                    ),
                }
            )
        return comparisons

    def _trend_candidates(
        self,
        paired_comparisons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for index, comparison in enumerate(paired_comparisons, 1):
            low = _safe_dict(comparison.get("low"))
            high = _safe_dict(comparison.get("high"))
            label = _safe_text(comparison.get("label")) or _safe_text(
                comparison.get("property")
            )
            candidates.append(
                {
                    "id": f"T{index:02d}",
                    "finding_type": "sample_level_contrast",
                    "property": comparison.get("property"),
                    "statement": (
                        f"{label}: {_safe_text(high.get('sample_id'))} "
                        f"{_safe_text(high.get('value'))} vs "
                        f"{_safe_text(low.get('sample_id'))} {_safe_text(low.get('value'))}."
                    ),
                    "supporting_comparison": comparison.get("id"),
                    "evidence_ids": comparison.get("evidence_ids", []),
                    "confidence": "medium" if comparison.get("evidence_ids") else "low",
                }
            )
        return candidates

    def _value_ref(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "sample_id": _safe_text(row.get("sample_id")),
            "property": _safe_text(row.get("property")),
            "value": _safe_text(row.get("value")),
            "value_number": row.get("value_number"),
            "unit": _safe_text(row.get("unit")),
            "paper": _safe_text(row.get("paper")) or "--",
            "process_parameters": deepcopy(_safe_dict(row.get("process_parameters"))),
            "evidence_ids": deepcopy(_safe_list(row.get("evidence_ids"))),
        }

    def _quality_flags(
        self,
        *,
        literature_scope: dict[str, Any],
        sample_rows: list[dict[str, Any]],
        property_rows: list[dict[str, Any]],
        property_ranges: list[dict[str, Any]],
        comparison_clusters: list[Any],
        evidence_index: dict[str, Any],
    ) -> list[dict[str, str]]:
        flags: list[dict[str, str]] = []

        def add(code: str, severity: str, message: str) -> None:
            flags.append({"code": code, "severity": severity, "message": message})

        paper_count = int(literature_scope.get("paper_count") or 0)
        if paper_count <= 1:
            add(
                "single_paper_scope",
                "warning",
                "Only one paper is present; report language must avoid cross-literature consensus claims.",
            )
        elif paper_count < 3:
            add(
                "limited_literature_scope",
                "warning",
                "The collection has fewer than three papers; cross-paper claims are weak.",
            )
        if not sample_rows:
            add("missing_sample_rows", "blocking", "No sample-process rows are available.")
        if not property_rows:
            add("missing_property_values", "blocking", "No sample-property values are available.")
        present_properties = {
            _safe_text(item.get("property"))
            for item in property_ranges
            if _safe_text(item.get("property"))
        }
        missing_core = [
            property_name
            for property_name in _CORE_PROPERTY_ORDER
            if property_name not in present_properties
        ]
        if property_rows and missing_core:
            add(
                "missing_core_properties",
                "info",
                "The data pack is missing core property groups: " + ", ".join(missing_core),
            )
        if not comparison_clusters:
            add(
                "no_comparison_clusters",
                "warning",
                "No controlled comparison clusters are available; trends are sample-level contrasts.",
            )
        if property_rows and not evidence_index:
            add(
                "missing_evidence_index",
                "warning",
                "Property rows cite evidence ids, but the evidence table is not available.",
            )
        return flags


class OutlinePlanner:
    """Create a structured report outline from deterministic data-pack facts."""

    def build(self, data_pack: dict[str, Any], *, language: str) -> dict[str, Any]:
        material_name = _safe_text(_safe_dict(data_pack.get("material")).get("canonical_name"))
        if not material_name:
            material_name = "Material"
        title = (
            f"{material_name} 选择性激光熔化工艺-性能综述草稿"
            if language == "zh"
            else f"{material_name} selective laser melting process-property review draft"
        )
        property_claims = [
            f"{_safe_text(item.get('property'))}_range"
            for item in _safe_list(_safe_dict(data_pack.get("computed_summaries")).get("property_ranges"))
            if _safe_text(_safe_dict(item).get("property"))
        ]
        sections = [
            self._section(
                "abstract",
                "摘要",
                "Abstract",
                "Summarize the scope, sample count, key ranges, and limitations with evidence ids.",
                ["literature_scope", "computed_summaries"],
                ["paper_count", "sample_count", "at_least_two_values"],
                language,
            ),
            self._section(
                "introduction",
                "引言",
                "Introduction",
                "Frame the material and process without adding unsupported external results.",
                ["material", "literature_scope"],
                ["collection_boundary"],
                language,
            ),
            self._section(
                "literature_scope",
                "文献范围与证据边界",
                "Literature Scope and Evidence Boundary",
                "State the collection size and avoid unsupported cross-literature claims.",
                ["literature_scope", "quality_flags"],
                ["paper_count", "sample_count", "scope_warning"],
                language,
            ),
            self._section(
                "sample_design",
                "材料体系与样品设计",
                "Material System and Sample Design",
                "Describe actual samples, material variants, and variable axes.",
                ["sample_design"],
                ["sample_count", "sample_rows"],
                language,
            ),
            self._section(
                "process_parameter_space",
                "工艺参数空间",
                "Process Parameter Space",
                "Summarize the observed process parameters and their ranges or categories.",
                ["sample_design"],
                ["process_parameter_space"],
                language,
            ),
            self._section(
                "property_results",
                "性能结果与样品级差异",
                "Performance Results and Sample-Level Differences",
                "Cover every measured core property range and name sample-level extrema.",
                ["property_matrix", "computed_summaries"],
                [*property_claims, "sample_level_extrema"],
                language,
            ),
            self._section(
                "processing_property_trends",
                "工艺-性能趋势",
                "Processing-Property Trends",
                "Discuss sample-level comparisons without overstating causality.",
                ["sample_design", "computed_summaries"],
                ["paired_comparisons", "trend_candidates"],
                language,
            ),
            self._scope_section(data_pack, language),
            self._section(
                "mechanism_discussion",
                "机制讨论",
                "Mechanistic Discussion",
                "Separate direct observations from hypotheses requiring validation.",
                ["computed_summaries", "quality_flags", "limitations"],
                ["direct_observation_vs_hypothesis"],
                language,
            ),
            self._section(
                "limitations",
                "局限性",
                "Limitations",
                "State data limitations and evidence boundaries explicitly.",
                ["limitations", "quality_flags"],
                ["scope_limits", "data_limits"],
                language,
            ),
            self._section(
                "research_gaps",
                "研究空白与未来方向",
                "Research Gaps and Future Directions",
                "Turn missing or weak evidence into concrete future work.",
                ["research_gaps", "quality_flags"],
                ["future_work_from_gaps"],
                language,
            ),
            self._section(
                "conclusions",
                "结论",
                "Conclusions",
                "Conclude only evidence-backed findings and cite evidence ids.",
                ["literature_scope", "computed_summaries", "quality_flags"],
                ["evidence_backed_takeaways"],
                language,
            ),
        ]
        return {
            "title": title,
            "language": language,
            "sections": sections,
            "planning_rules": {
                "single_paper_boundary": self._paper_count(data_pack) < 3,
                "property_matrix_section": bool(property_claims),
                "sample_design_section": bool(
                    _safe_list(_safe_dict(data_pack.get("sample_design")).get("sample_rows"))
                ),
            },
        }

    def _section(
        self,
        section_id: str,
        zh_title: str,
        en_title: str,
        purpose: str,
        required_data: list[str],
        required_claims: list[str],
        language: str,
    ) -> dict[str, Any]:
        return {
            "id": section_id,
            "title": zh_title if language == "zh" else en_title,
            "purpose": purpose,
            "required_data": required_data,
            "required_claims": required_claims,
        }

    def _scope_section(self, data_pack: dict[str, Any], language: str) -> dict[str, Any]:
        if self._paper_count(data_pack) < 3:
            return self._section(
                "evidence_boundary",
                "单篇文献边界",
                "Single-Paper Evidence Boundary",
                "Explain why the report cannot claim cross-paper consistency.",
                ["literature_scope", "quality_flags"],
                ["single_paper_boundary"],
                language,
            )
        return self._section(
            "cross_paper_consistency",
            "跨文献一致性与差异",
            "Cross-Paper Consistency and Differences",
            "Discuss consistency only when multiple papers support it.",
            ["comparison_clusters", "computed_summaries", "quality_flags"],
            ["cross_paper_support"],
            language,
        )

    def _paper_count(self, data_pack: dict[str, Any]) -> int:
        return int(_safe_dict(data_pack.get("literature_scope")).get("paper_count") or 0)


class SectionContextSelector:
    """Select the minimum structured data needed to write each section."""

    def select(self, data_pack: dict[str, Any], outline: dict[str, Any]) -> dict[str, Any]:
        contexts: list[dict[str, Any]] = []
        evidence_index = _safe_dict(data_pack.get("evidence_index"))
        for section in _safe_list(outline.get("sections")):
            section_record = _safe_dict(section)
            data = self._data_for_section(data_pack, section_record)
            evidence_ids = _collect_evidence_ids(data)
            contexts.append(
                {
                    "section": section_record,
                    "material": deepcopy(_safe_dict(data_pack.get("material"))),
                    "summary": self._summary(data_pack),
                    "quality_flags": deepcopy(_safe_list(data_pack.get("quality_flags"))),
                    "data": data,
                    "evidence_index": {
                        evidence_id: evidence_index[evidence_id]
                        for evidence_id in sorted(evidence_ids)
                        if evidence_id in evidence_index
                    },
                    "writing_rules": self._writing_rules(data_pack, section_record),
                }
            )
        return {"sections": contexts}

    def _data_for_section(
        self,
        data_pack: dict[str, Any],
        section: dict[str, Any],
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        computed = _safe_dict(data_pack.get("computed_summaries"))
        for item in _safe_list(section.get("required_data")):
            key = _safe_text(item)
            if key == "material":
                data[key] = deepcopy(_safe_dict(data_pack.get("material")))
            elif key == "quality_flags":
                data[key] = deepcopy(_safe_list(data_pack.get("quality_flags")))
            elif key in data_pack:
                data[key] = deepcopy(data_pack[key])
            elif key in computed:
                data[key] = deepcopy(computed[key])
        section_id = _safe_text(section.get("id"))
        if section_id in {"abstract", "conclusions"}:
            data.setdefault("literature_scope", deepcopy(data_pack.get("literature_scope")))
            data.setdefault("computed_summaries", deepcopy(computed))
        if section_id in {"property_results", "processing_property_trends"}:
            data.setdefault("property_matrix", deepcopy(data_pack.get("property_matrix")))
            data.setdefault("sample_design", deepcopy(data_pack.get("sample_design")))
        return data

    def _summary(self, data_pack: dict[str, Any]) -> dict[str, Any]:
        sample_design = _safe_dict(data_pack.get("sample_design"))
        property_matrix = _safe_dict(data_pack.get("property_matrix"))
        computed = _safe_dict(data_pack.get("computed_summaries"))
        return {
            "paper_count": _safe_dict(data_pack.get("literature_scope")).get("paper_count"),
            "sample_count": sample_design.get("sample_count"),
            "property_count": property_matrix.get("property_count"),
            "properties": property_matrix.get("properties", []),
            "process_parameters": sample_design.get("process_parameters", []),
            "paired_comparison_count": len(_safe_list(computed.get("paired_comparisons"))),
        }

    def _writing_rules(
        self,
        data_pack: dict[str, Any],
        section: dict[str, Any],
    ) -> list[str]:
        rules = [
            "Use only values, sample ids, papers, and evidence ids present in the section context.",
            "Cite evidence ids for key findings.",
            "Use concrete values for result claims.",
        ]
        if int(_safe_dict(data_pack.get("literature_scope")).get("paper_count") or 0) < 3:
            rules.append(
                "Describe the scope as the current collection or current paper; do not claim literature-wide consensus."
            )
        if _safe_text(section.get("id")) == "mechanism_discussion":
            rules.append(
                "Mark mechanistic statements as hypotheses unless the section context directly supports them."
            )
        return rules


class SectionWriter:
    """Write report sections one at a time from section-scoped context."""

    def __init__(self, *, llm_client: Any, model: str) -> None:
        self.llm_client = llm_client
        self.model = model

    def write_sections(
        self,
        section_contexts: dict[str, Any],
        *,
        language: str,
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for context in _safe_list(section_contexts.get("sections")):
            sections.append(self.write_section(_safe_dict(context), language=language))
        return sections

    def write_section(
        self,
        context: dict[str, Any],
        *,
        language: str,
    ) -> dict[str, Any]:
        section = _safe_dict(context.get("section"))
        content = self._call_llm(context, language=language)
        if not content:
            content = self.deterministic_section(context, language=language)
        payload = self._parse_response(content)
        markdown = self._normalize_section_markdown(
            _safe_text(payload.get("markdown")) or content,
            title=_safe_text(section.get("title")) or _safe_text(section.get("id")),
        )
        return {
            "section_id": _safe_text(section.get("id")),
            "title": _safe_text(section.get("title")),
            "markdown": markdown,
            "claims": _safe_list(payload.get("claims")),
            "source": "llm" if content else "deterministic",
        }

    def deterministic_section(self, context: dict[str, Any], *, language: str) -> str:
        section = _safe_dict(context.get("section"))
        section_id = _safe_text(section.get("id"))
        title = _safe_text(section.get("title")) or section_id
        data = _safe_dict(context.get("data"))
        summary = _safe_dict(context.get("summary"))
        lines = [f"## {title}", ""]
        if section_id == "abstract":
            lines.append(self._abstract_text(data, summary, language))
        elif section_id == "literature_scope":
            lines.append(self._scope_text(data, summary, language))
        elif section_id == "sample_design":
            lines.extend(self._sample_design_text(data, language))
        elif section_id == "process_parameter_space":
            lines.extend(self._process_space_text(data, language))
        elif section_id == "property_results":
            lines.extend(self._property_results_text(data, language))
        elif section_id == "processing_property_trends":
            lines.extend(self._trend_text(data, language))
        elif section_id in {"evidence_boundary", "cross_paper_consistency"}:
            lines.append(self._boundary_text(data, summary, language))
        elif section_id == "mechanism_discussion":
            lines.extend(self._mechanism_text(data, language))
        elif section_id == "limitations":
            lines.extend(self._limitations_text(data, language))
        elif section_id == "research_gaps":
            lines.extend(self._research_gaps_text(data, language))
        elif section_id == "conclusions":
            lines.extend(self._conclusion_text(data, summary, language))
        else:
            lines.append(self._intro_text(context, language))
        return "\n".join(lines).strip()

    def _call_llm(self, context: dict[str, Any], *, language: str) -> str:
        language_label = "formal academic Chinese" if language == "zh" else "formal academic English"
        system_prompt = (
            "You are a materials science section writer. Write only the requested section.\n"
            "Return JSON with keys markdown and claims. The markdown must include one level-2 heading.\n"
            "Every concrete result claim must include sample ids, values, and evidence ids."
        )
        user_prompt = (
            f"Language: {language_label}\n"
            "Write this section from the scoped context. Do not add facts outside it.\n"
            "If data are insufficient, state the limitation instead of generalizing.\n\n"
            f"SectionContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
        completion = self.llm_client.chat.completions.create(
            model=self.model,
            temperature=0.15,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content if completion.choices else None
        return _coerce_message_content(content)

    def _parse_response(self, content: str) -> dict[str, Any]:
        text = content.strip()
        text = _JSON_FENCE_PATTERN.sub("", text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"markdown": content, "claims": []}
        if isinstance(payload, dict):
            return payload
        return {"markdown": content, "claims": []}

    def _normalize_section_markdown(self, markdown: str, *, title: str) -> str:
        text = markdown.strip()
        text = re.sub(r"^#(?!#)\s+", "## ", text, count=1)
        if not re.match(r"^##\s+", text):
            text = f"## {title}\n\n{text}"
        return text.strip()

    def _abstract_text(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        language: str,
    ) -> str:
        scope = _safe_dict(data.get("literature_scope"))
        comparisons = _safe_list(
            _safe_dict(data.get("computed_summaries")).get("paired_comparisons")
        )
        paper_count = scope.get("paper_count", summary.get("paper_count", 0))
        sample_count = summary.get("sample_count", 0)
        if language == "en":
            prefix = (
                f"The current collection contains {paper_count} paper(s) and "
                f"{sample_count} sample(s)."
            )
        else:
            prefix = f"当前集合包含 {paper_count} 篇文献和 {sample_count} 个样品。"
        details = [self._comparison_sentence(item, language) for item in comparisons[:2]]
        return " ".join([prefix, *[item for item in details if item]])

    def _scope_text(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        language: str,
    ) -> str:
        scope = _safe_dict(data.get("literature_scope"))
        paper_count = scope.get("paper_count", summary.get("paper_count", 0))
        sample_count = summary.get("sample_count", 0)
        if language == "en":
            return (
                f"This report is limited to the current collection: {paper_count} paper(s), "
                f"{sample_count} sample(s), and no database-wide search. "
                "Claims are therefore collection-bounded."
            )
        return (
            f"本报告仅覆盖当前集合中的 {paper_count} 篇文献和 {sample_count} 个样品，"
            "不是全库或全领域文献检索结果，因此所有结论均限定在当前集合内。"
        )

    def _sample_design_text(self, data: dict[str, Any], language: str) -> list[str]:
        sample_design = _safe_dict(data.get("sample_design"))
        sample_rows = _safe_list(sample_design.get("sample_rows"))
        process_keys = _safe_list(sample_design.get("process_parameters"))
        if language == "en":
            lines = [
                (
                    f"The sample matrix contains {len(sample_rows)} sample(s). "
                    "Observed process parameters are "
                    + ", ".join(_process_parameter_label(_safe_text(key), language) for key in process_keys)
                    + "."
                )
            ]
        else:
            lines = [
                (
                    f"样品矩阵包含 {len(sample_rows)} 个样品；已抽取的工艺参数包括"
                    + "、".join(_process_parameter_label(_safe_text(key), language) for key in process_keys)
                    + "。"
                )
            ]
        preview = []
        for row in sample_rows[:3]:
            record = _safe_dict(row)
            params = self._process_summary(_safe_dict(record.get("process_parameters")), language)
            preview.append(f"{_safe_text(record.get('sample_id'))}: {params}")
        if preview:
            lines.append("；".join(preview) + "。")
        return lines

    def _process_space_text(self, data: dict[str, Any], language: str) -> list[str]:
        spaces = _safe_list(_safe_dict(data.get("sample_design")).get("process_parameter_space"))
        lines: list[str] = []
        for item in spaces:
            record = _safe_dict(item)
            label = _process_parameter_label(_safe_text(record.get("parameter")), language)
            if record.get("kind") == "numeric":
                lines.append(
                    f"{label}: {_format_number(record.get('min'))} 到 {_format_number(record.get('max'))}。"
                    if language == "zh"
                    else f"{label}: {_format_number(record.get('min'))} to {_format_number(record.get('max'))}."
                )
            else:
                values = ", ".join(_safe_text(value) for value in _safe_list(record.get("values")))
                lines.append(
                    f"{label}: {values}。"
                    if language == "zh"
                    else f"{label}: {values}."
                )
        return lines or ["当前数据未提供可汇总的工艺参数空间。"]

    def _property_results_text(self, data: dict[str, Any], language: str) -> list[str]:
        ranges = _safe_list(
            _safe_dict(data.get("computed_summaries")).get("property_ranges")
        )
        lines: list[str] = []
        for item in ranges:
            record = _safe_dict(item)
            low = _safe_dict(record.get("min"))
            high = _safe_dict(record.get("max"))
            label = _property_label(_safe_text(record.get("property")), language)
            if language == "en":
                lines.append(
                    f"{label} ranges from {_safe_text(low.get('value'))} in "
                    f"{_safe_text(low.get('sample_id'))} {_evidence_label(low.get('evidence_ids'))} "
                    f"to {_safe_text(high.get('value'))} in {_safe_text(high.get('sample_id'))} "
                    f"{_evidence_label(high.get('evidence_ids'))}."
                )
            else:
                lines.append(
                    f"{label}范围为 {_safe_text(low.get('value'))}（{_safe_text(low.get('sample_id'))}"
                    f"{_evidence_label(low.get('evidence_ids'))}）至 {_safe_text(high.get('value'))}"
                    f"（{_safe_text(high.get('sample_id'))}{_evidence_label(high.get('evidence_ids'))}）。"
                )
        return lines or ["当前数据未提供可量化的性能结果。"]

    def _trend_text(self, data: dict[str, Any], language: str) -> list[str]:
        comparisons = _safe_list(
            _safe_dict(data.get("computed_summaries")).get("paired_comparisons")
        )
        lines = [self._comparison_sentence(item, language) for item in comparisons[:5]]
        return [line for line in lines if line] or ["当前数据不足以形成样品级趋势比较。"]

    def _boundary_text(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        language: str,
    ) -> str:
        scope = _safe_dict(data.get("literature_scope"))
        paper_count = int(scope.get("paper_count") or summary.get("paper_count") or 0)
        if language == "en":
            if paper_count < 3:
                return (
                    "Because the collection has fewer than three papers, this section is "
                    "an evidence-boundary statement rather than a cross-paper consistency claim."
                )
            return "Cross-paper consistency should be read only across the papers present in this collection."
        if paper_count < 3:
            return "由于当前集合少于三篇文献，本节只说明证据边界，不作跨文献一致性结论。"
        return "跨文献一致性仅限于当前集合中已有文献之间的比较。"

    def _mechanism_text(self, data: dict[str, Any], language: str) -> list[str]:
        trends = _safe_list(
            _safe_dict(data.get("computed_summaries")).get("trend_candidates")
        )
        if not trends:
            return ["当前数据不足以支撑机制推断，只能记录待验证假设。"]
        first = _safe_dict(trends[0])
        if language == "en":
            return [
                (
                    "The available data support a sample-level observation, not a proven "
                    f"mechanism: {_safe_text(first.get('statement'))} "
                    f"{_evidence_label(first.get('evidence_ids'))}."
                ),
                "Thermal history, melt-pool stability, and defect closure remain hypotheses requiring more direct microstructural evidence.",
            ]
        return [
            (
                "现有数据支持样品级观察，而不是已经证明的机制："
                f"{_safe_text(first.get('statement'))}{_evidence_label(first.get('evidence_ids'))}。"
            ),
            "熔池稳定性、热历史和缺陷闭合等解释仍属于需要组织证据进一步验证的假设。",
        ]

    def _limitations_text(self, data: dict[str, Any], language: str) -> list[str]:
        limitations = [_safe_text(item) for item in _safe_list(data.get("limitations")) if _safe_text(item)]
        flags = [
            _safe_text(_safe_dict(item).get("message"))
            for item in _safe_list(data.get("quality_flags"))
            if _safe_text(_safe_dict(item).get("message"))
        ]
        lines = limitations + flags
        if not lines:
            lines = ["No additional limitations were recorded." if language == "en" else "当前没有额外记录的局限性。"]
        return lines

    def _research_gaps_text(self, data: dict[str, Any], language: str) -> list[str]:
        gaps = _safe_list(data.get("research_gaps"))
        lines: list[str] = []
        for gap in gaps:
            record = _safe_dict(gap)
            gap_text = _safe_text(record.get("gap"))
            basis = _safe_text(record.get("basis"))
            if gap_text:
                lines.append(f"{gap_text} {basis}".strip())
        if not lines:
            lines.append(
                "Future work should add controlled comparisons and direct microstructure evidence."
                if language == "en"
                else "后续研究应补充受控对比和直接组织证据。"
            )
        return lines

    def _conclusion_text(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        language: str,
    ) -> list[str]:
        comparisons = _safe_list(
            _safe_dict(data.get("computed_summaries")).get("paired_comparisons")
        )
        lines: list[str] = []
        if comparisons:
            lines.append(self._comparison_sentence(_safe_dict(comparisons[0]), language))
        else:
            lines.append(self._scope_text(data, summary, language))
        if language == "en":
            lines.append("These conclusions remain bounded to the current collection.")
        else:
            lines.append("上述结论仍限定在当前集合和当前证据范围内。")
        return lines

    def _intro_text(self, context: dict[str, Any], language: str) -> str:
        material = _safe_text(_safe_dict(context.get("material")).get("canonical_name")) or "the material"
        if language == "en":
            return (
                f"This draft reviews {material} only through the evidence currently "
                "available in the collection."
            )
        return f"本草稿仅基于当前集合中关于 {material} 的结构化证据展开综述。"

    def _comparison_sentence(self, comparison: dict[str, Any], language: str) -> str:
        record = _safe_dict(comparison)
        low = _safe_dict(record.get("low"))
        high = _safe_dict(record.get("high"))
        property_name = _safe_text(record.get("property"))
        label = _property_label(property_name, language)
        evidence = _evidence_label(record.get("evidence_ids"))
        if not low or not high:
            return ""
        if language == "en":
            return (
                f"For {label}, {_safe_text(high.get('sample_id'))} reaches "
                f"{_safe_text(high.get('value'))}, whereas {_safe_text(low.get('sample_id'))} "
                f"is {_safe_text(low.get('value'))} {evidence}."
            )
        return (
            f"在{label}上，{_safe_text(high.get('sample_id'))} 为 {_safe_text(high.get('value'))}，"
            f"而 {_safe_text(low.get('sample_id'))} 为 {_safe_text(low.get('value'))}{evidence}。"
        )

    def _process_summary(self, parameters: dict[str, Any], language: str) -> str:
        parts = [
            f"{_process_parameter_label(key, language)}={value}"
            for key, value in sorted(parameters.items(), key=lambda item: _process_sort_key(item[0]))
            if _safe_text(value)
        ]
        return "，".join(parts) if language == "zh" else ", ".join(parts)


class EvidenceBinder:
    """Bind section claims and text back to values and evidence ids in the data pack."""

    def bind_sections(
        self,
        sections: list[dict[str, Any]],
        data_pack: dict[str, Any],
    ) -> dict[str, Any]:
        known_evidence_ids = set(_safe_dict(data_pack.get("evidence_index")).keys())
        results = []
        for section in sections:
            text = _safe_text(section.get("markdown"))
            used_evidence_ids = set(_EVIDENCE_ID_PATTERN.findall(text))
            invalid_ids = sorted(used_evidence_ids - known_evidence_ids)
            mentioned_values = self._mentioned_values(text, data_pack)
            mentioned_samples = self._mentioned_samples(text, data_pack)
            problems = []
            if invalid_ids:
                problems.append("Invalid evidence ids: " + ", ".join(invalid_ids))
            if self._requires_binding(_safe_text(section.get("section_id"))) and not used_evidence_ids:
                problems.append("Section has no evidence ids.")
            if self._requires_values(_safe_text(section.get("section_id"))) and not mentioned_values:
                problems.append("Section does not mention known property values.")
            if invalid_ids or "Section has no evidence ids." in problems:
                status = "unsupported"
            elif problems:
                status = "weak"
            else:
                status = "bound"
            results.append(
                {
                    "section_id": section.get("section_id"),
                    "binding_status": status,
                    "bound_evidence": sorted(used_evidence_ids & known_evidence_ids),
                    "invalid_evidence": invalid_ids,
                    "sample_ids": mentioned_samples,
                    "values": mentioned_values[:30],
                    "claims": self._bind_claims(section, known_evidence_ids),
                    "problems": problems,
                }
            )
        overall = "passed" if all(item["binding_status"] != "unsupported" for item in results) else "failed"
        return {"overall_status": overall, "sections": results}

    def _bind_claims(
        self,
        section: dict[str, Any],
        known_evidence_ids: set[str],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        for claim in _safe_list(section.get("claims")):
            record = _safe_dict(claim)
            evidence_ids = {
                _safe_text(item)
                for item in _safe_list(record.get("evidence_ids"))
                if _safe_text(item)
            }
            invalid = sorted(evidence_ids - known_evidence_ids)
            claims.append(
                {
                    "claim": _safe_text(record.get("claim")),
                    "binding_status": "unsupported" if invalid or not evidence_ids else "bound",
                    "bound_evidence": sorted(evidence_ids & known_evidence_ids),
                    "sample_ids": _safe_list(record.get("sample_ids")),
                    "properties": _safe_list(record.get("properties")),
                    "values": _safe_list(record.get("values")),
                    "problems": (
                        ["Invalid evidence ids: " + ", ".join(invalid)]
                        if invalid
                        else ([] if evidence_ids else ["Claim has no evidence ids."])
                    ),
                }
            )
        return claims

    def _mentioned_values(self, text: str, data_pack: dict[str, Any]) -> list[dict[str, Any]]:
        normalized_text = text.replace(" ", "")
        values: list[dict[str, Any]] = []
        for row in _safe_list(_safe_dict(data_pack.get("property_matrix")).get("rows")):
            record = _safe_dict(row)
            value = _safe_text(record.get("value"))
            numeric = _format_number(record.get("value_number"))
            if (
                value
                and value.replace(" ", "") in normalized_text
                or numeric
                and numeric in normalized_text
            ):
                values.append(
                    {
                        "sample_id": record.get("sample_id"),
                        "property": record.get("property"),
                        "value": value,
                        "evidence_ids": record.get("evidence_ids", []),
                    }
                )
        return values

    def _mentioned_samples(self, text: str, data_pack: dict[str, Any]) -> list[str]:
        sample_ids = []
        for row in _safe_list(_safe_dict(data_pack.get("sample_design")).get("sample_rows")):
            sample_id = _safe_text(_safe_dict(row).get("sample_id"))
            if sample_id and sample_id in text and sample_id not in sample_ids:
                sample_ids.append(sample_id)
        return sample_ids

    def _requires_binding(self, section_id: str) -> bool:
        return section_id in {
            "abstract",
            "property_results",
            "processing_property_trends",
            "mechanism_discussion",
            "conclusions",
        }

    def _requires_values(self, section_id: str) -> bool:
        return section_id in {
            "abstract",
            "property_results",
            "processing_property_trends",
            "conclusions",
        }


class ReportReviewer:
    """Review section outputs for generic or unsupported writing."""

    def review(
        self,
        sections: list[dict[str, Any]],
        bound_claims: dict[str, Any],
        data_pack: dict[str, Any],
        outline: dict[str, Any],
    ) -> dict[str, Any]:
        binding_by_section = {
            _safe_text(item.get("section_id")): item
            for item in _safe_list(bound_claims.get("sections"))
        }
        notes: list[dict[str, Any]] = []
        for section in sections:
            section_id = _safe_text(section.get("section_id"))
            text = _safe_text(section.get("markdown"))
            binding = _safe_dict(binding_by_section.get(section_id))
            issues = []
            issues.extend(self._binding_issues(binding))
            issues.extend(self._section_issues(section_id, text, data_pack))
            status = "failed" if issues else "passed"
            notes.append(
                {
                    "section_id": section_id,
                    "status": status,
                    "blocking_issues": issues,
                    "revision_instructions": [
                        issue["message"]
                        for issue in issues
                        if _safe_text(issue.get("message"))
                    ],
                }
            )
        overall = "passed" if all(item["status"] == "passed" for item in notes) else "failed"
        return {
            "overall_status": overall,
            "sections": notes,
            "outline_section_count": len(_safe_list(outline.get("sections"))),
        }

    def _binding_issues(self, binding: dict[str, Any]) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        for problem in _safe_list(binding.get("problems")):
            issues.append(
                {
                    "type": "evidence_binding_failure",
                    "message": _safe_text(problem),
                }
            )
        return issues

    def _section_issues(
        self,
        section_id: str,
        text: str,
        data_pack: dict[str, Any],
    ) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        property_ranges = _safe_list(
            _safe_dict(data_pack.get("computed_summaries")).get("property_ranges")
        )
        if section_id == "abstract" and property_ranges:
            if len(self._known_values_in_text(text, data_pack)) < 2:
                issues.append(
                    {
                        "type": "missing_required_data",
                        "message": "The abstract must include at least two concrete property values.",
                    }
                )
        if section_id == "property_results":
            for item in property_ranges:
                record = _safe_dict(item)
                low = _safe_dict(record.get("min"))
                high = _safe_dict(record.get("max"))
                if not self._mentions_range(text, low, high):
                    issues.append(
                        {
                            "type": "missing_property_range",
                            "message": (
                                "The property-results section must include the range for "
                                f"{_safe_text(record.get('property'))}."
                            ),
                        }
                    )
        if section_id == "conclusions" and property_ranges:
            if not _EVIDENCE_ID_PATTERN.search(text):
                issues.append(
                    {
                        "type": "missing_evidence",
                        "message": "The conclusion section must cite evidence ids.",
                    }
                )
        if self._paper_count(data_pack) < 3 and self._overstates_scope(text):
            issues.append(
                {
                    "type": "scope_overstatement",
                    "message": "Single-paper or small-scope reports must not claim cross-paper consensus.",
                }
            )
        if self._has_generic_language_without_data(text, data_pack):
            issues.append(
                {
                    "type": "generic_language",
                    "message": "Generic process-property language must be tied to concrete values and evidence ids.",
                }
            )
        if section_id == "mechanism_discussion" and self._has_unsupported_causality(text):
            issues.append(
                {
                    "type": "unsupported_causality",
                    "message": "Mechanism discussion must mark causal explanations as hypotheses unless directly supported.",
                }
            )
        return issues

    def _known_values_in_text(self, text: str, data_pack: dict[str, Any]) -> list[str]:
        normalized_text = text.replace(" ", "")
        values: list[str] = []
        for row in _safe_list(_safe_dict(data_pack.get("property_matrix")).get("rows")):
            record = _safe_dict(row)
            value = _safe_text(record.get("value"))
            numeric = _format_number(record.get("value_number"))
            if (
                value
                and value.replace(" ", "") in normalized_text
                or numeric
                and numeric in normalized_text
            ):
                values.append(value or numeric)
        return values

    def _mentions_range(self, text: str, low: dict[str, Any], high: dict[str, Any]) -> bool:
        normalized_text = text.replace(" ", "")
        low_value = _safe_text(low.get("value")).replace(" ", "")
        high_value = _safe_text(high.get("value")).replace(" ", "")
        low_number = _format_number(low.get("value_number"))
        high_number = _format_number(high.get("value_number"))
        return (
            (low_value and low_value in normalized_text or low_number and low_number in normalized_text)
            and (
                high_value
                and high_value in normalized_text
                or high_number
                and high_number in normalized_text
            )
        )

    def _paper_count(self, data_pack: dict[str, Any]) -> int:
        return int(_safe_dict(data_pack.get("literature_scope")).get("paper_count") or 0)

    def _overstates_scope(self, text: str) -> bool:
        lowered = text.lower()
        return any(pattern in lowered or pattern in text for pattern in _SINGLE_PAPER_OVERSTATEMENTS)

    def _has_generic_language_without_data(
        self,
        text: str,
        data_pack: dict[str, Any],
    ) -> bool:
        lowered = text.lower()
        if not any(pattern in lowered or pattern in text for pattern in _GENERIC_PATTERNS):
            return False
        return not _EVIDENCE_ID_PATTERN.search(text) or not self._known_values_in_text(text, data_pack)

    def _has_unsupported_causality(self, text: str) -> bool:
        lowered = text.lower()
        causal_terms = ["causes", "caused by", "leads to", "导致", "决定"]
        hedges = ["may", "possible", "hypothesis", "requires validation", "可能", "假设", "需要验证"]
        return any(term in lowered or term in text for term in causal_terms) and not any(
            hedge in lowered or hedge in text for hedge in hedges
        )


class RevisionService:
    """Revise failed sections with bounded LLM attempts and deterministic fallback."""

    def __init__(self, *, section_writer: SectionWriter) -> None:
        self.section_writer = section_writer

    def revise_once(
        self,
        sections: list[dict[str, Any]],
        review_notes: dict[str, Any],
        section_contexts: dict[str, Any],
        *,
        language: str,
        round_index: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        context_by_id = {
            _safe_text(_safe_dict(item).get("section", {}).get("id")): _safe_dict(item)
            for item in _safe_list(section_contexts.get("sections"))
        }
        notes_by_id = {
            _safe_text(item.get("section_id")): _safe_dict(item)
            for item in _safe_list(review_notes.get("sections"))
            if _safe_text(item.get("status")) == "failed"
        }
        revised_sections: list[dict[str, Any]] = []
        revision_records: list[dict[str, Any]] = []
        for section in sections:
            section_id = _safe_text(section.get("section_id"))
            note = notes_by_id.get(section_id)
            if not note:
                revised_sections.append(section)
                continue
            context = context_by_id.get(section_id, {})
            content = self._call_revision_llm(section, note, context, language=language)
            if content:
                payload = self.section_writer._parse_response(content)
                markdown = self.section_writer._normalize_section_markdown(
                    _safe_text(payload.get("markdown")) or content,
                    title=_safe_text(section.get("title")) or section_id,
                )
                revised = {
                    **section,
                    "markdown": markdown,
                    "claims": _safe_list(payload.get("claims")),
                    "source": f"revision_round_{round_index}",
                }
                method = "llm_revision"
            else:
                revised = section
                method = "unchanged_empty_revision"
            revised_sections.append(revised)
            revision_records.append(
                {
                    "round": round_index,
                    "section_id": section_id,
                    "method": method,
                    "issues": note.get("blocking_issues", []),
                }
            )
        return revised_sections, revision_records

    def apply_deterministic_fallbacks(
        self,
        sections: list[dict[str, Any]],
        review_notes: dict[str, Any],
        section_contexts: dict[str, Any],
        *,
        language: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        context_by_id = {
            _safe_text(_safe_dict(item).get("section", {}).get("id")): _safe_dict(item)
            for item in _safe_list(section_contexts.get("sections"))
        }
        failed_ids = {
            _safe_text(item.get("section_id"))
            for item in _safe_list(review_notes.get("sections"))
            if _safe_text(item.get("status")) == "failed"
        }
        revised_sections: list[dict[str, Any]] = []
        revision_records: list[dict[str, Any]] = []
        for section in sections:
            section_id = _safe_text(section.get("section_id"))
            context = context_by_id.get(section_id)
            if section_id in failed_ids and context:
                markdown = self.section_writer.deterministic_section(context, language=language)
                revised_sections.append(
                    {
                        **section,
                        "markdown": markdown,
                        "claims": [],
                        "source": "deterministic_fallback",
                    }
                )
                revision_records.append(
                    {
                        "round": "fallback",
                        "section_id": section_id,
                        "method": "deterministic_fallback",
                    }
                )
            else:
                revised_sections.append(section)
        return revised_sections, revision_records

    def _call_revision_llm(
        self,
        section: dict[str, Any],
        note: dict[str, Any],
        context: dict[str, Any],
        *,
        language: str,
    ) -> str:
        system_prompt = (
            "You revise one materials science report section. Return JSON with markdown and claims. "
            "Fix only the listed issues and do not add facts outside the context."
        )
        user_prompt = (
            f"Language: {'formal academic Chinese' if language == 'zh' else 'formal academic English'}\n"
            f"Original section:\n{_safe_text(section.get('markdown'))}\n\n"
            f"Reviewer notes:\n{json.dumps(note, ensure_ascii=False, indent=2)}\n\n"
            f"Section context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
        completion = self.section_writer.llm_client.chat.completions.create(
            model=self.section_writer.model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content if completion.choices else None
        return _coerce_message_content(content)


class FinalIntegrator:
    """Assemble reviewed sections and deterministic appendices into Markdown."""

    def integrate(
        self,
        *,
        outline: dict[str, Any],
        sections: list[dict[str, Any]],
        data_pack: dict[str, Any],
        review_notes: dict[str, Any],
        include_appendix: bool,
        language: str,
    ) -> str:
        section_by_id = {
            _safe_text(section.get("section_id")): section
            for section in sections
            if _safe_text(section.get("section_id"))
        }
        lines = [f"# {_safe_text(outline.get('title'))}", ""]
        for planned in _safe_list(outline.get("sections")):
            section_id = _safe_text(_safe_dict(planned).get("id"))
            section = _safe_dict(section_by_id.get(section_id))
            markdown = _safe_text(section.get("markdown"))
            if markdown:
                lines.extend([self._normalize_heading(markdown), ""])
        if include_appendix:
            lines.extend(self._appendices(data_pack, review_notes, language=language))
        return "\n".join(lines).rstrip() + "\n"

    def _normalize_heading(self, markdown: str) -> str:
        text = markdown.strip()
        return re.sub(r"^#(?!#)\s+", "## ", text, count=1)

    def _appendices(
        self,
        data_pack: dict[str, Any],
        review_notes: dict[str, Any],
        *,
        language: str,
    ) -> list[str]:
        lines: list[str] = []
        sample_table = self._sample_process_table(data_pack, language=language)
        property_table = self._property_matrix_table(data_pack, language=language)
        evidence_table = self._evidence_table(data_pack, language=language)
        warning_table = self._review_warning_table(review_notes, language=language)
        if sample_table:
            lines.extend(["## 附录：样品-工艺参数矩阵" if language == "zh" else "## Appendix: Sample-Process Matrix", "", sample_table, ""])
        if property_table:
            lines.extend(["## 附录：样品-性能数据矩阵" if language == "zh" else "## Appendix: Sample-Property Matrix", "", property_table, ""])
        if evidence_table:
            lines.extend(["## 附录：证据表" if language == "zh" else "## Appendix: Evidence Table", "", evidence_table, ""])
        if warning_table:
            lines.extend(["## 附录：审核警告" if language == "zh" else "## Appendix: Reviewer Warnings", "", warning_table, ""])
        return lines

    def _sample_process_table(self, data_pack: dict[str, Any], *, language: str) -> str:
        sample_design = _safe_dict(data_pack.get("sample_design"))
        sample_rows = _safe_list(sample_design.get("sample_rows"))[:_MAX_TABLE_ROWS]
        if not sample_rows:
            return ""
        process_keys = [
            _safe_text(item)
            for item in _safe_list(sample_design.get("process_parameters"))
            if _safe_text(item)
        ]
        headers = [
            "样品" if language == "zh" else "Sample",
            "变量" if language == "zh" else "Variable",
            *[_process_parameter_label(key, language) for key in process_keys],
            "证据" if language == "zh" else "Evidence",
        ]
        rows = []
        for row in sample_rows:
            record = _safe_dict(row)
            variable = self._variable_label(record, language)
            params = _safe_dict(record.get("process_parameters"))
            rows.append(
                [
                    record.get("sample_id"),
                    variable,
                    *[params.get(key, "--") for key in process_keys],
                    ", ".join(_safe_text(item) for item in _safe_list(record.get("evidence_ids"))),
                ]
            )
        return _markdown_table(headers, rows)

    def _property_matrix_table(self, data_pack: dict[str, Any], *, language: str) -> str:
        rows = _safe_list(_safe_dict(data_pack.get("property_matrix")).get("rows"))
        if not rows:
            return ""
        properties = [
            _safe_text(item)
            for item in _safe_list(_safe_dict(data_pack.get("property_matrix")).get("properties"))
            if _safe_text(item)
        ]
        sample_ids: list[str] = []
        values: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            record = _safe_dict(row)
            sample_id = _safe_text(record.get("sample_id"))
            property_name = _safe_text(record.get("property"))
            if not sample_id or not property_name:
                continue
            if sample_id not in sample_ids:
                sample_ids.append(sample_id)
            evidence = _evidence_label(record.get("evidence_ids"))
            cell = f"{_safe_text(record.get('value'))} {evidence}".strip()
            values.setdefault(sample_id, {}).setdefault(property_name, []).append(cell)
        headers = [
            "样品" if language == "zh" else "Sample",
            *[_property_label(property_name, language) for property_name in properties],
        ]
        table_rows = []
        for sample_id in sample_ids[:_MAX_TABLE_ROWS]:
            sample_values = values.get(sample_id, {})
            table_rows.append(
                [
                    sample_id,
                    *["; ".join(sample_values.get(property_name, [])) for property_name in properties],
                ]
            )
        return _markdown_table(headers, table_rows)

    def _evidence_table(self, data_pack: dict[str, Any], *, language: str) -> str:
        evidence_rows = [
            _safe_dict(value)
            for _, value in sorted(_safe_dict(data_pack.get("evidence_index")).items())
        ]
        if not evidence_rows:
            return ""
        headers = (
            ["证据ID", "论文", "来源类型", "定位", "置信度", "可追溯性状态"]
            if language == "zh"
            else ["Evidence ID", "Paper", "Source", "Locator", "Confidence", "Traceability"]
        )
        rows = [
            [
                row.get("id"),
                row.get("paper"),
                row.get("source_kind"),
                row.get("locator"),
                row.get("confidence"),
                row.get("traceability_status"),
            ]
            for row in evidence_rows[:_MAX_TABLE_ROWS]
        ]
        return _markdown_table(headers, rows)

    def _review_warning_table(self, review_notes: dict[str, Any], *, language: str) -> str:
        rows = []
        for note in _safe_list(review_notes.get("sections")):
            record = _safe_dict(note)
            if _safe_text(record.get("status")) != "failed":
                continue
            for issue in _safe_list(record.get("blocking_issues")):
                issue_record = _safe_dict(issue)
                rows.append(
                    [
                        record.get("section_id"),
                        issue_record.get("type"),
                        issue_record.get("message"),
                    ]
                )
        if not rows:
            return ""
        headers = (
            ["章节", "类型", "说明"]
            if language == "zh"
            else ["Section", "Type", "Message"]
        )
        return _markdown_table(headers, rows[:_MAX_TABLE_ROWS])

    def _variable_label(self, row: dict[str, Any], language: str) -> str:
        axis = _safe_text(row.get("variable_axis"))
        value = row.get("variable_value")
        if axis and value is not None:
            return f"{axis}={value}"
        return "未标注" if language == "zh" else "not specified"


class MaterialReviewReportPipeline:
    """Run staged generation and persist intermediate review artifacts."""

    def __init__(self, *, llm_client: Any, model: str) -> None:
        self.data_pack_builder = MaterialReviewDataPackBuilder()
        self.outline_planner = OutlinePlanner()
        self.context_selector = SectionContextSelector()
        self.section_writer = SectionWriter(llm_client=llm_client, model=model)
        self.evidence_binder = EvidenceBinder()
        self.reviewer = ReportReviewer()
        self.revision_service = RevisionService(section_writer=self.section_writer)
        self.integrator = FinalIntegrator()

    def run(
        self,
        context_pack: dict[str, Any],
        *,
        paths: dict[str, Path],
        language: str,
        include_appendix: bool,
        stage_callback: StageCallback | None = None,
    ) -> dict[str, Any]:
        self._stage(stage_callback, "building_data_pack", "Building structured data pack.")
        data_pack = self.data_pack_builder.build(context_pack)
        write_json(paths["data_pack"], data_pack)

        self._stage(stage_callback, "planning_outline", "Planning report outline.")
        outline = self.outline_planner.build(data_pack, language=language)
        write_json(paths["outline"], outline)

        self._stage(stage_callback, "selecting_section_contexts", "Selecting section contexts.")
        section_contexts = self.context_selector.select(data_pack, outline)
        write_json(paths["section_contexts"], section_contexts)

        self._stage(stage_callback, "writing_sections", "Writing report sections.")
        sections = self.section_writer.write_sections(section_contexts, language=language)
        write_json(paths["sections"], {"sections": sections})

        bound_claims, review_notes = self._bind_and_review(
            sections,
            data_pack,
            outline,
            stage_callback=stage_callback,
        )
        write_json(paths["bound_claims"], bound_claims)
        write_json(paths["review_notes"], review_notes)

        revisions: dict[str, Any] = {"rounds": []}
        for round_index in range(1, _MAX_REVISION_ROUNDS + 1):
            if _safe_text(review_notes.get("overall_status")) == "passed":
                break
            self._stage(
                stage_callback,
                "revising",
                f"Revising sections, round {round_index}.",
            )
            sections, round_records = self.revision_service.revise_once(
                sections,
                review_notes,
                section_contexts,
                language=language,
                round_index=round_index,
            )
            revisions["rounds"].extend(round_records)
            bound_claims, review_notes = self._bind_and_review(
                sections,
                data_pack,
                outline,
                stage_callback=stage_callback,
            )
            write_json(paths["sections"], {"sections": sections})
            write_json(paths["bound_claims"], bound_claims)
            write_json(paths["review_notes"], review_notes)
            write_json(paths["revisions"], revisions)

        if _safe_text(review_notes.get("overall_status")) != "passed":
            self._stage(
                stage_callback,
                "revising",
                "Applying deterministic fallbacks for unresolved sections.",
            )
            sections, fallback_records = self.revision_service.apply_deterministic_fallbacks(
                sections,
                review_notes,
                section_contexts,
                language=language,
            )
            revisions["rounds"].extend(fallback_records)
            bound_claims, review_notes = self._bind_and_review(
                sections,
                data_pack,
                outline,
                stage_callback=stage_callback,
            )
            write_json(paths["sections"], {"sections": sections})
            write_json(paths["bound_claims"], bound_claims)
            write_json(paths["review_notes"], review_notes)
            write_json(paths["revisions"], revisions)

        if not paths["revisions"].exists():
            write_json(paths["revisions"], revisions)

        self._stage(stage_callback, "integrating", "Integrating final Markdown.")
        markdown = self.integrator.integrate(
            outline=outline,
            sections=sections,
            data_pack=data_pack,
            review_notes=review_notes,
            include_appendix=include_appendix,
            language=language,
        )
        return {
            "markdown": markdown,
            "warnings": self._warnings(data_pack, bound_claims, review_notes),
            "data_pack": data_pack,
            "outline": outline,
            "bound_claims": bound_claims,
            "review_notes": review_notes,
            "revisions": revisions,
        }

    def _bind_and_review(
        self,
        sections: list[dict[str, Any]],
        data_pack: dict[str, Any],
        outline: dict[str, Any],
        *,
        stage_callback: StageCallback | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._stage(stage_callback, "binding_evidence", "Binding section evidence.")
        bound_claims = self.evidence_binder.bind_sections(sections, data_pack)
        self._stage(stage_callback, "reviewing", "Reviewing section quality.")
        review_notes = self.reviewer.review(sections, bound_claims, data_pack, outline)
        return bound_claims, review_notes

    def _warnings(
        self,
        data_pack: dict[str, Any],
        bound_claims: dict[str, Any],
        review_notes: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        for flag in _safe_list(data_pack.get("quality_flags")):
            record = _safe_dict(flag)
            if _safe_text(record.get("severity")) in {"warning", "blocking"}:
                warnings.append(_safe_text(record.get("message")))
        for section in _safe_list(bound_claims.get("sections")):
            for problem in _safe_list(_safe_dict(section).get("problems")):
                warnings.append(
                    f"{_safe_text(_safe_dict(section).get('section_id'))}: {_safe_text(problem)}"
                )
        for note in _safe_list(review_notes.get("sections")):
            record = _safe_dict(note)
            if _safe_text(record.get("status")) != "failed":
                continue
            for issue in _safe_list(record.get("blocking_issues")):
                issue_record = _safe_dict(issue)
                warnings.append(
                    f"{_safe_text(record.get('section_id'))}: {_safe_text(issue_record.get('message'))}"
                )
        return list(dict.fromkeys(item for item in warnings if item))

    def _stage(
        self,
        stage_callback: StageCallback | None,
        stage: str,
        message: str,
    ) -> None:
        if stage_callback is not None:
            stage_callback(stage, message)

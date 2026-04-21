from __future__ import annotations

import re
from typing import Any

from application.core.semantic_build.llm.schemas import (
    BaselineReferencePayload,
    EvidenceAnchorPayload,
    ExtractedTestConditionPayload,
    MeasurementResultPayload,
    MeasurementValuePayload,
    MethodFactPayload,
    SampleVariantPayload,
    StructuredDocumentProfile,
    StructuredExtractionBundle,
)


_PROPERTY_HINTS = (
    ("yield strength", "yield_strength"),
    ("tensile strength", "tensile_strength"),
    ("flexural strength", "flexural_strength"),
    ("fatigue life", "fatigue_life"),
    ("retention", "retention"),
    ("hardness", "hardness"),
    ("conductivity", "conductivity"),
    ("modulus", "modulus"),
    ("elongation", "elongation"),
    ("strength", "strength"),
)
_PROPERTY_UNIT_PATTERN = re.compile(r"\(([^)]+)\)")
_FLOAT_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_TEMP_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:c|°c)\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs)\b",
    re.IGNORECASE,
)
_ATM_PATTERN = re.compile(r"\b(?:under|in)\s+(air|argon|ar|nitrogen|n2|vacuum)\b", re.IGNORECASE)
_METHODS = ("XRD", "SEM", "TEM", "XPS", "Raman", "FTIR", "DSC", "TGA", "DMA")


class FakeCoreLLMStructuredExtractor:
    def extract_document_profile(self, payload: dict[str, Any]) -> StructuredDocumentProfile:
        title = str(payload.get("title") or "").strip()
        source_filename = str(payload.get("source_filename") or "").strip()
        lead_text = str(payload.get("abstract_or_lead_text") or "")
        headings = payload.get("headings") if isinstance(payload.get("headings"), list) else []

        heading_text = " ".join(str(item) for item in headings)
        combined_text = " ".join(part for part in (title, source_filename, heading_text, lead_text) if part)
        lowered_text = combined_text.lower()

        review_hits = sum(
            marker in lowered_text
            for marker in (
                "review",
                "overview",
                "survey",
                "recent advances",
                "progress in",
            )
        )
        methods_hits = sum(
            marker in lowered_text
            for marker in (
                "experimental",
                "materials and methods",
                "method",
                "methods",
                "experiment",
            )
        )
        characterization_hits = sum(
            marker in lowered_text
            for marker in (
                "characterization",
                "xrd",
                "sem",
                "tem",
                "xps",
                "ftir",
                "raman",
            )
        )
        procedural_hits = sum(
            marker in lowered_text
            for marker in (
                "mixed",
                "stir",
                "anneal",
                "annealed",
                "dried",
                "fabricated",
                "prepared",
                "sintered",
            )
        )
        results_hits = (
            len(_TEMP_PATTERN.findall(combined_text))
            + len(_TIME_PATTERN.findall(combined_text))
            + sum(
                marker in lowered_text
                for marker in ("mpa", "gpa", "%", "w/mk", "conductivity", "strength")
            )
        )

        experimental_score = (
            methods_hits + characterization_hits + procedural_hits + results_hits
        )

        warnings: list[str] = []
        if review_hits and experimental_score >= 3:
            doc_type = "mixed"
            protocol_extractable = "partial"
        elif review_hits:
            doc_type = "review"
            protocol_extractable = "no"
        elif experimental_score >= 5:
            doc_type = "experimental"
            protocol_extractable = "yes"
        elif experimental_score >= 2:
            doc_type = "experimental"
            protocol_extractable = "partial"
        else:
            doc_type = "uncertain"
            protocol_extractable = "uncertain"
            warnings.append("classification_uncertain")

        return StructuredDocumentProfile(
            doc_type=doc_type,
            protocol_extractable=protocol_extractable,
            protocol_extractability_signals=[],
            parsing_warnings=sorted(set(warnings)),
            confidence=0.86 if doc_type == "experimental" else 0.82 if doc_type == "review" else 0.78,
        )

    def extract_text_window_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        document_title = str(payload.get("document_title") or "")
        document_profile = payload.get("document_profile") or {}
        text_window = payload.get("text_window") or {}
        text = str(text_window.get("text") or "")
        heading_path = str(text_window.get("heading_path") or "")
        window_role = self._classify_text_window_role(heading_path, text)

        if (
            str(document_profile.get("doc_type") or "") == "review"
            and "experimental section" not in text.lower()
            and window_role != "methods"
        ):
            return StructuredExtractionBundle()

        material_system = self._infer_material_system(document_title, text)
        process_context = self._extract_process_context(text)
        methods = self._extract_methods(text)
        baseline_label = self._extract_baseline_label(text)

        method_facts: list[MethodFactPayload] = []
        sample_variants: list[SampleVariantPayload] = []
        test_conditions: list[ExtractedTestConditionPayload] = []
        baseline_references: list[BaselineReferencePayload] = []
        measurement_results: list[MeasurementResultPayload] = []

        if window_role == "methods":
            sentence = self._first_statement(text)
            if sentence:
                method_facts.append(
                    MethodFactPayload(
                        method_ref="section_process",
                        method_role="process",
                        method_name="sample preparation",
                        method_payload={
                            "temperatures_c": process_context.get("temperatures_c") or [],
                            "durations": process_context.get("durations") or [],
                            "atmosphere": process_context.get("atmosphere"),
                            "details": sentence,
                        },
                        anchors=[
                            EvidenceAnchorPayload(
                                quote=sentence,
                                source_type="method",
                            )
                        ],
                        confidence=0.82,
                    )
                )

        if window_role == "characterization" and methods:
            anchor = EvidenceAnchorPayload(
                quote=self._first_statement(text) or text[:160],
                source_type="text",
            )
            for index, method_name in enumerate(methods, start=1):
                method_facts.append(
                    MethodFactPayload(
                        method_ref=f"section_char_{index}",
                        method_role="characterization",
                        method_name=method_name,
                        method_payload={
                            "methods": [method_name],
                            "details": text[:400],
                        },
                        anchors=[anchor],
                        confidence=0.78,
                    )
                )

        property_sentences = [
            sentence
            for sentence in self._split_statements(text)
            if "|" not in sentence
            and not sentence.lower().startswith("table ")
            and self._infer_property(sentence) is not None
        ]
        if property_sentences:
            sample_variants.append(
                SampleVariantPayload(
                    variant_ref="default_variant",
                    variant_label=self._default_variant_label(
                        material_system.get("family"),
                        document_title,
                    ),
                    host_material_system=material_system,
                    composition=material_system.get("composition"),
                    variable_axis_type=None,
                    variable_value=None,
                    process_context=process_context,
                    confidence=0.66,
                    epistemic_status="inferred_with_low_confidence",
                    source_kind="text_window",
                )
            )

        if property_sentences and (
            methods
            or process_context.get("temperatures_c")
            or process_context.get("durations")
        ):
            property_name = self._infer_property(property_sentences[0]) or "qualitative"
            test_conditions.append(
                ExtractedTestConditionPayload(
                    test_condition_ref="section_tc",
                    property_type=property_name,
                    condition_payload={
                        "method": methods[0] if len(methods) == 1 else None,
                        "methods": methods,
                        "temperatures_c": process_context.get("temperatures_c") or [],
                        "durations": process_context.get("durations") or [],
                        "atmosphere": process_context.get("atmosphere"),
                    },
                    confidence=0.8,
                )
            )

        if property_sentences and baseline_label:
            baseline_references.append(
                BaselineReferencePayload(
                    baseline_ref="section_base",
                    baseline_label=baseline_label,
                    confidence=0.8,
                    epistemic_status="normalized_from_evidence",
                )
            )

        for index, sentence in enumerate(property_sentences, start=1):
            parsed = self._parse_result_sentence(sentence)
            if parsed is None:
                continue
            property_name = self._infer_property(sentence) or "qualitative"
            result_type, value_payload, unit = parsed
            measurement_results.append(
                MeasurementResultPayload(
                    result_ref=f"section_result_{index}",
                    claim_text=sentence,
                    property_normalized=property_name,
                    result_type=result_type,
                    value_payload=value_payload,
                    unit=unit,
                    variant_ref="default_variant",
                    test_condition_ref="section_tc" if test_conditions else None,
                    baseline_ref="section_base" if baseline_references else None,
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=sentence,
                            source_type="text",
                        )
                    ],
                    confidence=0.84,
                )
            )

        return StructuredExtractionBundle(
            method_facts=method_facts,
            sample_variants=sample_variants,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
            measurement_results=measurement_results,
        )

    def extract_table_row_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        document_title = str(payload.get("document_title") or "")
        document_profile = payload.get("document_profile") or {}
        row = payload.get("table_row") or {}
        supporting_windows = (
            payload.get("supporting_text_windows")
            if isinstance(payload.get("supporting_text_windows"), list)
            else []
        )
        if str(document_profile.get("doc_type") or "") == "review":
            return StructuredExtractionBundle()

        row_summary = str(row.get("row_summary") or "")
        cells = row.get("cells") if isinstance(row.get("cells"), list) else []
        support_text = "\n\n".join(
            str(window.get("text") or "").strip()
            for window in supporting_windows
            if isinstance(window, dict) and str(window.get("text") or "").strip()
        )

        material_system = self._infer_material_system(document_title, support_text or row_summary)
        process_context = self._extract_process_context(support_text)
        methods = self._extract_methods(support_text)

        sample_label = None
        variable_axis_type = None
        variable_value: str | int | float | None = None
        baseline_label = None
        property_cells: list[tuple[str, str, str | None]] = []

        for cell in cells:
            header = str(cell.get("header_path") or "")
            value = str(cell.get("cell_text") or "").strip()
            unit_hint = str(cell.get("unit_hint") or "").strip() or None
            if not value:
                continue
            lowered_header = header.lower()
            if any(token in lowered_header for token in ("sample", "group", "variant")):
                sample_label = value
                continue
            if "baseline" in lowered_header or "control" in lowered_header or "reference" in lowered_header:
                baseline_label = value
                continue
            property_name = self._infer_property(f"{header} {document_title}")
            if property_name is not None:
                property_cells.append((property_name, value, unit_hint or self._extract_unit(header)))
                continue
            if variable_axis_type is None:
                variable_axis_type = self._normalize_axis(header)
                variable_value = self._normalize_numeric_or_text(value)

        if not property_cells:
            return StructuredExtractionBundle()

        variant_label = sample_label or self._default_variant_label(
            material_system.get("family"),
            document_title,
        )
        sample_variants = [
            SampleVariantPayload(
                variant_ref="table_variant",
                variant_label=variant_label,
                host_material_system=material_system,
                composition=material_system.get("composition"),
                variable_axis_type=variable_axis_type,
                variable_value=variable_value,
                process_context=process_context,
                confidence=0.86,
                epistemic_status="normalized_from_evidence",
                source_kind="table_row",
            )
        ]

        test_conditions = [
            ExtractedTestConditionPayload(
                test_condition_ref="table_tc",
                property_type=property_cells[0][0],
                condition_payload={
                    "method": methods[0] if len(methods) == 1 else None,
                    "methods": methods,
                    "temperatures_c": process_context.get("temperatures_c") or [],
                    "durations": process_context.get("durations") or [],
                    "atmosphere": process_context.get("atmosphere"),
                },
                confidence=0.82,
            )
        ] if (
            methods
            or process_context.get("temperatures_c")
            or process_context.get("durations")
        ) else []

        baseline_references = [
            BaselineReferencePayload(
                baseline_ref="table_base",
                baseline_label=baseline_label,
                confidence=0.82,
                epistemic_status="normalized_from_evidence",
            )
        ] if baseline_label else []

        measurement_results: list[MeasurementResultPayload] = []
        for index, (property_name, value, unit) in enumerate(property_cells, start=1):
            parsed_value = self._normalize_numeric_or_text(value)
            if property_name == "retention":
                value_payload = MeasurementValuePayload(
                    retention_percent=float(parsed_value),
                    statement=f"{property_name} of {parsed_value} {unit or '%'}".strip(),
                )
                result_type = "retention"
                unit = unit or "%"
            else:
                value_payload = MeasurementValuePayload(
                    value=float(parsed_value),
                    statement=f"{property_name} of {parsed_value} {unit or ''}".strip(),
                )
                result_type = "scalar"
            measurement_results.append(
                MeasurementResultPayload(
                    result_ref=f"table_result_{index}",
                    claim_text=f"{variant_label} reported {property_name} of {parsed_value} {unit or ''}".strip(),
                    property_normalized=property_name,
                    result_type=result_type,
                    value_payload=value_payload,
                    unit=unit,
                    variant_ref="table_variant",
                    test_condition_ref="table_tc" if test_conditions else None,
                    baseline_ref="table_base" if baseline_references else None,
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=row_summary,
                            source_type="table",
                        )
                    ],
                    confidence=0.9,
                )
            )

        return StructuredExtractionBundle(
            sample_variants=sample_variants,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
            measurement_results=measurement_results,
        )

    def _classify_text_window_role(self, heading_path: str, text: str) -> str | None:
        lowered_heading = heading_path.lower()
        lowered_text = text.lower()
        if any(token in lowered_heading for token in ("experimental", "method", "methods", "materials and methods")):
            return "methods"
        if any(token in lowered_heading for token in ("characterization", "analysis")):
            return "characterization"
        if any(token in lowered_text for token in ("mixed", "annealed", "stirred", "dried", "sintered")):
            return "methods"
        if self._extract_methods(text) and "character" in lowered_text:
            return "characterization"
        return None

    def _infer_material_system(self, title: str, text: str):
        lowered = f"{title}\n{text}".lower()
        if "epoxy" in lowered:
            family = "epoxy composite"
        elif "ti alloy" in lowered or "titanium" in lowered:
            family = "Ti alloy"
        elif "ceramic" in lowered:
            family = "ceramic"
        elif "coating" in lowered:
            family = "coating"
        elif "composite" in lowered:
            family = "composite"
        else:
            family = "unspecified material system"
        return {"family": family, "composition": None}

    def _default_variant_label(self, family: str | None, title: str) -> str:
        if family and family != "unspecified material system":
            return family
        return title.strip() or "document sample"

    def _extract_process_context(self, text: str):
        temperatures = [float(match.group(1)) for match in _TEMP_PATTERN.finditer(text)]
        durations = [match.group(0) for match in _TIME_PATTERN.finditer(text)]
        atmosphere_match = _ATM_PATTERN.search(text)
        return {
            "temperatures_c": temperatures,
            "durations": durations,
            "atmosphere": atmosphere_match.group(1) if atmosphere_match else None,
        }

    def _extract_methods(self, text: str) -> list[str]:
        lowered = text.lower()
        return [method for method in _METHODS if method.lower() in lowered]

    def _extract_baseline_label(self, text: str) -> str | None:
        lowered = text.lower()
        if "as-built" in lowered:
            return "as-built"
        if "as-prepared" in lowered:
            return "as-prepared"
        if "untreated baseline" in lowered:
            return "untreated baseline"
        match = re.search(r"relative to the ([^.]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")
        return None

    def _infer_property(self, text: str) -> str | None:
        lowered = str(text or "").lower()
        if "yield strength" in lowered:
            return "yield_strength"
        if "tensile strength" in lowered:
            return "tensile_strength"
        if "flexural strength" in lowered:
            return "flexural_strength"
        if "strength" in lowered:
            return "tensile_strength"
        for token, normalized in _PROPERTY_HINTS:
            if token in lowered:
                return normalized
        return None

    def _parse_result_sentence(
        self,
        sentence: str,
    ) -> tuple[str, MeasurementValuePayload, str | None] | None:
        property_name = self._infer_property(sentence)
        if property_name is None:
            return None
        unit = self._extract_unit(sentence)
        numbers = [float(match.group(0)) for match in _FLOAT_PATTERN.finditer(sentence)]
        if not numbers:
            return None
        numeric_value = numbers[-1]
        if property_name == "retention":
            return (
                "retention",
                MeasurementValuePayload(
                    retention_percent=numeric_value,
                    statement=sentence,
                ),
                unit or "%",
            )
        return (
            "scalar",
            MeasurementValuePayload(
                value=numeric_value,
                statement=sentence,
            ),
            unit,
        )

    def _extract_unit(self, text: str) -> str | None:
        match = _PROPERTY_UNIT_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        explicit = re.search(r"\b(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK)\b", text, re.IGNORECASE)
        if explicit:
            return explicit.group(1)
        return None

    def _split_statements(self, text: str) -> list[str]:
        parts = re.split(r"[\n。]+|(?<=[.?!])\s+", text)
        return [part.strip() for part in parts if part.strip()]

    def _first_statement(self, text: str) -> str | None:
        statements = self._split_statements(text)
        return statements[0] if statements else None

    def _normalize_axis(self, header: str) -> str | None:
        lowered = header.lower()
        if "current" in lowered:
            return "induction_current"
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return normalized or None

    def _normalize_numeric_or_text(self, value: Any) -> str | int | float:
        text = str(value).strip()
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
            return float(text)
        return text

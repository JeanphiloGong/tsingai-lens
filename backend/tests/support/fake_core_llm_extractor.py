from __future__ import annotations

import re
from typing import Any

from application.core.semantic_build.llm.schemas import (
    MeasurementValuePayload,
    StructuredAxisCanonicalizationGroup,
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredObjectiveEvidenceRoute,
    StructuredObjectiveEvidenceRoutes,
    StructuredObjectiveEvidenceUnit,
    StructuredObjectiveEvidenceUnits,
    StructuredObjectivePaperFrame,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
    StructuredTableBatchMentions,
    StructuredTableBatchRowMentions,
    StructuredTableRowMentions,
    StructuredTextWindowMentions,
    TableRowBaselineMentionPayload,
    TableRowFactMentionPayload,
    TableRowResultClaimPayload,
    TableRowSubjectMentionPayload,
    TextWindowBaselineMentionPayload,
    TextWindowConditionMentionPayload,
    TextWindowMaterialMentionPayload,
    TextWindowMethodMentionPayload,
    TextWindowResultClaimPayload,
    TextWindowVariantMentionPayload,
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
        elif review_hits:
            doc_type = "review"
        elif experimental_score >= 5:
            doc_type = "experimental"
        elif experimental_score >= 2:
            doc_type = "experimental"
        else:
            doc_type = "uncertain"
            warnings.append("classification_uncertain")

        return StructuredDocumentProfile(
            doc_type=doc_type,
            parsing_warnings=sorted(set(warnings)),
            confidence=0.86 if doc_type == "experimental" else 0.82 if doc_type == "review" else 0.78,
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        title = str(payload.get("title") or "").strip()
        profile = payload.get("document_profile") if isinstance(payload.get("document_profile"), dict) else {}
        headings = payload.get("headings") if isinstance(payload.get("headings"), list) else []
        text_preview = str(payload.get("text_preview") or "")
        table_text = " ".join(
            str(item.get("caption_text") or "")
            for item in payload.get("table_captions", [])
            if isinstance(item, dict)
        )
        figure_text = " ".join(
            str(item.get("caption_text") or "")
            for item in payload.get("figure_captions", [])
            if isinstance(item, dict)
        )
        combined_text = " ".join(
            part
            for part in (
                title,
                " ".join(str(item) for item in headings),
                text_preview,
                table_text,
                figure_text,
            )
            if part
        )
        lowered_text = combined_text.lower()

        material_system = self._infer_material_system(title, combined_text)
        material_family = material_system.get("family")
        candidate_materials = (
            []
            if material_family == "unspecified material system"
            else [str(material_family)]
        )
        candidate_processes: list[str] = []
        if any(token in lowered_text for token in ("lpbf", "slm", "laser powder bed fusion")):
            candidate_processes.append("LPBF")
        if any(token in lowered_text for token in ("anneal", "heat treatment", "heated")):
            candidate_processes.append("heat treatment")
        if "mixed" in lowered_text or "stirred" in lowered_text:
            candidate_processes.append("mixing")

        candidate_properties = []
        property_name = self._infer_property(combined_text)
        if property_name:
            candidate_properties.append(property_name)
        changed_variables = []
        if self._extract_process_context(combined_text).get("temperatures_c"):
            changed_variables.append("temperature")
        if self._extract_process_context(combined_text).get("durations"):
            changed_variables.append("duration")
        if "anneal" in lowered_text:
            changed_variables.append("annealing")

        possible_objectives = []
        if candidate_materials and candidate_properties:
            process_phrase = (
                " and ".join(candidate_processes)
                if candidate_processes
                else "processing"
            )
            possible_objectives.append(
                f"How does {process_phrase} affect {candidate_properties[0]} of {candidate_materials[0]}?"
            )

        doc_role = str(profile.get("doc_type") or "").strip() or "uncertain"
        if doc_role not in {"experimental", "review", "mixed", "uncertain"}:
            doc_role = "uncertain"
        evidence_density = (
            "high"
            if possible_objectives
            else "medium" if candidate_materials or candidate_properties else "low"
        )
        return StructuredPaperSkim(
            doc_role=doc_role,
            candidate_materials=candidate_materials,
            candidate_processes=candidate_processes,
            candidate_properties=candidate_properties,
            changed_variables=changed_variables,
            possible_objectives=possible_objectives,
            evidence_density=evidence_density,
            confidence=0.86 if possible_objectives else 0.62,
            warnings=[] if possible_objectives else ["objective_uncertain"],
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        skims = payload.get("paper_skims") if isinstance(payload.get("paper_skims"), list) else []
        objectives: list[StructuredResearchObjective] = []
        seen_questions: set[str] = set()
        for skim in skims:
            if not isinstance(skim, dict):
                continue
            possible_objectives = skim.get("possible_objectives")
            if not isinstance(possible_objectives, list):
                possible_objectives = []
            candidate_question = next(
                (str(item).strip() for item in possible_objectives if str(item).strip()),
                "",
            )
            if not candidate_question:
                continue
            key = candidate_question.lower()
            if key in seen_questions:
                continue
            seen_questions.add(key)
            document_id = str(skim.get("document_id") or "").strip()
            objectives.append(
                StructuredResearchObjective(
                    question=candidate_question,
                    material_scope=[
                        str(item)
                        for item in skim.get("candidate_materials", [])
                        if str(item).strip()
                    ],
                    process_axes=[
                        str(item)
                        for item in skim.get("candidate_processes", [])
                        if str(item).strip()
                    ],
                    property_axes=[
                        str(item)
                        for item in skim.get("candidate_properties", [])
                        if str(item).strip()
                    ],
                    comparison_intent="compare process or treatment effects across papers",
                    seed_document_ids=[document_id] if document_id else [],
                    excluded_document_ids=[
                        str(item.get("document_id") or "").strip()
                        for item in skims
                        if isinstance(item, dict)
                        and str(item.get("doc_role") or "") == "review"
                        and str(item.get("document_id") or "").strip()
                    ],
                    confidence=0.82,
                    reason="derived from paper skim objective candidates",
                )
            )
        return StructuredResearchObjectives(objectives=objectives)

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        axis_candidates = (
            payload.get("axis_candidates")
            if isinstance(payload.get("axis_candidates"), dict)
            else {}
        )
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type=axis_type,
                    canonical=str(value),
                    aliases=[str(value)],
                    confidence=1.0,
                    reason="kept separate",
                )
                for axis_type, values in axis_candidates.items()
                if axis_type in {"material", "process", "property"}
                and isinstance(values, list)
                for value in values
                if str(value).strip()
            ]
        )

    def frame_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectivePaperFrame:
        objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
        paper_skim = payload.get("paper_skim") if isinstance(payload.get("paper_skim"), dict) else {}
        document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
        document_id = str(document.get("document_id") or "")
        table_summaries = (
            payload.get("table_summaries")
            if isinstance(payload.get("table_summaries"), list)
            else []
        )
        excluded_document_ids = {
            str(value)
            for value in objective.get("excluded_document_ids", [])
            if str(value).strip()
        }
        if document_id in excluded_document_ids or paper_skim.get("doc_role") == "review":
            return StructuredObjectivePaperFrame(
                relevance="irrelevant",
                paper_role="review",
                background="Paper does not directly support the objective.",
                excluded_tables=[
                    str(table.get("table_id"))
                    for table in table_summaries
                    if isinstance(table, dict) and table.get("table_id")
                ],
            )

        axes = [
            str(value).lower()
            for value in (
                *(objective.get("process_axes") or []),
                *(objective.get("property_axes") or []),
            )
            if str(value).strip()
        ]
        relevant_tables: list[str] = []
        excluded_tables: list[str] = []
        for table in table_summaries:
            if not isinstance(table, dict):
                continue
            table_id = str(table.get("table_id") or "")
            table_text = " ".join(
                str(value or "")
                for value in (
                    table.get("caption_text"),
                    table.get("heading_path"),
                    " ".join(str(item) for item in table.get("column_headers") or []),
                )
            ).lower()
            if table_id and any(axis in table_text for axis in axes):
                relevant_tables.append(table_id)
            elif table_id:
                excluded_tables.append(table_id)

        section_labels = [
            str(item.get("section_label"))
            for item in payload.get("section_snippets", [])
            if isinstance(item, dict) and item.get("section_label")
        ]
        return StructuredObjectivePaperFrame(
            relevance="high" if paper_skim else "uncertain",
            paper_role="primary_experiment",
            background="Paper directly supports the objective.",
            material_match=[
                str(item)
                for item in paper_skim.get("candidate_materials", [])
                if str(item).strip()
            ],
            changed_variables=[
                str(item)
                for item in paper_skim.get("changed_variables", [])
                if str(item).strip()
            ],
            measured_property_scope=[
                str(item)
                for item in objective.get("property_axes", [])
                if str(item).strip()
            ],
            test_environment_scope=[],
            relevant_sections=section_labels[:2],
            relevant_tables=relevant_tables,
            excluded_tables=excluded_tables,
        )

    def route_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceRoutes:
        objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
        property_axes = [
            str(value).lower()
            for value in objective.get("property_axes", [])
            if str(value).strip()
        ]
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        candidates = [payload["current_source"]]
        routes: list[StructuredObjectiveEvidenceRoute] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            source_kind = str(candidate.get("source_kind") or "text_window")
            source_ref = str(candidate.get("source_ref") or "")
            if not source_ref:
                continue
            if candidate.get("frame_status") == "excluded":
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        role="low_value_or_irrelevant",
                        extractable=False,
                        reason="Excluded by objective paper frame.",
                        confidence=0.7,
                    )
                )
                continue
            if source_kind == "table":
                table_schema = (
                    candidate.get("table_schema")
                    if isinstance(candidate.get("table_schema"), dict)
                    else {}
                )
                column_headers = (
                    table_schema.get("column_headers")
                    if isinstance(table_schema.get("column_headers"), list)
                    else candidate.get("column_headers")
                    if isinstance(candidate.get("column_headers"), list)
                    else []
                )
                table_text = " ".join(
                    str(value or "")
                    for value in (
                        candidate.get("caption_text"),
                        candidate.get("heading_path"),
                        " ".join(
                            str(item)
                            for item in column_headers
                        ),
                    )
                ).lower()
                role = (
                    "current_experimental_evidence"
                    if any(axis in table_text for axis in property_axes)
                    else "process_or_treatment"
                )
                routes.append(
                    StructuredObjectiveEvidenceRoute(
                        role=role,
                        extractable=True,
                        reason="Table is relevant to the active objective.",
                        confidence=0.82,
                    )
                )
                continue
            routes.append(
                StructuredObjectiveEvidenceRoute(
                    role="process_or_treatment",
                    extractable=True,
                    reason="Text window is in a relevant objective section.",
                    confidence=0.72,
                )
            )
        return StructuredObjectiveEvidenceRoutes(routes=routes)

    def extract_objective_evidence_units(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceUnits:
        route = payload.get("evidence_route")
        source = payload.get("source")
        if not isinstance(route, dict) or not isinstance(source, dict):
            return StructuredObjectiveEvidenceUnits()
        if route.get("source_kind") == "table":
            headers = [
                str(value)
                for value in source.get("column_headers", [])
                if str(value).strip()
            ]
            matrix = source.get("table_matrix") if isinstance(source.get("table_matrix"), list) else []
            property_header = next(
                (
                    header
                    for header in headers
                    if any(
                        token in header.lower()
                        for token in (
                            "strength",
                            "elongation",
                            "hardness",
                            "corrosion",
                            "density",
                        )
                    )
                ),
                headers[-1] if headers else "value",
            )
            units: list[StructuredObjectiveEvidenceUnit] = []
            for row in matrix[1:]:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                sample_label = str(row[0]).strip()
                value_text = str(row[-1]).strip()
                if not sample_label or not value_text:
                    continue
                units.append(
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="measurement",
                        property_normalized=property_header,
                        sample_context={"label": sample_label},
                        value_payload={"source_value_text": value_text},
                        join_keys={"sample_key": sample_label},
                        resolution_status="partial",
                        confidence=0.78,
                    )
                )
            return StructuredObjectiveEvidenceUnits(evidence_units=units)
        if route.get("source_kind") == "text_window" and source.get("text"):
            return StructuredObjectiveEvidenceUnits(
                evidence_units=[
                    StructuredObjectiveEvidenceUnit(
                        unit_kind="process_context",
                        value_payload={"statement": str(source.get("text"))[:160]},
                        resolution_status="partial",
                        confidence=0.7,
                    )
                ]
            )
        return StructuredObjectiveEvidenceUnits()

    def extract_text_window_mentions(self, payload: dict[str, Any]) -> StructuredTextWindowMentions:
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
            return StructuredTextWindowMentions()

        material_system = self._infer_material_system(document_title, text)
        process_context = self._extract_process_context(text)
        methods = self._extract_methods(text)
        baseline_label = self._extract_baseline_label(text)
        first_statement = self._first_statement(text)

        method_mentions: list[TextWindowMethodMentionPayload] = []
        material_mentions: list[TextWindowMaterialMentionPayload] = []
        variant_mentions: list[TextWindowVariantMentionPayload] = []
        condition_mentions: list[TextWindowConditionMentionPayload] = []
        baseline_mentions: list[TextWindowBaselineMentionPayload] = []
        result_claims: list[TextWindowResultClaimPayload] = []

        if window_role == "methods":
            if first_statement:
                method_mentions.append(
                    TextWindowMethodMentionPayload(
                        method_role="process",
                        method_name="sample preparation",
                        details=first_statement,
                        evidence_quote=first_statement,
                        confidence=0.82,
                    )
                )

        if window_role == "characterization" and methods:
            for index, method_name in enumerate(methods, start=1):
                evidence_quote = first_statement or text[:160]
                if evidence_quote:
                    method_mentions.append(
                        TextWindowMethodMentionPayload(
                        method_role="characterization",
                        method_name=method_name,
                        details=text[:400],
                        evidence_quote=evidence_quote,
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
            evidence_quote = property_sentences[0]
            material_label = self._default_variant_label(
                material_system.get("family"),
                document_title,
            )
            if material_system.get("family") and material_system.get("family") != "unspecified material system":
                material_mentions.append(
                    TextWindowMaterialMentionPayload(
                        material_label=material_label,
                        family=material_system.get("family"),
                        composition=material_system.get("composition"),
                        evidence_quote=evidence_quote,
                        confidence=0.72,
                    )
                )

        if first_statement:
            for temperature in process_context.get("temperatures_c") or []:
                condition_mentions.append(
                    TextWindowConditionMentionPayload(
                        condition_type="temperature",
                        condition_text=first_statement,
                        normalized_value=temperature,
                        unit="C",
                        evidence_quote=first_statement,
                        confidence=0.8,
                    )
                )
            for duration in process_context.get("durations") or []:
                condition_mentions.append(
                    TextWindowConditionMentionPayload(
                        condition_type="duration",
                        condition_text=duration,
                        normalized_value=None,
                        unit=None,
                        evidence_quote=first_statement,
                        confidence=0.8,
                    )
                )
            if process_context.get("atmosphere"):
                condition_mentions.append(
                    TextWindowConditionMentionPayload(
                        condition_type="atmosphere",
                        condition_text=first_statement,
                        normalized_value=process_context.get("atmosphere"),
                        unit=None,
                        evidence_quote=first_statement,
                        confidence=0.8,
                    )
                )

        if property_sentences and baseline_label:
            baseline_mentions.append(
                TextWindowBaselineMentionPayload(
                    baseline_label=baseline_label,
                    baseline_type="as-built" if baseline_label == "as-built" else "untreated" if "untreated" in baseline_label.lower() else "reference",
                    evidence_quote=property_sentences[0],
                    confidence=0.8,
                )
            )

        for index, sentence in enumerate(property_sentences, start=1):
            parsed = self._parse_result_sentence(sentence)
            property_name = self._infer_property(sentence) or "qualitative"
            claim_scope = self._classify_claim_scope(sentence)
            if parsed is None:
                result_type = "trend"
                unit = None
                value_text = None
            else:
                result_type, value_payload, unit = parsed
                value_text = sentence if value_payload.model_dump(exclude_none=True) else None
            result_claims.append(
                TextWindowResultClaimPayload(
                    claim_text=sentence,
                    property_normalized=property_name,
                    result_type=result_type,
                    value_text=value_text,
                    unit=unit,
                    claim_scope=claim_scope,
                    eligible_for_measurement_result=(claim_scope == "current_work"),
                    evidence_quote=sentence,
                    confidence=0.84,
                )
            )

        return StructuredTextWindowMentions(
            method_mentions=method_mentions,
            material_mentions=material_mentions,
            variant_mentions=variant_mentions,
            condition_mentions=condition_mentions,
            baseline_mentions=baseline_mentions,
            result_claims=result_claims,
        )

    def extract_table_batch_mentions(self, payload: dict[str, Any]) -> StructuredTableBatchMentions:
        document_title = str(payload.get("document_title") or "")
        document_profile = payload.get("document_profile") or {}
        supporting_windows = (
            payload.get("supporting_text_windows")
            if isinstance(payload.get("supporting_text_windows"), list)
            else []
        )
        target_rows = (
            payload.get("target_rows")
            if isinstance(payload.get("target_rows"), list)
            else []
        )
        if str(document_profile.get("doc_type") or "") == "review":
            return StructuredTableBatchMentions()

        row_results: list[StructuredTableBatchRowMentions] = []
        for row in target_rows:
            if not isinstance(row, dict):
                continue
            row_index = int(row.get("row_index") or 0)
            mentions = self._extract_table_row_mentions(
                document_title=document_title,
                row=row,
                supporting_windows=supporting_windows,
            )
            row_results.append(
                StructuredTableBatchRowMentions(
                    row_index=row_index,
                    **mentions.model_dump(),
                )
            )
        return StructuredTableBatchMentions(row_results=row_results)

    def _extract_table_row_mentions(
        self,
        *,
        document_title: str,
        row: dict[str, Any],
        supporting_windows: list[Any],
    ) -> StructuredTableRowMentions:
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
            return StructuredTableRowMentions()

        variant_label = sample_label or self._default_variant_label(
            material_system.get("family"),
            document_title,
        )
        row_subjects = [
            TableRowSubjectMentionPayload(
                variant_label=variant_label,
                family=material_system.get("family"),
                composition=material_system.get("composition"),
                variable_axis_type=variable_axis_type,
                variable_value=variable_value,
                quote=variant_label,
            )
        ]

        process_mentions: list[TableRowFactMentionPayload] = []
        for temperature in process_context.get("temperatures_c") or []:
            process_mentions.append(
                TableRowFactMentionPayload(
                    name="temperature_c",
                    value_text=temperature,
                    unit="C",
                    quote=f"{temperature:g} C",
                )
            )
        for duration in process_context.get("durations") or []:
            process_mentions.append(
                TableRowFactMentionPayload(
                    name="duration",
                    value_text=duration,
                    unit=None,
                    quote=duration,
                )
            )
        if process_context.get("atmosphere"):
            process_mentions.append(
                TableRowFactMentionPayload(
                    name="atmosphere",
                    value_text=process_context.get("atmosphere"),
                    unit=None,
                    quote=str(process_context.get("atmosphere")),
                )
            )

        test_condition_mentions = [
            TableRowFactMentionPayload(
                name="method",
                value_text=method,
                unit=None,
                quote=method,
            )
            for method in methods
        ]

        baseline_mentions = [
            TableRowBaselineMentionPayload(
                baseline_label=baseline_label,
                quote=baseline_label,
            )
        ] if baseline_label else []

        result_claims: list[TableRowResultClaimPayload] = []
        for index, (property_name, value, unit) in enumerate(property_cells, start=1):
            parsed_value = self._normalize_numeric_or_text(value)
            if property_name == "retention":
                result_type = "retention"
                unit = unit or "%"
            else:
                result_type = "scalar"
            result_claims.append(
                TableRowResultClaimPayload(
                    claim_text=f"{variant_label} reported {property_name} of {parsed_value} {unit or ''}".strip(),
                    property_normalized=property_name,
                    result_type=result_type,
                    value_text=value,
                    unit=unit,
                    variant_label=variant_label,
                    baseline_label=baseline_label if baseline_mentions else None,
                    claim_scope="current_work",
                    quote=row_summary,
                )
            )

        return StructuredTableRowMentions(
            row_subjects=row_subjects,
            process_mentions=process_mentions,
            test_condition_mentions=test_condition_mentions,
            baseline_mentions=baseline_mentions,
            result_claims=result_claims,
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
        if "316l" in lowered or "stainless steel" in lowered:
            family = "316L stainless steel"
        elif "epoxy" in lowered:
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

    def _classify_claim_scope(self, text: str) -> str:
        lowered = str(text or "").lower()
        if "previous work" in lowered:
            return "prior_work"
        if "review" in lowered or "survey" in lowered:
            return "review_summary"
        if "literature" in lowered or "reported in prior studies" in lowered:
            return "literature_summary"
        return "current_work"

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

from __future__ import annotations

import json
import os
import re
import textwrap
import unicodedata
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz
from openai import OpenAI

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
)
from application.derived.material_review_pipeline import MaterialReviewReportPipeline
from application.source.collection_service import CollectionService
from infra.persistence.file._json import read_json, write_json


_EVIDENCE_ID_PATTERN = re.compile(r"\bE\d{2,}\b")
_MARKDOWN_TITLE_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_MATERIAL_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_DEFAULT_REPORT_TYPE = "review_draft"
_DEFAULT_LANGUAGE = "zh"


class MaterialReviewReportNotFoundError(FileNotFoundError):
    """Raised when a material review report has not been requested yet."""

    def __init__(self, collection_id: str, material_id: str) -> None:
        self.collection_id = collection_id
        self.material_id = material_id
        super().__init__(f"material review report not found: {collection_id}/{material_id}")


class MaterialReviewReportNotReadyError(RuntimeError):
    """Raised when a material review report artifact is not ready to download."""

    def __init__(self, collection_id: str, material_id: str, status: str) -> None:
        self.collection_id = collection_id
        self.material_id = material_id
        self.status = status
        super().__init__(
            f"material review report is not ready: {collection_id}/{material_id}/{status}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _display_value(value: dict[str, Any]) -> str:
    display_value = _safe_text(value.get("display_value"))
    if display_value:
        return display_value
    raw_value = value.get("normalized_value", value.get("value"))
    if raw_value is None:
        return "--"
    unit = _safe_text(value.get("normalized_unit") or value.get("unit"))
    return f"{raw_value} {unit}".strip()


def _status_is_ready(status: str | None) -> bool:
    return status in {"ready", "ready_with_warnings"}


class MaterialReviewReportService:
    """Generate evidence-grounded AI review drafts for one material profile."""

    def __init__(
        self,
        *,
        collection_service: CollectionService | None = None,
        research_view_service: ResearchViewAggregationService | None = None,
        llm_client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.research_view_service = research_view_service or ResearchViewAggregationService()
        self.model = (
            model
            or os.getenv("MATERIAL_REVIEW_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        ).strip()
        self.llm_client = llm_client or OpenAI(
            api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
            base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        )
        self.pipeline = MaterialReviewReportPipeline(
            llm_client=self.llm_client,
            model=self.model,
        )

    def request_review_report(
        self,
        collection_id: str,
        material_id: str,
        *,
        language: str = _DEFAULT_LANGUAGE,
        report_type: str = _DEFAULT_REPORT_TYPE,
        include_appendix: bool = True,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        existing = self._read_metadata(collection_id, material_id)
        if existing and not force_regenerate:
            return self._with_urls(collection_id, material_id, existing)

        collection = self.collection_service.get_collection(collection_id)
        profile = self.research_view_service.get_collection_material_research_view(
            collection_id,
            material_id,
        )
        context_pack = self.build_context_pack(
            collection_id=collection_id,
            material_id=material_id,
            collection=collection,
            profile=profile,
            include_appendix=include_appendix,
        )
        data_version = self._context_data_version(context_pack)
        report_id = f"mrp_{uuid4().hex[:12]}"
        now = _now_iso()
        metadata = {
            "report_id": report_id,
            "collection_id": collection_id,
            "material_id": material_id,
            "status": "generating",
            "stage": "requested",
            "message": "Review draft generation started.",
            "title": self._default_title(profile),
            "language": language,
            "report_type": report_type,
            "include_appendix": include_appendix,
            "readiness": context_pack["review_readiness"]["level"],
            "readiness_reason": context_pack["review_readiness"]["reason"],
            "data_version": data_version,
            "warnings": [],
            "created_at": now,
            "updated_at": now,
            "generated_at": None,
        }
        paths = self._report_paths(collection_id, material_id)
        paths["base_dir"].mkdir(parents=True, exist_ok=True)
        write_json(paths["context"], context_pack)
        write_json(paths["metadata"], metadata)
        return self._with_urls(collection_id, material_id, metadata)

    def generate_review_report(
        self,
        collection_id: str,
        material_id: str,
        *,
        language: str = _DEFAULT_LANGUAGE,
        report_type: str = _DEFAULT_REPORT_TYPE,
        include_appendix: bool = True,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        metadata = self.request_review_report(
            collection_id,
            material_id,
            language=language,
            report_type=report_type,
            include_appendix=include_appendix,
            force_regenerate=force_regenerate,
        )
        if _status_is_ready(metadata.get("status")) and not force_regenerate:
            return metadata

        paths = self._report_paths(collection_id, material_id)
        try:
            context_pack = read_json(paths["context"], None)
            if context_pack is None:
                raise MaterialReviewReportNotFoundError(collection_id, material_id)
            def update_stage(stage: str, message: str) -> None:
                nonlocal metadata
                metadata = self._update_metadata_stage(
                    collection_id,
                    material_id,
                    metadata,
                    stage,
                    message,
                )

            pipeline_result = self.pipeline.run(
                context_pack,
                paths=paths,
                language=language,
                include_appendix=include_appendix,
                stage_callback=update_stage,
            )
            markdown = _safe_text(pipeline_result.get("markdown"))
            if not markdown:
                raise RuntimeError("material review generation returned empty markdown")
            validation = self.validate_markdown(markdown, context_pack)
            warnings = list(
                dict.fromkeys(
                    [
                        *[
                            _safe_text(item)
                            for item in _safe_list(pipeline_result.get("warnings"))
                            if _safe_text(item)
                        ],
                        *validation["warnings"],
                    ]
                )
            )
            status = "ready_with_warnings" if warnings else "ready"
            title = self._extract_title(markdown) or metadata.get("title") or self._default_title(
                context_pack.get("material", {})
            )
            self._write_text(paths["markdown"], markdown)
            metadata = self._update_metadata_stage(
                collection_id,
                material_id,
                metadata,
                "rendering_pdf",
                "Rendering PDF.",
            )
            self._render_pdf(
                markdown,
                paths["pdf"],
                title=title,
                language=language,
            )
            updated = {
                **metadata,
                "status": status,
                "stage": status,
                "message": (
                    "Review draft generated with evidence warnings."
                    if warnings
                    else "Review draft generated."
                ),
                "title": title,
                "warnings": warnings,
                "updated_at": _now_iso(),
                "generated_at": _now_iso(),
            }
            write_json(paths["metadata"], self._without_urls(updated))
            return self._with_urls(collection_id, material_id, updated)
        except Exception as exc:
            failed = {
                **self._without_urls(metadata),
                "status": "failed",
                "stage": "failed",
                "message": str(exc),
                "updated_at": _now_iso(),
            }
            write_json(paths["metadata"], failed)
            raise

    def get_review_report_status(self, collection_id: str, material_id: str) -> dict[str, Any]:
        metadata = self._read_metadata(collection_id, material_id)
        if metadata is None:
            raise MaterialReviewReportNotFoundError(collection_id, material_id)
        return self._with_urls(collection_id, material_id, metadata)

    def get_review_markdown(self, collection_id: str, material_id: str) -> str:
        metadata = self.get_review_report_status(collection_id, material_id)
        if not _status_is_ready(metadata.get("status")):
            raise MaterialReviewReportNotReadyError(
                collection_id,
                material_id,
                str(metadata.get("status") or "unknown"),
            )
        path = self._report_paths(collection_id, material_id)["markdown"]
        if not path.is_file():
            raise MaterialReviewReportNotReadyError(collection_id, material_id, "missing_markdown")
        return path.read_text(encoding="utf-8")

    def get_review_pdf_path(self, collection_id: str, material_id: str) -> Path:
        metadata = self.get_review_report_status(collection_id, material_id)
        if not _status_is_ready(metadata.get("status")):
            raise MaterialReviewReportNotReadyError(
                collection_id,
                material_id,
                str(metadata.get("status") or "unknown"),
            )
        path = self._report_paths(collection_id, material_id)["pdf"]
        if not path.is_file():
            raise MaterialReviewReportNotReadyError(collection_id, material_id, "missing_pdf")
        return path

    def build_context_pack(
        self,
        *,
        collection_id: str,
        material_id: str,
        collection: dict[str, Any],
        profile: dict[str, Any],
        include_appendix: bool,
    ) -> dict[str, Any]:
        evidence_index: dict[str, str] = {}
        evidence_table: list[dict[str, Any]] = []
        paper_titles = self._paper_titles(profile)

        def evidence_ids(refs: list[Any]) -> list[str]:
            ids: list[str] = []
            for ref in refs:
                ref_record = _safe_dict(ref)
                ref_key = self._evidence_ref_key(ref_record)
                if not ref_key:
                    continue
                if ref_key not in evidence_index:
                    evidence_id = f"E{len(evidence_index) + 1:02d}"
                    evidence_index[ref_key] = evidence_id
                    evidence_table.append(
                        {
                            "id": evidence_id,
                            "paper": paper_titles.get(
                                _safe_text(ref_record.get("document_id")),
                                _safe_text(ref_record.get("document_id")) or "--",
                            ),
                            "source_kind": _safe_text(ref_record.get("source_kind")) or "--",
                            "locator": self._locator_label(ref_record.get("locator")),
                            "confidence": ref_record.get("confidence"),
                            "traceability_status": _safe_text(
                                ref_record.get("traceability_status")
                            )
                            or "--",
                        }
                    )
                ids.append(evidence_index[ref_key])
            return sorted(set(ids))

        sample_process_matrix: list[dict[str, Any]] = []
        property_matrix: list[dict[str, Any]] = []
        sample_rows = _safe_list(_safe_dict(profile.get("sample_matrix")).get("rows"))
        for row in sample_rows:
            row_record = _safe_dict(row)
            row_evidence = evidence_ids(_safe_list(row_record.get("evidence_refs")))
            sample_id = _safe_text(row_record.get("sample_label")) or _safe_text(
                row_record.get("sample_id")
            )
            sample_process_matrix.append(
                {
                    "sample_id": sample_id,
                    "paper": paper_titles.get(
                        _safe_text(row_record.get("document_id")),
                        _safe_text(row_record.get("document_id")) or "--",
                    ),
                    "material": _safe_text(row_record.get("material"))
                    or _safe_text(profile.get("canonical_name")),
                    "variable_axis": _safe_text(row_record.get("variable_axis")),
                    "variable_value": row_record.get("variable_value"),
                    "process_parameters": _safe_dict(row_record.get("process_context")),
                    "evidence_ids": row_evidence,
                }
            )
            for key, value in _safe_dict(row_record.get("values")).items():
                value_record = _safe_dict(value)
                value_evidence = evidence_ids(_safe_list(value_record.get("evidence_refs")))
                property_matrix.append(
                    {
                        "sample_id": sample_id,
                        "paper": paper_titles.get(
                            _safe_text(row_record.get("document_id")),
                            _safe_text(row_record.get("document_id")) or "--",
                        ),
                        "property": _safe_text(value_record.get("label")) or key,
                        "value": _display_value(value_record),
                        "unit": _safe_text(value_record.get("unit"))
                        or _safe_text(value_record.get("normalized_unit")),
                        "status": _safe_text(value_record.get("status")) or "observed",
                        "confidence": value_record.get("confidence"),
                        "evidence_ids": value_evidence,
                    }
                )

        comparison_clusters: list[dict[str, Any]] = []
        trend_findings: list[dict[str, Any]] = []
        for group in _safe_list(profile.get("comparison_groups")):
            group_record = _safe_dict(group)
            matrix_rows = _safe_list(_safe_dict(group_record.get("matrix")).get("rows"))
            group_evidence = evidence_ids(_safe_list(group_record.get("evidence_refs")))
            for matrix_row in matrix_rows:
                matrix_record = _safe_dict(matrix_row)
                group_evidence.extend(evidence_ids(_safe_list(matrix_record.get("evidence_refs"))))
                result_record = _safe_dict(matrix_record.get("result"))
                group_evidence.extend(evidence_ids(_safe_list(result_record.get("evidence_refs"))))
            group_evidence = sorted(set(group_evidence))
            topic = _safe_text(group_record.get("title")) or "Material comparison cluster"
            comparison_clusters.append(
                {
                    "topic": topic,
                    "material_system": _safe_text(group_record.get("material_system")),
                    "process_family": _safe_text(group_record.get("process_family")),
                    "controlled_variables": _safe_dict(group_record.get("fixed_conditions")),
                    "variable_axis": _safe_text(group_record.get("variable_axis")),
                    "affected_properties": [
                        _safe_text(item) for item in _safe_list(group_record.get("properties"))
                    ],
                    "comparability_status": _safe_text(
                        group_record.get("comparability_status")
                    )
                    or "limited",
                    "observations": self._comparison_observations(matrix_rows, paper_titles),
                    "evidence_ids": group_evidence,
                }
            )
            trend_findings.append(
                {
                    "statement": (
                        f"{topic} contains {len(matrix_rows)} evidence-backed observations "
                        "for comparison and trend discussion."
                    ),
                    "finding_type": "direct_observation",
                    "supporting_evidence": group_evidence,
                    "confidence": self._confidence_from_status(
                        _safe_text(group_record.get("comparability_status"))
                    ),
                }
            )

        conflicting_findings = self._conflicting_findings(
            property_matrix,
            _safe_list(profile.get("warnings")),
        )
        limitations = self._limitations(profile, sample_process_matrix, property_matrix)
        research_gaps = self._research_gaps(
            profile=profile,
            sample_process_matrix=sample_process_matrix,
            property_matrix=property_matrix,
            comparison_clusters=comparison_clusters,
        )
        readiness = self._review_readiness(
            profile=profile,
            sample_count=len(sample_process_matrix),
            property_count=len(property_matrix),
            comparison_count=len(comparison_clusters),
            evidence_count=len(evidence_table),
        )

        return {
            "material": {
                "canonical_name": _safe_text(profile.get("canonical_name")) or material_id,
                "aliases": [_safe_text(item) for item in _safe_list(profile.get("aliases"))],
                "material_family": self._material_family(profile),
            },
            "literature_scope": {
                "collection_id": collection_id,
                "collection_name": _safe_text(collection.get("name")) or collection_id,
                "paper_count": _safe_dict(profile.get("overview")).get(
                    "paper_count",
                    len(_safe_list(profile.get("papers"))),
                ),
                "included_papers": self._included_papers(profile),
                "scope_note": (
                    "This review is based on the papers currently included in the user's "
                    "collection, not an exhaustive database-wide literature search."
                ),
            },
            "taxonomy": {
                "material_variants": sorted(
                    {
                        item["material"]
                        for item in sample_process_matrix
                        if _safe_text(item.get("material"))
                    }
                ),
                "process_families": _safe_dict(profile.get("overview")).get(
                    "process_families",
                    [],
                ),
                "process_parameters": sorted(
                    {
                        key
                        for row in sample_process_matrix
                        for key in _safe_dict(row.get("process_parameters")).keys()
                    }
                ),
                "property_groups": sorted(
                    {
                        _safe_text(row.get("property"))
                        for row in property_matrix
                        if _safe_text(row.get("property"))
                    }
                ),
                "test_conditions": [],
            },
            "sample_process_matrix": sample_process_matrix,
            "property_matrix": property_matrix,
            "comparison_clusters": comparison_clusters,
            "trend_findings": trend_findings,
            "conflicting_findings": conflicting_findings,
            "research_gaps": research_gaps,
            "evidence_table": evidence_table if include_appendix else [],
            "limitations": limitations,
            "review_readiness": readiness,
        }

    def validate_markdown(self, markdown: str, context_pack: dict[str, Any]) -> dict[str, Any]:
        known_evidence_ids = {
            _safe_text(item.get("id"))
            for item in _safe_list(context_pack.get("evidence_table"))
            if _safe_text(item.get("id"))
        }
        used_evidence_ids = set(_EVIDENCE_ID_PATTERN.findall(markdown))
        warnings: list[str] = []
        invalid_ids = sorted(used_evidence_ids - known_evidence_ids)
        if invalid_ids:
            warnings.append(
                "Invalid evidence ids generated: " + ", ".join(invalid_ids)
            )
        if known_evidence_ids and not used_evidence_ids:
            warnings.append("The generated report does not cite any evidence ids.")
        conclusion = self._section_text(markdown, "结论") or self._section_text(
            markdown,
            "Conclusion",
        )
        if conclusion and not _EVIDENCE_ID_PATTERN.search(conclusion):
            warnings.append("The conclusion section does not include evidence citations.")
        return {
            "known_evidence_ids": sorted(known_evidence_ids),
            "used_evidence_ids": sorted(used_evidence_ids),
            "warnings": warnings,
        }

    def _render_pdf(
        self,
        markdown: str,
        path: Path,
        *,
        title: str,
        language: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        margin_left = 68
        margin_top = 68
        page_width, page_height = fitz.paper_size("a4")
        margin_bottom = 64
        y = margin_top
        page = doc.new_page(width=page_width, height=page_height)
        font = "china-s"

        def new_page() -> fitz.Page:
            nonlocal y
            y = margin_top
            return doc.new_page(width=page_width, height=page_height)

        def add_line(line: str, size: float, spacing: float, color: tuple[float, float, float]):
            nonlocal page, y
            if y > page_height - margin_bottom:
                page = new_page()
            page.insert_text(
                (margin_left, y),
                line,
                fontname=font,
                fontsize=size,
                color=color,
            )
            y += spacing

        disclaimer = (
            "本文件为基于当前文献集合生成的 AI 辅助综述论文草稿，正式学术使用前需人工审阅。"
            if language == "zh"
            else "AI-assisted review draft based on the current literature collection. Human review is required before academic use."
        )
        add_line(title, 18, 28, (0.06, 0.09, 0.16))
        for wrapped in self._wrap_pdf_line(disclaimer, 10, max_units=62):
            add_line(wrapped, 10, 16, (0.39, 0.45, 0.55))
        y += 10

        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if not line:
                y += 8
                continue
            size, spacing, color, cleaned = self._markdown_line_style(line)
            max_units = 46 if size >= 16 else 62 if size >= 12 else 72
            for wrapped in self._wrap_pdf_line(cleaned, size, max_units=max_units):
                add_line(wrapped, size, spacing, color)

        temp_path = path.with_name(f".{path.name}.tmp")
        doc.save(temp_path)
        doc.close()
        temp_path.replace(path)

    def _markdown_line_style(
        self,
        line: str,
    ) -> tuple[float, float, tuple[float, float, float], str]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return 18, 26, (0.06, 0.09, 0.16), stripped[2:].strip()
        if stripped.startswith("## "):
            return 14, 22, (0.06, 0.09, 0.16), stripped[3:].strip()
        if stripped.startswith("### "):
            return 12, 19, (0.06, 0.09, 0.16), stripped[4:].strip()
        if stripped.startswith("|"):
            return 8.5, 13, (0.15, 0.19, 0.27), stripped
        cleaned = re.sub(r"[*_`]+", "", stripped)
        return 10.5, 17, (0.15, 0.19, 0.27), cleaned

    def _wrap_pdf_line(self, line: str, size: float, *, max_units: int) -> list[str]:
        if self._display_units(line) <= max_units:
            return [line]
        chunks: list[str] = []
        current = ""
        for char in line:
            candidate = f"{current}{char}"
            if current and self._display_units(candidate) > max_units:
                chunks.append(current)
                current = char
            else:
                current = candidate
        if current:
            chunks.append(current)
        if size <= 9:
            return chunks
        return [wrapped for chunk in chunks for wrapped in textwrap.wrap(chunk, width=max_units) or [chunk]]

    def _display_units(self, value: str) -> int:
        units = 0
        for char in value:
            units += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        return units

    def _report_paths(self, collection_id: str, material_id: str) -> dict[str, Path]:
        paths = self.collection_service.get_paths(collection_id)
        safe_material_id = _MATERIAL_ID_SAFE_PATTERN.sub("-", material_id).strip("-") or "material"
        base_dir = paths.output_dir / "material_review_reports" / safe_material_id
        return {
            "base_dir": base_dir,
            "metadata": base_dir / "report.json",
            "context": base_dir / "context_pack.json",
            "data_pack": base_dir / "data_pack.json",
            "outline": base_dir / "outline.json",
            "section_contexts": base_dir / "section_contexts.json",
            "sections": base_dir / "sections.json",
            "bound_claims": base_dir / "bound_claims.json",
            "review_notes": base_dir / "review_notes.json",
            "revisions": base_dir / "revisions.json",
            "markdown": base_dir / "review.md",
            "pdf": base_dir / "review.pdf",
        }

    def _read_metadata(self, collection_id: str, material_id: str) -> dict[str, Any] | None:
        return read_json(self._report_paths(collection_id, material_id)["metadata"], None)

    def _update_metadata_stage(
        self,
        collection_id: str,
        material_id: str,
        metadata: dict[str, Any],
        stage: str,
        message: str,
    ) -> dict[str, Any]:
        updated = {
            **self._without_urls(metadata),
            "status": "generating",
            "stage": stage,
            "message": message,
            "updated_at": _now_iso(),
        }
        write_json(self._report_paths(collection_id, material_id)["metadata"], updated)
        return updated

    def _write_text(self, path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(path)

    def _without_urls(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in metadata.items()
            if key not in {"pdf_url", "markdown_url"}
        }

    def _with_urls(
        self,
        collection_id: str,
        material_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(metadata)
        if _status_is_ready(_safe_text(payload.get("status"))):
            base = f"/api/v1/collections/{collection_id}/materials/{material_id}/review-report"
            payload["pdf_url"] = f"{base}.pdf"
            payload["markdown_url"] = f"{base}.md"
        else:
            payload["pdf_url"] = None
            payload["markdown_url"] = None
        return payload

    def _context_data_version(self, context_pack: dict[str, Any]) -> str:
        digest = sha256(
            json.dumps(context_pack, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        return f"material_profile:{digest}"

    def _paper_titles(self, profile: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for paper in _safe_list(profile.get("papers")):
            record = _safe_dict(paper)
            document_id = _safe_text(record.get("document_id"))
            if document_id:
                result[document_id] = (
                    _safe_text(record.get("title"))
                    or _safe_text(record.get("source_filename"))
                    or document_id
                )
        return result

    def _included_papers(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        papers: list[dict[str, Any]] = []
        for paper in _safe_list(profile.get("papers")):
            record = _safe_dict(paper)
            papers.append(
                {
                    "paper": _safe_text(record.get("title"))
                    or _safe_text(record.get("source_filename"))
                    or _safe_text(record.get("document_id"))
                    or "--",
                    "year": record.get("year"),
                    "sample_count": record.get("sample_count", 0),
                    "process_families": _safe_list(record.get("process_families")),
                    "measured_properties": _safe_list(record.get("measured_properties")),
                }
            )
        return papers

    def _evidence_ref_key(self, ref: dict[str, Any]) -> str:
        explicit = _safe_text(ref.get("evidence_ref_id"))
        if explicit:
            return explicit
        fact_ids = [_safe_text(item) for item in _safe_list(ref.get("fact_ids"))]
        anchor_ids = [_safe_text(item) for item in _safe_list(ref.get("anchor_ids"))]
        return "|".join([*fact_ids, *anchor_ids])

    def _locator_label(self, locator: Any) -> str:
        if isinstance(locator, dict):
            parts = [
                _safe_text(locator.get("page")),
                _safe_text(locator.get("table")),
                _safe_text(locator.get("figure")),
                _safe_text(locator.get("section")),
                _safe_text(locator.get("paragraph")),
                _safe_text(locator.get("label")),
            ]
            return " / ".join(part for part in parts if part) or "--"
        return _safe_text(locator) or "--"

    def _comparison_observations(
        self,
        rows: list[Any],
        paper_titles: dict[str, str],
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for row in rows[:60]:
            record = _safe_dict(row)
            result = _safe_dict(record.get("result"))
            observations.append(
                {
                    "paper": paper_titles.get(
                        _safe_text(record.get("document_id")),
                        _safe_text(record.get("document_id")) or "--",
                    ),
                    "sample_id": _safe_text(record.get("sample_label"))
                    or _safe_text(record.get("sample_id")),
                    "variable_value": record.get("variable_value"),
                    "property": _safe_text(record.get("property")),
                    "result": _display_value(result),
                    "test_condition": _safe_text(record.get("test_condition")),
                }
            )
        return observations

    def _conflicting_findings(
        self,
        property_matrix: list[dict[str, Any]],
        warnings: list[Any],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for row in property_matrix:
            if _safe_text(row.get("status")) == "conflicted":
                findings.append(
                    {
                        "topic": f"Conflicted value for {row.get('sample_id')} / {row.get('property')}",
                        "finding_a": row.get("value"),
                        "finding_b": "conflicting extracted values",
                        "possible_reason": "The source extraction returned a conflicted value state.",
                        "evidence_ids": row.get("evidence_ids", []),
                    }
                )
        for warning in warnings:
            record = _safe_dict(warning)
            message = _safe_text(record.get("message"))
            if "conflict" in message.lower() or "冲突" in message:
                findings.append(
                    {
                        "topic": _safe_text(record.get("code")) or "Profile warning",
                        "finding_a": message,
                        "finding_b": "",
                        "possible_reason": "Material profile warning from research-view aggregation.",
                        "evidence_ids": [],
                    }
                )
        return findings

    def _research_gaps(
        self,
        *,
        profile: dict[str, Any],
        sample_process_matrix: list[dict[str, Any]],
        property_matrix: list[dict[str, Any]],
        comparison_clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        if not sample_process_matrix:
            gaps.append(
                {
                    "gap": "Sample-level process information is not available.",
                    "basis": "The material profile sample matrix contains no sample rows.",
                    "evidence_ids": [],
                }
            )
        if not property_matrix:
            gaps.append(
                {
                    "gap": "Performance values are insufficient for a review-level synthesis.",
                    "basis": "The material profile property matrix contains no observed values.",
                    "evidence_ids": [],
                }
            )
        if not comparison_clusters:
            gaps.append(
                {
                    "gap": "Controlled comparison clusters are limited or unavailable.",
                    "basis": "The material profile returned no comparable groups.",
                    "evidence_ids": [],
                }
            )
        if not _safe_list(profile.get("condition_series")):
            gaps.append(
                {
                    "gap": "Condition-dependent behavior cannot yet be synthesized.",
                    "basis": "No condition series were returned for this material.",
                    "evidence_ids": [],
                }
            )
        return gaps

    def _limitations(
        self,
        profile: dict[str, Any],
        sample_process_matrix: list[dict[str, Any]],
        property_matrix: list[dict[str, Any]],
    ) -> list[str]:
        limitations = [
            "This report is based only on the current user collection and is not an exhaustive literature review.",
        ]
        if len(_safe_list(profile.get("papers"))) <= 2:
            limitations.append("The literature scope is small, so conclusions should be treated as preliminary.")
        if not sample_process_matrix:
            limitations.append("Sample and process matrices are missing or empty.")
        if not property_matrix:
            limitations.append("Measured property values are missing or empty.")
        if _safe_list(profile.get("warnings")):
            limitations.append("Research-view aggregation warnings are present and should be reviewed.")
        return limitations

    def _review_readiness(
        self,
        *,
        profile: dict[str, Any],
        sample_count: int,
        property_count: int,
        comparison_count: int,
        evidence_count: int,
    ) -> dict[str, str]:
        paper_count = int(_safe_dict(profile.get("overview")).get("paper_count") or len(_safe_list(profile.get("papers"))))
        if paper_count >= 10 and sample_count >= 20 and comparison_count >= 3 and evidence_count >= 30:
            return {
                "level": "strong",
                "reason": "The material profile has broad paper, sample, comparison, and evidence coverage.",
            }
        if paper_count >= 3 and sample_count >= 5 and property_count >= 5 and comparison_count >= 1:
            return {
                "level": "usable",
                "reason": "The material profile has enough matrix and comparison coverage for a usable review draft.",
            }
        if paper_count >= 1 and sample_count >= 1 and property_count >= 1:
            return {
                "level": "preliminary",
                "reason": "The material profile has limited coverage and is suitable for a preliminary review draft.",
            }
        return {
            "level": "insufficient",
            "reason": "The material profile lacks enough sample or performance data for review-level synthesis.",
        }

    def _material_family(self, profile: dict[str, Any]) -> str | None:
        name = _safe_text(profile.get("canonical_name")).lower()
        if "stainless" in name:
            return "stainless steel"
        if "steel" in name:
            return "steel"
        if "ti-" in name or "titanium" in name:
            return "titanium alloy"
        return None

    def _confidence_from_status(self, status: str) -> str:
        if status == "comparable":
            return "medium"
        if status == "limited":
            return "low"
        return "insufficient"

    def _extract_title(self, markdown: str) -> str | None:
        match = _MARKDOWN_TITLE_PATTERN.search(markdown)
        return match.group(1).strip() if match else None

    def _default_title(self, profile: dict[str, Any]) -> str:
        material_name = _safe_text(profile.get("canonical_name")) or _safe_text(
            profile.get("material_id")
        ) or "Material"
        return f"{material_name} processing-structure-property review draft"

    def _section_text(self, markdown: str, heading_keyword: str) -> str:
        pattern = re.compile(
            rf"^#+\s*[0-9.\s]*{re.escape(heading_keyword)}.*?$"
            rf"(?P<body>.*?)(?=^#+\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(markdown)
        return match.group("body").strip() if match else ""

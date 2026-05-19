from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from application.derived.material_review_pipeline import (
    MaterialReviewDataPackBuilder,
    OutlinePlanner,
)
from application.derived.material_review_report_service import (
    MaterialReviewReportService,
)
from domain.ports import CollectionPaths
from infra.persistence.file._json import read_json


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(_FakeMessage(content))]


class _FakeCompletions:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = content if isinstance(content, list) else [content]
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeCompletion:
        index = min(len(self.calls), len(self.contents) - 1)
        self.calls.append(kwargs)
        return _FakeCompletion(self.contents[index])


class _FakeChat:
    def __init__(self, content: str | list[str]) -> None:
        self.completions = _FakeCompletions(content)


class _FakeLLMClient:
    def __init__(self, content: str | list[str]) -> None:
        self.chat = _FakeChat(content)


class _FakeCollectionService:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        return {
            "id": collection_id,
            "name": "AM 316L papers",
        }

    def get_paths(self, collection_id: str) -> CollectionPaths:
        collection_dir = self.output_dir.parent
        return CollectionPaths(
            collection_dir=collection_dir,
            input_dir=collection_dir / "input",
            output_dir=self.output_dir,
            meta_path=collection_dir / "meta.json",
            files_path=collection_dir / "files.json",
            import_manifest_path=collection_dir / "import_manifest.json",
            artifacts_path=collection_dir / "artifacts.json",
        )


class _FakeResearchViewService:
    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict[str, Any]:
        return _material_profile(collection_id, material_id)


def _value(value: str, evidence_id: str, *, unit: str = "%") -> dict[str, Any]:
    return {
        "display_value": value,
        "value": value,
        "unit": unit,
        "status": "observed",
        "confidence": 0.91,
        "evidence_refs": [
            {
                "evidence_ref_id": evidence_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "locator": {"table": "Table 2"},
                "confidence": 0.95,
                "traceability_status": "located",
            }
        ],
        "duplicate_count": 0,
        "conflict_status": "none",
        "warnings": [],
    }


def _material_profile(collection_id: str, material_id: str) -> dict[str, Any]:
    return {
        "collection_id": collection_id,
        "material_id": material_id,
        "canonical_name": "316L stainless steel",
        "aliases": ["316L"],
        "state": "ready",
        "overview": {
            "paper_count": 1,
            "sample_count": 2,
            "comparison_count": 1,
            "evidence_count": 3,
            "process_families": ["LPBF"],
            "measured_properties": ["relative_density", "hardness"],
            "variable_axes": ["scan_strategy"],
        },
        "papers": [
            {
                "document_id": "paper-1",
                "title": "Paper A",
                "sample_count": 2,
                "process_families": ["LPBF"],
                "measured_properties": ["relative_density", "hardness"],
            }
        ],
        "sample_matrix": {
            "matrix_id": "material-sample-matrix",
            "document_id": None,
            "state": "ready",
            "columns": [],
            "rows": [
                {
                    "row_id": "row-1",
                    "document_id": "paper-1",
                    "sample_id": "S001",
                    "sample_label": "S001",
                    "material": "316L stainless steel",
                    "process_context": {
                        "laser_power_w": 200,
                        "scan_speed_mm_s": 800,
                        "energy_density_j_mm3": 70,
                    },
                    "variable_axis": "scan_strategy",
                    "variable_value": "strategy A",
                    "values": {
                        "relative_density": _value("95.4", "ev-density-s1"),
                        "hardness": _value("215.65", "ev-hardness-s1", unit="HV"),
                    },
                    "evidence_refs": [],
                    "warnings": [],
                },
                {
                    "row_id": "row-2",
                    "document_id": "paper-1",
                    "sample_id": "S002",
                    "sample_label": "S002",
                    "material": "316L stainless steel",
                    "process_context": {
                        "laser_power_w": 200,
                        "scan_speed_mm_s": 800,
                        "energy_density_j_mm3": 70,
                    },
                    "variable_axis": "scan_strategy",
                    "variable_value": "strategy B",
                    "values": {
                        "relative_density": _value("97.7", "ev-density-s2"),
                        "hardness": _value("192.275", "ev-hardness-s2", unit="HV"),
                    },
                    "evidence_refs": [],
                    "warnings": [],
                },
            ],
            "warnings": [],
        },
        "process_parameter_ranges": [],
        "measured_properties": [],
        "comparison_groups": [
            {
                "group_id": "grp-1",
                "title": "Effect of scanning strategy on density",
                "material_system": "316L stainless steel",
                "process_family": "LPBF",
                "variable_axis": "scan_strategy",
                "fixed_conditions": {"scan_speed_mm_s": 800},
                "properties": ["relative_density"],
                "comparability_status": "comparable",
                "matrix": {
                    "rows": [
                        {
                            "row_id": "cmp-1",
                            "document_id": "paper-1",
                            "sample_id": "S001",
                            "sample_label": "S001",
                            "variable_value": "strategy A",
                            "property": "relative_density",
                            "result": _value("95.4", "ev-density-s1"),
                            "evidence_refs": [],
                            "warnings": [],
                        },
                        {
                            "row_id": "cmp-2",
                            "document_id": "paper-1",
                            "sample_id": "S002",
                            "sample_label": "S002",
                            "variable_value": "strategy B",
                            "property": "relative_density",
                            "result": _value("97.7", "ev-density-s2"),
                            "evidence_refs": [],
                            "warnings": [],
                        }
                    ]
                },
                "evidence_refs": [],
                "warnings": [],
            }
        ],
        "condition_series": [],
        "evidence_refs": [],
        "debug_links": {},
        "warnings": [],
    }


def test_material_review_report_generates_markdown_pdf_and_warnings(tmp_path: Path):
    generic_markdown = "## 草稿\n\n不同工艺参数会显著影响材料性能。"
    service = MaterialReviewReportService(
        collection_service=_FakeCollectionService(tmp_path / "output"),
        research_view_service=_FakeResearchViewService(),
        llm_client=_FakeLLMClient(generic_markdown),
        model="fake-model",
    )

    payload = service.generate_review_report(
        "col-1",
        "mat-316l-stainless-steel",
        force_regenerate=True,
    )

    assert payload["status"] == "ready_with_warnings"
    assert payload["stage"] == "ready_with_warnings"
    assert payload["readiness"] == "preliminary"
    assert any("Only one paper is present" in item for item in payload["warnings"])
    assert payload["pdf_url"].endswith("/review-report.pdf")
    assert payload["markdown_url"].endswith("/review-report.md")
    generated_markdown = service.get_review_markdown("col-1", "mat-316l-stainless-steel")
    assert generated_markdown.startswith(
        "# 316L stainless steel 选择性激光熔化工艺-性能综述草稿"
    )
    assert "## 性能结果与样品级差异" in generated_markdown
    assert "## 单篇文献边界" in generated_markdown
    assert "## 附录：样品-工艺参数矩阵" in generated_markdown
    assert "## 附录：样品-性能数据矩阵" in generated_markdown
    assert "S001" in generated_markdown
    assert "200" in generated_markdown
    assert "95.4" in generated_markdown
    assert "97.7 [E03]" in generated_markdown
    assert service.get_review_pdf_path("col-1", "mat-316l-stainless-steel").is_file()
    assert service.llm_client.chat.completions.calls[0]["model"] == "fake-model"

    paths = service._report_paths("col-1", "mat-316l-stainless-steel")
    for key in [
        "data_pack",
        "outline",
        "section_contexts",
        "sections",
        "bound_claims",
        "review_notes",
        "revisions",
    ]:
        assert paths[key].is_file()
    data_pack = read_json(paths["data_pack"], {})
    outline = read_json(paths["outline"], {})
    assert data_pack["sample_design"]["sample_count"] == 2
    assert data_pack["computed_summaries"]["property_ranges"][0]["max"]["sample_id"] == "S002"
    assert "evidence_boundary" in [item["id"] for item in outline["sections"]]


def test_material_review_context_pack_uses_review_evidence_ids(tmp_path: Path):
    service = MaterialReviewReportService(
        collection_service=_FakeCollectionService(tmp_path / "output"),
        research_view_service=_FakeResearchViewService(),
        llm_client=_FakeLLMClient("# Draft"),
        model="fake-model",
    )

    context_pack = service.build_context_pack(
        collection_id="col-1",
        material_id="mat-316l-stainless-steel",
        collection={"name": "AM 316L papers"},
        profile=_material_profile("col-1", "mat-316l-stainless-steel"),
        include_appendix=True,
    )

    assert context_pack["material"]["canonical_name"] == "316L stainless steel"
    assert context_pack["sample_process_matrix"][0]["sample_id"] == "S001"
    assert context_pack["property_matrix"][0]["evidence_ids"] == ["E01"]
    assert context_pack["property_matrix"][1]["evidence_ids"] == ["E02"]
    assert context_pack["property_matrix"][2]["evidence_ids"] == ["E03"]
    assert context_pack["evidence_table"][0]["paper"] == "Paper A"
    assert context_pack["comparison_clusters"][0]["topic"] == (
        "Effect of scanning strategy on density"
    )


def test_material_review_data_pack_and_outline_are_evidence_bounded(tmp_path: Path):
    service = MaterialReviewReportService(
        collection_service=_FakeCollectionService(tmp_path / "output"),
        research_view_service=_FakeResearchViewService(),
        llm_client=_FakeLLMClient("# Draft"),
        model="fake-model",
    )
    context_pack = service.build_context_pack(
        collection_id="col-1",
        material_id="mat-316l-stainless-steel",
        collection={"name": "AM 316L papers"},
        profile=_material_profile("col-1", "mat-316l-stainless-steel"),
        include_appendix=True,
    )

    data_pack = MaterialReviewDataPackBuilder().build(context_pack)
    outline = OutlinePlanner().build(data_pack, language="zh")

    assert data_pack["literature_scope"]["scope_warning"] == "single_paper_only"
    assert data_pack["sample_design"]["sample_count"] == 2
    assert data_pack["property_matrix"]["properties"] == ["density", "hardness"]
    assert data_pack["computed_summaries"]["paired_comparisons"][0]["high"]["value"] == "97.7"
    assert "single_paper_scope" in [
        item["code"] for item in data_pack["quality_flags"]
    ]
    section_ids = [item["id"] for item in outline["sections"]]
    assert "evidence_boundary" in section_ids
    assert "cross_paper_consistency" not in section_ids
    assert all(item["required_data"] for item in outline["sections"])

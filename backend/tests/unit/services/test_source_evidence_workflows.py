from __future__ import annotations

import ast
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

from infra.source.config.source_runtime_config import GraphRagConfig
from infra.source.runtime.source_evidence import build_sections, build_table_cells
from infra.source.runtime.workflows.create_source_artifacts import _build_pdf_bundle


def test_default_source_pipeline_includes_sections_and_table_cells():
    factory_path = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "source"
        / "runtime"
        / "workflows"
        / "factory.py"
    )
    module = ast.parse(factory_path.read_text(encoding="utf-8"))

    workflow_names: list[str] | None = None
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != "_source_handoff_workflows":
            continue
        workflow_names = [
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        break

    assert workflow_names == [
        "create_source_artifacts",
    ]


def test_build_sections_emits_source_sections_with_locator_fields():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Composite Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {"id": "tu-1", "text": "Powders were mixed in ethanol and stirred for 2 h.", "document_ids": ["doc-1"]},
            {"id": "tu-2", "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.", "document_ids": ["doc-1"]},
        ]
    )

    sections = build_sections(documents, text_units)

    assert set(sections["section_type"]) == {"methods", "characterization"}
    assert set(sections["paper_id"]) == {"doc-1"}
    assert "page" in sections.columns
    assert "char_range" in sections.columns
    assert sections["page"].isna().all()
    assert sections["char_range"].isna().all()


def test_build_table_cells_extracts_pipe_delimited_rows():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Table Study",
                "text": "\n".join(
                    [
                        "Table 1 Conductivity Results",
                        "Sample | Conductivity (mS/cm) | Baseline",
                        "A | 12 | as-prepared",
                        "B | 18 | annealed",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(columns=["id", "text", "document_ids"])

    table_cells = build_table_cells(documents, text_units)

    assert not table_cells.empty
    assert set(table_cells["document_id"]) == {"doc-1"}
    data_cells = table_cells[table_cells["row_index"] == 1]
    assert "Conductivity (mS/cm)" in set(data_cells["header_path"].dropna())
    assert "mS/cm" in set(table_cells["unit_hint"].dropna())


def test_build_pdf_bundle_maps_docling_output_into_source_artifacts(monkeypatch, tmp_path):
    class FakeBBox:
        def __init__(self) -> None:
            self.l = 1.0
            self.t = 2.0
            self.r = 3.0
            self.b = 4.0
            self.coord_origin = SimpleNamespace(value="BOTTOMLEFT")

    class FakeProv:
        def __init__(self, page_no: int, start: int, end: int) -> None:
            self.page_no = page_no
            self.charspan = (start, end)

    class FakeTextItem:
        def __init__(self, text: str, label: str, start: int, end: int) -> None:
            self.text = text
            self.label = label
            self.prov = [FakeProv(1, start, end)]

    class FakeTableCell:
        def __init__(
            self,
            *,
            row_index: int,
            col_index: int,
            text: str,
            column_header: bool = False,
        ) -> None:
            self.start_row_offset_idx = row_index
            self.end_row_offset_idx = row_index + 1
            self.start_col_offset_idx = col_index
            self.end_col_offset_idx = col_index + 1
            self.text = text
            self.column_header = column_header
            self.row_header = False
            self.row_section = False
            self.bbox = FakeBBox()

    class FakeTable:
        def __init__(self) -> None:
            self.prov = [FakeProv(1, 0, 0)]
            self.data = SimpleNamespace(
                table_cells=[
                    FakeTableCell(row_index=0, col_index=0, text="Sample", column_header=True),
                    FakeTableCell(row_index=0, col_index=1, text="Strength (MPa)", column_header=True),
                    FakeTableCell(row_index=1, col_index=0, text="A"),
                    FakeTableCell(row_index=1, col_index=1, text="123"),
                ]
            )

    class FakeDocument:
        def __init__(self) -> None:
            self.texts = [
                FakeTextItem("Methods", "section_header", 0, 7),
                FakeTextItem("Powders were mixed and annealed at 600 C.", "text", 8, 48),
                FakeTextItem("Characterization", "section_header", 49, 65),
                FakeTextItem("XRD and SEM were used to characterize the sample.", "text", 66, 114),
            ]
            self.tables = [FakeTable()]

        def export_to_text(self) -> str:
            return "\n".join(item.text for item in self.texts)

    monkeypatch.setattr(
        "infra.source.runtime.workflows.create_source_artifacts._convert_pdf_document",
        lambda **_: FakeDocument(),
    )

    bundle = _build_pdf_bundle(
        row=pd.Series(
            {
                "id": "doc-1",
                "title": "paper.pdf",
                "creation_date": "2026-04-20T00:00:00+00:00",
                "source_path": "paper.pdf",
                "source_type": "pdf",
            }
        ),
        payload=b"%PDF-1.4 test",
        config=GraphRagConfig(root_dir=str(tmp_path)),
        converter=object(),
    )

    assert bundle.documents.iloc[0]["metadata"]["source_parser"] == "docling"
    assert set(bundle.sections["section_type"]) == {"methods", "characterization"}
    assert not bundle.table_cells.empty
    assert "Strength (MPa)" in set(bundle.table_cells["header_path"].dropna())
    assert "MPa" in set(bundle.table_cells["unit_hint"].dropna())

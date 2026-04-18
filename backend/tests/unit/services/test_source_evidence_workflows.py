from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

from retrieval.index.operations.source_evidence import build_sections, build_table_cells


def test_default_source_pipeline_includes_sections_and_table_cells():
    factory_path = (
        Path(__file__).resolve().parents[3]
        / "retrieval"
        / "index"
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
        "create_base_text_units",
        "create_final_documents",
        "create_final_text_units",
        "create_sections",
        "create_table_cells",
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

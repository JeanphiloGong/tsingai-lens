from __future__ import annotations

import json

import pandas as pd
import pytest

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.build_source_artifacts import build_source_artifacts


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_parse_research_text_preserves_traceback_and_current_failures(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    paper_text = "\n".join(
        [
            "Laser power and Ti-6Al-4V porosity",
            "Methods",
            "Ti-6Al-4V specimens were produced by laser powder bed fusion.",
            "Results",
            "Table 1 Porosity Results",
            "Laser power (W) | Porosity (%)",
            "100 | 2.0",
            "150 | 0.5",
        ]
    )
    (input_dir / "laser-porosity.txt").write_text(paper_text, encoding="utf-8")
    (input_dir / "damaged.txt").write_bytes(b"\xff\xfe")
    config = SourceRuntimeConfig(root_dir=str(tmp_path))

    bundle = await build_source_artifacts(config)

    assert isinstance(bundle, SourceArtifactBundle)
    assert len(bundle.documents) == 1
    document = bundle.to_documents()[0]
    assert document.text == paper_text
    assert document.title == "laser-porosity.txt"
    assert {"Methods", "Results"} <= set(bundle.blocks["text"])
    assert set(bundle.text_units["document_ids"].explode()) == {document.document_id}
    assert set(bundle.table_cells["id"]) == {document.document_id}
    assert set(bundle.table_cells["header_path"].dropna()) == {
        "Laser power (W)", "Porosity (%)"
    }
    assert "100 | 2.0" in set(bundle.table_rows["row_text"])

    output_dir = tmp_path / "output"
    for name, columns in (
        ("documents", DOCUMENTS_FINAL_COLUMNS),
        ("text_units", TEXT_UNITS_FINAL_COLUMNS),
        ("blocks", BLOCKS_FINAL_COLUMNS),
        ("figures", FIGURES_FINAL_COLUMNS),
        ("tables", TABLES_FINAL_COLUMNS),
        ("table_rows", TABLE_ROWS_FINAL_COLUMNS),
        ("table_cells", TABLE_CELLS_FINAL_COLUMNS),
    ):
        payload = json.loads((output_dir / f"{name}.json").read_text())
        assert payload["columns"] == columns
        assert len(payload["records"]) == len(getattr(bundle, name))
    diagnostics = json.loads((output_dir / "context.json").read_text())
    assert diagnostics["source_document_failures"] == []
    assert diagnostics["source_input_failures"][0]["source_path"] == "damaged.txt"
    assert diagnostics["source_input_failures"][0]["error_type"] == "UnicodeDecodeError"

    # An explicit retry inventory must not reload other files or old failures.
    retry = await build_source_artifacts(
        config,
        input_documents=pd.DataFrame(
            [{"id": document.document_id, "title": document.title, "text": paper_text}]
        ),
    )
    assert retry.to_documents()[0].text == paper_text
    assert retry.text_units["id"].tolist() == bundle.text_units["id"].tolist()
    assert json.loads((output_dir / "context.json").read_text()) == {
        "source_input_failures": [],
        "source_document_failures": [],
    }
    stats = json.loads((output_dir / "stats.json").read_text())
    assert stats["num_documents"] == 1
    assert stats["total_runtime"] >= stats["input_load_time"] >= 0

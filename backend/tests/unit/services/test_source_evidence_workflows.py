from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from PIL import Image
import pytest

from domain.source import resolve_heading_path_for_page
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
from infra.source.runtime.mapping.block_artifacts import collect_pdf_text_items
from infra.source.runtime.mapping.table_artifacts import build_pdf_table_cells
from infra.source.runtime.parsers.docling_pdf import build_pdf_bundle, build_pdf_converter
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)
from infra.source.runtime.workflows.create_source_artifacts import (
    create_source_artifacts,
)


def _source_bundle(document_id: str) -> SourceArtifactBundle:
    return SourceArtifactBundle(
        documents=pd.DataFrame(
            [
                {
                    "id": document_id,
                    "document_order": 0,
                    "title": f"{document_id}.pdf",
                    "text": "Readable research paper.",
                    "text_unit_ids": [],
                    "creation_date": None,
                    "metadata": {"source_parser": "docling"},
                }
            ],
            columns=DOCUMENTS_FINAL_COLUMNS,
        ),
        text_units=pd.DataFrame(columns=TEXT_UNITS_FINAL_COLUMNS),
        blocks=pd.DataFrame(columns=BLOCKS_FINAL_COLUMNS),
        figures=pd.DataFrame(columns=FIGURES_FINAL_COLUMNS),
        tables=pd.DataFrame(columns=TABLES_FINAL_COLUMNS),
        table_rows=pd.DataFrame(columns=TABLE_ROWS_FINAL_COLUMNS),
        table_cells=pd.DataFrame(columns=TABLE_CELLS_FINAL_COLUMNS),
        figure_assets={},
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_default_source_pipeline_uses_structure_first_handoff_workflow():
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


@pytest.mark.anyio
async def test_create_source_artifacts_keeps_valid_pdf_when_one_pdf_fails(
    monkeypatch,
    tmp_path,
):
    inventory = pd.DataFrame(
        [
            {
                "id": "doc-bad",
                "title": "damaged.pdf",
                "source_path": "stored-damaged.pdf",
            },
            {
                "id": "doc-good",
                "title": "valid.pdf",
                "source_path": "stored-valid.pdf",
            },
        ]
    )

    class InputStorage:
        async def get(self, path, **_kwargs):  # noqa: ANN001
            return {"stored-damaged.pdf": b"bad", "stored-valid.pdf": b"valid"}[path]

    def parse_pdf(*, row, **_kwargs):  # noqa: ANN001
        if row["id"] == "doc-bad":
            raise RuntimeError("PDFium data format error")
        return _source_bundle("doc-good")

    monkeypatch.setattr(
        "infra.source.runtime.workflows.create_source_artifacts.build_pdf_converter",
        lambda: object(),
    )
    monkeypatch.setattr(
        "infra.source.runtime.workflows.create_source_artifacts.build_pdf_bundle",
        parse_pdf,
    )
    context = SimpleNamespace(input_storage=InputStorage(), state={})

    result = await create_source_artifacts(
        inventory=inventory,
        config=SourceRuntimeConfig(root_dir=str(tmp_path)),
        context=context,
    )

    assert result.documents["id"].tolist() == ["doc-good"]
    assert context.state["source_document_failures"] == [
        {
            "source_path": "stored-damaged.pdf",
            "error_code": "source_pdf_parse_failed",
            "error_type": "RuntimeError",
        }
    ]


@pytest.mark.anyio
async def test_create_source_artifacts_fails_when_every_pdf_fails(
    monkeypatch,
    tmp_path,
):
    inventory = pd.DataFrame(
        [
            {
                "id": "doc-bad",
                "title": "damaged.pdf",
                "source_path": "stored-damaged.pdf",
            }
        ]
    )

    class InputStorage:
        async def get(self, _path, **_kwargs):  # noqa: ANN001
            return b"bad"

    monkeypatch.setattr(
        "infra.source.runtime.workflows.create_source_artifacts.build_pdf_converter",
        lambda: object(),
    )
    monkeypatch.setattr(
        "infra.source.runtime.workflows.create_source_artifacts.build_pdf_bundle",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("PDFium data format error")),
    )
    context = SimpleNamespace(input_storage=InputStorage(), state={})

    with pytest.raises(
        RuntimeError,
        match="Source parsing failed for all 1 input document",
    ):
        await create_source_artifacts(
            inventory=inventory,
            config=SourceRuntimeConfig(root_dir=str(tmp_path)),
            context=context,
        )


def test_build_blocks_emits_structure_first_blocks_with_heading_context():
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

    blocks = build_blocks(documents, text_units)

    assert set(blocks["document_id"]) == {"doc-1"}
    assert {"title", "heading", "paragraph"} <= set(blocks["block_type"])
    methods_blocks = blocks[blocks["heading_path"].astype(str).str.contains("Experimental Section", na=False)]
    assert not methods_blocks.empty
    assert methods_blocks["page"].isna().all()
    assert "char_range" not in methods_blocks


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


def test_build_pdf_table_cells_preserves_docling_logical_topology():
    cell = SimpleNamespace(
        start_row_offset_idx=0,
        end_row_offset_idx=2,
        start_col_offset_idx=1,
        end_col_offset_idx=4,
        text="Mechanical properties",
        column_header=True,
        row_header=False,
        row_section=True,
    )
    table = SimpleNamespace(
        data=SimpleNamespace(table_cells=[cell]),
        prov=[],
    )

    cells = build_pdf_table_cells(
        document_id="doc-1",
        document=SimpleNamespace(tables=[table]),
    )

    record = cells.iloc[0]
    assert record["row_span"] == 2
    assert record["col_span"] == 3
    assert bool(record["column_header"]) is True
    assert bool(record["row_header"]) is False
    assert bool(record["row_section"]) is True


def test_build_table_rows_extracts_row_level_evidence():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Table Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Table 1 Conductivity Results",
                        "Sample | Conductivity (mS/cm) | Baseline",
                        "A | 12 | as-prepared",
                        "B | 18 | annealed",
                    ]
                ),
            }
        ]
    )

    table_rows = build_table_rows(documents, None)

    assert len(table_rows) == 2
    assert set(table_rows["document_id"]) == {"doc-1"}
    assert set(table_rows["heading_path"].dropna()) == {"Experimental Section"}
    assert "A | 12 | as-prepared" in set(table_rows["row_text"])


def test_build_blocks_marks_figure_caption_lines_for_plain_text_inputs():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Figure Study",
                "text": "\n".join(
                    [
                        "Characterization",
                        "Figure 1 SEM image of the annealed powder.",
                        "The morphology remained porous after heat treatment.",
                    ]
                ),
            }
        ]
    )

    blocks = build_blocks(documents, None)

    figure_captions = blocks[blocks["block_type"] == "figure_caption"]
    assert len(figure_captions) == 1
    assert figure_captions.iloc[0]["text"] == "Figure 1 SEM image of the annealed powder."


def test_build_pdf_converter_uses_auto_docling_device_by_default(monkeypatch):
    monkeypatch.delenv("DOCLING_DEVICE", raising=False)

    converter = build_pdf_converter()

    assert _pdf_pipeline_device(converter) == "auto"


def test_build_pdf_converter_uses_docling_device_env(monkeypatch):
    monkeypatch.setenv("DOCLING_DEVICE", "cpu")

    converter = build_pdf_converter()

    assert _pdf_pipeline_device(converter) == "cpu"


def test_collect_pdf_text_items_excludes_figure_text_but_preserves_caption():
    class FakeBBox:
        def __init__(self, *, l: float, t: float, r: float, b: float) -> None:
            self.l = l
            self.t = t
            self.r = r
            self.b = b
            self.coord_origin = SimpleNamespace(value="BOTTOMLEFT")

    class FakeProv:
        def __init__(self, bbox: FakeBBox) -> None:
            self.page_no = 1
            self.charspan = (0, 1)
            self.bbox = bbox

    class FakeTextItem:
        def __init__(self, text: str, bbox: FakeBBox, label: str = "text") -> None:
            self.text = text
            self.label = label
            self.prov = [FakeProv(bbox)]

    class FakeRef:
        def __init__(self, cref: str) -> None:
            self.cref = cref

    body = FakeTextItem(
        "The porosity level decreased after preheating.",
        FakeBBox(l=72, t=760, r=540, b=730),
    )
    plot_tick = FakeTextItem(
        "(25-32[",
        FakeBBox(l=160, t=397, r=180, b=392),
    )
    caption = FakeTextItem(
        "Figure 4. Porosity measurement results.",
        FakeBBox(l=76, t=370, r=535, b=340),
        label="caption",
    )
    picture = SimpleNamespace(
        prov=[FakeProv(FakeBBox(l=76, t=714, r=535, b=379))],
        captions=[FakeRef("#/texts/2")],
    )
    document = SimpleNamespace(
        texts=[body, plot_tick, caption],
        pictures=[picture],
        tables=[],
    )

    text_items = collect_pdf_text_items(document)

    assert [item["text"] for item in text_items] == [
        "The porosity level decreased after preheating.",
        "Figure 4. Porosity measurement results.",
    ]


def test_build_pdf_bundle_maps_docling_output_into_source_artifacts(monkeypatch, tmp_path):
    class FakeBBox:
        def __init__(
            self,
            *,
            l: float = 1.0,
            t: float = 4.0,
            r: float = 3.0,
            b: float = 2.0,
        ) -> None:
            self.l = l
            self.t = t
            self.r = r
            self.b = b
            self.coord_origin = SimpleNamespace(value="BOTTOMLEFT")

    class FakeProv:
        def __init__(
            self,
            page_no: int,
            start: int,
            end: int,
            *,
            bbox: FakeBBox | None = None,
        ) -> None:
            self.page_no = page_no
            self.charspan = (start, end)
            self.bbox = bbox or FakeBBox()

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
        def __init__(self, caption_item: FakeTextItem) -> None:
            self.label = SimpleNamespace(value="table")
            self.captions = [FakeRef("#/texts/4", caption_item)]
            self.prov = [FakeProv(1, 0, 0)]
            self.data = SimpleNamespace(
                num_rows=2,
                num_cols=2,
                table_cells=[
                    FakeTableCell(row_index=0, col_index=0, text="Sample", column_header=True),
                    FakeTableCell(row_index=0, col_index=1, text="Strength (MPa)", column_header=True),
                    FakeTableCell(row_index=1, col_index=0, text="A"),
                    FakeTableCell(row_index=1, col_index=1, text="123"),
                ]
            )

        def caption_text(self, document) -> str:  # noqa: ANN001
            return self.captions[0].resolve(document).text

    class FakeRef:
        def __init__(self, cref: str, item: FakeTextItem) -> None:
            self.cref = cref
            self._item = item

        def resolve(self, document) -> FakeTextItem:  # noqa: ANN001
            return self._item

    class FakePicture:
        def __init__(self, caption_item: FakeTextItem) -> None:
            self.label = SimpleNamespace(value="picture")
            self.captions = [FakeRef("#/texts/5", caption_item)]
            self.prov = [
                FakeProv(
                    1,
                    115,
                    145,
                    bbox=FakeBBox(l=10.0, t=40.0, r=30.0, b=20.0),
                )
            ]

        def caption_text(self, document) -> str:  # noqa: ANN001
            return self.captions[0].resolve(document).text

        def get_image(self, document) -> Image.Image:  # noqa: ANN001
            return Image.new("RGB", (20, 10), color="white")

    class FakeDocument:
        def __init__(self) -> None:
            table_caption_item = FakeTextItem("Table 1 Mechanical results.", "caption", 115, 142)
            figure_caption_item = FakeTextItem("Figure 1 SEM image of the annealed powder.", "caption", 143, 184)
            self.texts = [
                FakeTextItem("Methods", "section_header", 0, 7),
                FakeTextItem("Powders were mixed and annealed at 600 C.", "text", 8, 48),
                FakeTextItem("Characterization", "section_header", 49, 65),
                FakeTextItem("XRD and SEM were used to characterize the sample.", "text", 66, 114),
                table_caption_item,
                figure_caption_item,
            ]
            self.tables = [FakeTable(table_caption_item)]
            self.pictures = [FakePicture(figure_caption_item)]

        def export_to_text(self) -> str:
            return "\n".join(item.text for item in self.texts)

    monkeypatch.setattr(
        "infra.source.runtime.parsers.docling_pdf.convert_pdf_document",
        lambda **_: FakeDocument(),
    )

    bundle = build_pdf_bundle(
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
        config=SourceRuntimeConfig(root_dir=str(tmp_path)),
        converter=object(),
    )

    assert bundle.documents.iloc[0]["metadata"]["source_parser"] == "docling"
    assert not bundle.blocks.empty
    assert {"heading", "paragraph", "figure_caption"} <= set(bundle.blocks["block_type"])
    assert not bundle.figures.empty
    assert bundle.figures.iloc[0]["caption_text"] == "Figure 1 SEM image of the annealed powder."
    assert bundle.figures.iloc[0]["image_path"].startswith("image_assets/")
    assert bundle.figures.iloc[0]["image_mime_type"] == "image/png"
    assert bundle.figures.iloc[0]["image_width"] == 20
    assert bundle.figures.iloc[0]["caption_block_id"] == "blk_doc-1_7"
    assert bundle.figures.iloc[0]["figure_label"] == "Figure 1"
    assert bundle.figure_assets
    assert not bundle.tables.empty
    table = bundle.tables.iloc[0]
    assert table["caption_text"] == "Table 1 Mechanical results."
    assert table["caption_block_id"] == "blk_doc-1_6"
    assert table["row_count"] == 2
    assert table["col_count"] == 2
    assert table["column_headers"] == ["Sample", "Strength (MPa)"]
    assert table["table_matrix"] == [["Sample", "Strength (MPa)"], ["A", "123"]]
    assert "| Sample | Strength (MPa) |" in table["table_markdown"]
    assert "A | 123" in table["table_text"]
    assert not bundle.table_rows.empty
    assert len(bundle.table_rows) == 1
    assert bundle.table_rows["row_id"].is_unique
    assert not bundle.table_cells.empty
    assert set(bundle.tables["table_id"]) == set(bundle.table_rows["table_id"])
    assert "Strength (MPa)" in set(bundle.table_cells["header_path"].dropna())
    assert "MPa" in set(bundle.table_cells["unit_hint"].dropna())


def test_build_pdf_bundle_skips_garbled_pdf_text_items(monkeypatch, tmp_path):
    class FakeProv:
        def __init__(self, page_no: int, start: int, end: int) -> None:
            self.page_no = page_no
            self.charspan = (start, end)
            self.bbox = None

    class FakeTextItem:
        def __init__(self, text: str, label: str, start: int, end: int) -> None:
            self.text = text
            self.label = label
            self.prov = [FakeProv(1, start, end)]

    class FakeDocument:
        def __init__(self) -> None:
            self.texts = [
                FakeTextItem("4DWHULDOV xFLHQFH c (QJLQHHULQJ E OiU iSiUG lnyfvf", "text", 0, 50),
                FakeTextItem("Readable methods text remains.", "text", 51, 81),
            ]
            self.tables = []
            self.pictures = []

        def export_to_text(self) -> str:
            return "\n".join(item.text for item in self.texts)

    monkeypatch.setattr(
        "infra.source.runtime.parsers.docling_pdf.convert_pdf_document",
        lambda **_: FakeDocument(),
    )

    bundle = build_pdf_bundle(
        row=pd.Series(
            {
                "id": "doc-1",
                "title": "paper.pdf",
                "source_path": "paper.pdf",
                "source_type": "pdf",
            }
        ),
        payload=b"%PDF-1.4 test",
        config=SourceRuntimeConfig(root_dir=str(tmp_path)),
        converter=object(),
    )

    block_text = "\n".join(bundle.blocks["text"].astype(str).tolist())
    text_unit_text = "\n".join(bundle.text_units["text"].astype(str).tolist())
    assert "Readable methods text remains." in block_text
    assert "Readable methods text remains." in text_unit_text
    assert "4DWHULDOV" not in block_text
    assert "4DWHULDOV" not in text_unit_text


def _pdf_pipeline_device(converter) -> str:  # noqa: ANN001
    from docling.datamodel.base_models import InputFormat

    return str(converter.format_to_options[InputFormat.PDF].pipeline_options.accelerator_options.device)


def test_heading_path_binding_uses_last_heading_at_or_before_page():
    heading_blocks = [
        {
            "page": 1,
            "heading_path": "Introduction",
            "block_order": 1,
            "block_type": "heading",
        },
        {
            "page": 1,
            "heading_path": "Results > Mechanical Properties",
            "block_order": 2,
            "block_type": "heading",
        },
        {
            "page": 1,
            "heading_path": "Appendix",
            "block_order": 3,
            "block_type": "heading",
        },
    ]

    assert (
        resolve_heading_path_for_page(1, heading_blocks)
        == "Appendix"
    )

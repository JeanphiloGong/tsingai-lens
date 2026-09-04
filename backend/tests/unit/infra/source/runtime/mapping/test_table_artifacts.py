from __future__ import annotations

from types import SimpleNamespace

from infra.source.runtime.mapping.table_artifacts import (
    build_docling_header_paths,
    build_docling_header_row_count,
    build_pdf_table_cells,
    extract_pdf_table_visual_text,
)


def _cell(
    *,
    text: str,
    row: int,
    col: int,
    column_header: bool = False,
    row_header: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=col,
        end_col_offset_idx=col + 1,
        column_header=column_header,
        row_header=row_header,
    )


def test_pdf_table_cells_bind_column_header_to_row_header_data_cells():
    document = SimpleNamespace(
        tables=[
            SimpleNamespace(
                prov=[],
                data=SimpleNamespace(
                    table_cells=[
                        _cell(text="Specimens", row=0, col=0, column_header=True),
                        _cell(text="Density (%)", row=0, col=1, column_header=True),
                        _cell(text="as-SLM (140/", row=1, col=0, row_header=True),
                        _cell(text="92.19", row=1, col=1),
                    ]
                ),
            )
        ]
    )

    records = build_pdf_table_cells(document_id="doc-p004", document=document).to_dict(
        orient="records"
    )

    specimen_cell = next(record for record in records if record["cell_text"] == "as-SLM (140/")
    density_cell = next(record for record in records if record["cell_text"] == "92.19")
    assert specimen_cell["header_path"] == "Specimens"
    assert density_cell["header_path"] == "Density (%)"


def test_docling_continuation_label_is_not_a_scientific_header_parent():
    document_table = SimpleNamespace(
        data=SimpleNamespace(
            table_cells=[
                _cell(
                    text="Table 2 (continued)",
                    row=0,
                    col=0,
                    column_header=True,
                ),
                _cell(text="Specimens", row=1, col=0, column_header=True),
                _cell(text="Density (%)", row=1, col=1, column_header=True),
            ]
        )
    )

    assert build_docling_header_paths(document_table) == {
        0: "Specimens",
        1: "Density (%)",
    }
    assert build_docling_header_row_count(document_table) == 2


def test_extract_pdf_table_visual_text_preserves_continuous_page_layout():
    import fitz

    pdf = fitz.open()
    page = pdf.new_page(width=300, height=300)
    page.insert_text((30, 50), "Specimens   Yield Strength (MPa)")
    page.insert_text((30, 75), "as-SLM(100/")
    page.insert_text((30, 90), "  100)       441.5 (±15.0)")
    payload = pdf.tobytes()
    pdf.close()

    class FakeBBox:
        l = 20
        t = 20
        r = 280
        b = 120

    table = SimpleNamespace(
        prov=[SimpleNamespace(page_no=1, bbox=FakeBBox())],
    )

    visual_text = extract_pdf_table_visual_text(payload=payload, table=table)

    assert visual_text is not None
    assert "Specimens" in visual_text
    assert "as-SLM(100/" in visual_text
    assert "441.5" in visual_text

from __future__ import annotations

from types import SimpleNamespace

from infra.source.runtime.mapping.table_artifacts import build_pdf_table_cells


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
        bbox=None,
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

"""Test construction for the fixed Source artifact table contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from infra.source.artifact_bundle import SourceArtifactBundle
from domain.source import SourceDocument


def build_source_documents(
    *,
    documents: Iterable[Mapping[str, Any]],
    text_units: Iterable[Mapping[str, Any]] = (),
    blocks: Iterable[Mapping[str, Any]] = (),
    tables: Iterable[Mapping[str, Any]] = (),
    table_rows: Iterable[Mapping[str, Any]] = (),
    table_cells: Iterable[Mapping[str, Any]] = (),
    figures: Iterable[Mapping[str, Any]] = (),
) -> tuple[SourceDocument, ...]:
    """Build test documents through the same fixed columns as production."""

    def frame(records: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
        values = pd.DataFrame(records)
        return values.where(pd.notna(values), None)

    return SourceArtifactBundle(
        documents=frame(documents),
        text_units=frame(text_units),
        blocks=frame(blocks),
        figures=frame(figures),
        tables=frame(tables),
        table_rows=frame(table_rows),
        table_cells=frame(table_cells),
        figure_assets={},
    ).to_documents()

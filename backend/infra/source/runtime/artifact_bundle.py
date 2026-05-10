from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from domain.source import SourceArtifactSet


@dataclass(frozen=True)
class SourceArtifactBundle:
    documents: pd.DataFrame
    text_units: pd.DataFrame
    blocks: pd.DataFrame
    figures: pd.DataFrame
    tables: pd.DataFrame
    table_rows: pd.DataFrame
    table_cells: pd.DataFrame
    figure_assets: dict[str, bytes]

    def to_artifact_set(self) -> SourceArtifactSet:
        return SourceArtifactSet.from_records(
            documents=_records(self.documents),
            text_units=_records(self.text_units),
            blocks=_records(self.blocks),
            figures=_records(self.figures),
            tables=_records(self.tables),
            table_rows=_records(self.table_rows),
            table_cells=_records(self.table_cells),
        )


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return frame.to_dict(orient="records")

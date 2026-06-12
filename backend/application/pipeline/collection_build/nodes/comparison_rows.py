from __future__ import annotations

from application.core.comparison_service import ComparisonRowsNotReadyError
from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    try:
        comparison_rows = context.services["comparison_service"].build_comparison_rows(
            context.collection_id
        )
    except ComparisonRowsNotReadyError:
        comparison_rows = ()
    if not comparison_rows:
        return {"warnings": ["未生成 comparison rows，当前 collection 还不能直接做结构化比较。"]}
    return {"comparison_row_count": len(comparison_rows)}

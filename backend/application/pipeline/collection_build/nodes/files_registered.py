from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    files = context.collection_service.list_files(context.collection_id)
    if not files:
        raise RuntimeError("集合内没有可构建文件")
    context.state["file_count"] = len(files)
    return {}

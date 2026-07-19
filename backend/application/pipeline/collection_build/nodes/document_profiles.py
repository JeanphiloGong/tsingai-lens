from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    profiles = context.services["document_profile_service"].build_document_profiles(
        context.collection_id,
        build_id=context.build_id,
    )
    return {"profile_count": len(profiles)}

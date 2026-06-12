from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    evidence_cards = context.services["paper_facts_service"].build_evidence_cards(
        context.collection_id
    )
    if not evidence_cards:
        return {"warnings": ["未抽取到 evidence cards，collection 暂时只能依赖 document profiles。"]}
    return {"evidence_card_count": len(evidence_cards)}

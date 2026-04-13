from __future__ import annotations

import pytest

from application.collections.service import CollectionService
from application.goals.service import GoalService


def test_goal_service_creates_seed_collection_and_contract(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalService(collection_service)

    payload = service.intake_goal(
        material_system="LiFePO4",
        target_property="rate capability",
        intent="compare",
        constraints={"temperature": "298 K"},
        context="Focus on battery cathode studies.",
        max_seed_documents=24,
    )

    collection_id = payload["seed_collection"]["collection_id"]
    collection = collection_service.get_collection(collection_id)

    assert payload["research_brief"]["objective"] == "Assess rate capability for LiFePO4."
    assert payload["coverage_assessment"]["level"] == "direct"
    assert payload["entry_recommendation"]["recommended_mode"] == "comparison"
    assert payload["seed_collection"]["created"] is True
    assert payload["seed_collection"]["seeded_document_count"] == 0
    assert collection["collection_id"] == collection_id
    assert collection["description"] == "Assess rate capability for LiFePO4."


def test_goal_service_rejects_empty_goal_signal(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalService(collection_service)

    with pytest.raises(ValueError) as exc_info:
        service.intake_goal(
            material_system=None,
            target_property=None,
            intent="explore",
            constraints={},
            context=None,
            max_seed_documents=30,
        )

    assert "至少提供" in str(exc_info.value)

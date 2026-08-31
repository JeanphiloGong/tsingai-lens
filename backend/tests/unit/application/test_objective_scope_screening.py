from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.core.objectives.research_objective_service import (
    ObjectiveScopeNotReadyError,
    ResearchObjectiveService,
)
from application.core.objectives.scope_screening import screen_objective_scope
from domain.core import PaperResearchMap, ResearchObjective


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _objective(*, seed_document_ids: tuple[str, ...] = ("paper-seed",)) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "question": "How does laser power affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["elongation"],
            "seed_document_ids": list(seed_document_ids),
            "confidence": 0.8,
        }
    )


def _experimental_map(
    document_id: str,
    *,
    material: str = "Ti-6Al-4V",
    factor: str = "laser power",
    outcome: str = "elongation",
    map_status: str = "sufficient",
) -> PaperResearchMap:
    studies = []
    if map_status == "sufficient":
        studies = [
            {
                "study_id": f"study-{document_id}",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": [material],
                "relationships": [
                    {
                        "relationship_id": f"rel-{document_id}",
                        "varied_factors": [factor],
                        "outcome": outcome,
                        "source_refs": [
                            {"source_kind": "block", "source_ref": "block-1"}
                        ],
                        "confidence": 0.8,
                    }
                ],
            }
        ]
    return PaperResearchMap.from_mapping(
        {
            "document_id": document_id,
            "doc_role": "experimental",
            "studies": studies,
            "map_status": map_status,
            "map_limitations": (
                ["High-level Sources did not establish the target outcome."]
                if map_status != "sufficient"
                else []
            ),
        }
    )


def test_non_seed_matching_paper_is_recommended_for_analysis() -> None:
    objective = _objective()

    preview = screen_objective_scope(
        (_experimental_map("paper-seed"), _experimental_map("paper-not-a-seed")),
        objective=objective,
    )

    assert preview.recommended_document_ids == (
        "paper-seed",
        "paper-not-a-seed",
    )
    assert preview.decisions[0].is_seed is True
    assert preview.decisions[1].is_seed is False


def test_incomplete_map_requires_researcher_inspection() -> None:
    preview = screen_objective_scope(
        (_experimental_map("paper-uncertain", map_status="insufficient_map"),),
        objective=_objective(seed_document_ids=()),
    )

    assert preview.recommended_document_ids == ()
    assert preview.review_document_ids == ("paper-uncertain",)
    assert preview.decisions[0].reason == "paper_map_incomplete"


def test_specific_material_conflict_is_confidently_out_of_scope() -> None:
    preview = screen_objective_scope(
        (
            _experimental_map(
                "paper-316l",
                material="316L",
                factor="solution treatment temperature",
                outcome="corrosion potential",
            ),
        ),
        objective=_objective(seed_document_ids=()),
    )

    assert preview.excluded_document_ids == ("paper-316l",)
    assert preview.decisions[0].reason == "material_scope_conflict"


def test_scope_preview_does_not_truncate_a_131_paper_collection() -> None:
    maps = tuple(_experimental_map(f"paper-{position:03d}") for position in range(131))

    preview = screen_objective_scope(
        maps,
        objective=_objective(seed_document_ids=("paper-000",)),
    )

    assert len(preview.decisions) == 131
    assert len(preview.recommended_document_ids) == 131
    assert preview.counts == {
        "likely_relevant": 131,
        "needs_inspection": 0,
        "confidently_out_of_scope": 0,
    }
    assert len(set(item.document_id for item in preview.decisions)) == 131


def test_review_citation_lead_is_navigation_for_inspection_not_recommended_scope() -> None:
    review = PaperResearchMap.from_mapping(
        {
            "document_id": "review-1",
            "doc_role": "review",
            "map_status": "sufficient",
            "review_synthesis": {
                "citation_leads": [
                    {
                        "content": "Smith et al. varied laser power and measured elongation.",
                        "material_scope": ["Ti-6Al-4V"],
                        "variables": ["laser power"],
                        "outcomes": ["elongation"],
                        "source_refs": [
                            {"source_kind": "block", "source_ref": "block-9"}
                        ],
                        "confidence": 0.9,
                    }
                ]
            },
        }
    )

    preview = screen_objective_scope(
        (review,),
        objective=_objective(seed_document_ids=()),
    )

    assert preview.recommended_document_ids == ()
    assert preview.review_document_ids == ("review-1",)
    assert preview.decisions[0].reason == "citation_lead_only"
    assert preview.support_is_evidence is False


def test_explicit_objective_exclusion_never_reenters_recommended_scope() -> None:
    objective = ResearchObjective.from_mapping(
        {
            **_objective(seed_document_ids=()).to_record(),
            "excluded_document_ids": ["paper-excluded"],
        }
    )

    preview = screen_objective_scope(
        (_experimental_map("paper-excluded"),),
        objective=objective,
    )

    assert preview.recommended_document_ids == ()
    assert preview.excluded_document_ids == ("paper-excluded",)
    assert preview.decisions[0].reason == "objective_explicit_exclusion"


async def test_service_loads_the_persisted_objective_and_every_collection_map() -> None:
    objective = _objective()
    paper_maps = (
        _experimental_map("paper-seed"),
        _experimental_map("paper-not-a-seed"),
    )
    collection_service = SimpleNamespace(
        get_collection=lambda collection_id: _async_value(
            {"collection_id": collection_id}
        )
    )
    objective_repository = SimpleNamespace(
        read_objective=lambda collection_id, objective_id: _async_value(objective)
    )
    paper_map_repository = SimpleNamespace(
        list_collection=lambda collection_id: _async_value(paper_maps)
    )
    service = ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=SimpleNamespace(),
        paper_map_repository=paper_map_repository,
        objective_repository=objective_repository,
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
        paper_map_service=SimpleNamespace(),
    )

    preview = await service.preview_objective_scope("col-1", "obj-1")

    assert preview.recommended_document_ids == (
        "paper-seed",
        "paper-not-a-seed",
    )


async def test_service_reports_scope_not_ready_without_collection_paper_maps() -> None:
    service = ResearchObjectiveService(
        collection_service=SimpleNamespace(
            get_collection=lambda collection_id: _async_value(
                {"collection_id": collection_id}
            )
        ),
        source_artifact_repository=SimpleNamespace(),
        paper_map_repository=SimpleNamespace(
            list_collection=lambda collection_id: _async_value(())
        ),
        objective_repository=SimpleNamespace(
            read_objective=lambda collection_id, objective_id: _async_value(
                _objective()
            )
        ),
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
        paper_map_service=SimpleNamespace(),
    )

    with pytest.raises(ObjectiveScopeNotReadyError):
        await service.preview_objective_scope("col-1", "obj-1")


async def _async_value(value):
    return value

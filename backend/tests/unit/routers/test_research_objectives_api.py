from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectivesNotReadyError,
)
from controllers.core import research_objectives as objective_controller
from controllers.schemas.core.research_objectives import ObjectiveEvidenceUnitResponse
from domain.core import ResearchObjective


def _objective_list_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "state": "partial",
        "readiness": {
            "objectives_ready": True,
            "frames_ready": True,
            "routes_ready": False,
            "evidence_units_ready": False,
            "logic_chain_ready": False,
        },
        "objectives": [
            {
                "objective_id": "obj-1",
                "question": "How does heat treatment affect corrosion resistance of LPBF 316L?",
                "material_scope": ["316L stainless steel"],
                "process_axes": ["heat treatment"],
                "property_axes": ["corrosion resistance"],
                "comparison_intent": "Compare as-built and heat-treated samples.",
                "confidence": 0.87,
                "status": "confirmed",
                "analysis_error": None,
                "analysis_progress": None,
                "state": "partial",
                "review_summary": {
                    "primary_finding_count": 0,
                    "review_candidate_count": 0,
                },
                "paper_frame_count": 2,
                "evidence_route_count": 0,
                "evidence_unit_count": 0,
                "logic_chain_count": 0,
            }
        ],
        "warnings": [],
    }


def _objective_detail_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "state": "partial",
        "objective": _objective_list_payload(collection_id)["objectives"][0],
        "review_summary": {
            "primary_finding_count": 0,
            "review_candidate_count": 0,
        },
        "objective_context": {
            "objective_id": "obj-1",
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["corrosion resistance"],
            "excluded_property_axes": [],
            "routing_hints": [],
            "extraction_guidance": {},
            "confidence": 0.87,
        },
        "readiness": {
            "objectives_ready": True,
            "frames_ready": True,
            "routes_ready": False,
            "evidence_units_ready": False,
            "logic_chain_ready": False,
        },
        "paper_frames": [
            {
                "frame_id": "opf-1",
                "objective_id": "obj-1",
                "document_id": "paper-1",
                "title": "LPBF 316L Corrosion",
                "source_filename": "paper-1.pdf",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "background": "Directly studies the objective.",
                "material_match": ["316L stainless steel"],
                "changed_variables": ["heat treatment"],
                "measured_property_scope": ["corrosion resistance"],
                "test_environment_scope": ["NaCl"],
                "relevant_sections": ["Results"],
                "relevant_tables": ["table-1"],
                "excluded_tables": [],
            }
        ],
        "evidence_routes": [],
        "evidence_units": [],
        "logic_chain": None,
        "existing_comparison_rows": [],
        "warnings": [],
    }


class FakeObjectiveService:
    def list_objective_workspaces(self, collection_id: str) -> dict:
        return _objective_list_payload(collection_id)

    def get_objective_research_view(
        self,
        collection_id: str,
        objective_id: str,  # noqa: ARG002
    ) -> dict:
        return _objective_detail_payload(collection_id)


class FakeObjectiveAnalysisService:
    def __init__(self) -> None:
        self.objective = ResearchObjective.from_mapping(
            {
                "objective_id": "obj-1",
                "question": "How does heat treatment affect corrosion resistance?",
                "status": "confirmed",
                "source_build_id": "build-1",
            }
        )

    def confirm_objective(self, collection_id: str, objective_id: str) -> dict:
        return self._payload(collection_id)

    def queue_analysis(self, collection_id: str, objective_id: str) -> dict:
        self.objective = ResearchObjective.from_mapping(
            {**self.objective.to_workspace_record(), "status": "queued"}
        )
        return self._payload(collection_id)

    def get_analysis(self, collection_id: str, objective_id: str) -> dict:
        return self._payload(collection_id)

    def run_analysis(self, collection_id: str, objective_id: str) -> dict:
        return self._payload(collection_id)

    def _payload(self, collection_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "objective": self.objective,
            "understanding": None,
            "warnings": [],
        }


class FakeFuture:
    def add_done_callback(self, callback):
        self.callback = callback


class FakeExecutor:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, func, *args):
        self.submissions.append((func.__name__, args))
        return FakeFuture()


class NotReadyObjectiveService:
    def list_objective_workspaces(self, collection_id: str) -> dict:
        raise ResearchObjectivesNotReadyError(collection_id)

    def get_objective_research_view(
        self,
        collection_id: str,
        objective_id: str,  # noqa: ARG002
    ) -> dict:
        raise ResearchObjectivesNotReadyError(collection_id)


class MissingObjectiveService(FakeObjectiveService):
    def get_objective_research_view(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)


def test_objective_routes_return_contract_payload():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                research_objective_service=FakeObjectiveService(),
                objective_analysis_service=FakeObjectiveAnalysisService(),
            )
        )
    )

    objectives = asyncio.run(
        objective_controller.list_collection_objectives("col-1", request)
    )
    detail = asyncio.run(
        objective_controller.get_collection_objective_research_view(
            "col-1",
            "obj-1",
            request,
        )
    )

    assert objectives.collection_id == "col-1"
    assert objectives.objectives[0].objective_id == "obj-1"
    assert detail.objective.objective_id == "obj-1"
    assert detail.paper_frames[0].document_id == "paper-1"
    assert detail.evidence_units == []
    assert detail.logic_chain is None
    assert objectives.objectives[0].status == "confirmed"
    assert detail.review_summary.primary_finding_count == 0


def test_objective_evidence_response_exposes_unified_selection_metadata():
    response = ObjectiveEvidenceUnitResponse(
        evidence_unit_id="oeu-1",
        objective_id="obj-1",
        document_id="paper-1",
        unit_kind="measurement",
        source_kind="table",
        source_ref="table-1",
        evidence_role="current_experimental_evidence",
        selection_reason="Target result table.",
        selection_status="extracted",
        resolution_status="resolved",
    )

    assert response.model_dump()["source_ref"] == "table-1"
    assert response.model_dump()["selection_status"] == "extracted"


def test_objective_confirm_and_analysis_routes_use_one_identity(monkeypatch):
    analysis_service = FakeObjectiveAnalysisService()
    executor = FakeExecutor()
    monkeypatch.setattr(objective_controller, "_objective_analysis_executor", executor)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(objective_analysis_service=analysis_service)
        )
    )

    confirmed = asyncio.run(
        objective_controller.confirm_collection_objective("col-1", "obj-1", request)
    )
    queued = objective_controller.run_collection_objective_analysis(
        "col-1", "obj-1", request
    )
    polled = asyncio.run(
        objective_controller.get_collection_objective_analysis(
            "col-1", "obj-1", request
        )
    )

    assert confirmed.objective.objective_id == "obj-1"
    assert queued.objective.status == "queued"
    assert polled.objective.status == "queued"
    assert executor.submissions == [
        ("run_analysis", ("col-1", "obj-1")),
    ]


def test_candidate_cannot_start_analysis_before_confirmation():
    service = FakeObjectiveAnalysisService()
    service.objective = ResearchObjective.from_mapping(
        {**service.objective.to_workspace_record(), "status": "candidate"}
    )

    def reject_candidate(collection_id, objective_id):
        raise ValueError("invalid objective status transition: candidate -> queued")

    service.queue_analysis = reject_candidate
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(objective_analysis_service=service))
    )

    with pytest.raises(HTTPException) as exc_info:
        objective_controller.run_collection_objective_analysis(
            "col-1", "obj-1", request
        )
    assert exc_info.value.status_code == 409


def test_objective_routes_run_service_in_threadpool(monkeypatch):
    calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                research_objective_service=FakeObjectiveService(),
            )
        )
    )
    monkeypatch.setattr(
        objective_controller,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )

    asyncio.run(objective_controller.list_collection_objectives("col-1", request))
    asyncio.run(
        objective_controller.get_collection_objective_research_view(
            "col-1",
            "obj-1",
            request,
        )
    )

    assert calls == [
        ("list_objective_workspaces", ("col-1",), {}),
        ("get_objective_research_view", ("col-1", "obj-1"), {}),
    ]


def test_objective_route_returns_409_when_not_ready():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                research_objective_service=NotReadyObjectiveService(),
            )
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            objective_controller.list_collection_objectives("col-1", request)
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "research_objectives_not_ready"
    assert exc.detail["collection_id"] == "col-1"


def test_objective_detail_route_returns_404_for_missing_objective():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                research_objective_service=MissingObjectiveService(),
            )
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            objective_controller.get_collection_objective_research_view(
                "col-1",
                "obj-missing",
                request,
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "research_objective_not_found"
    assert exc.detail["objective_id"] == "obj-missing"

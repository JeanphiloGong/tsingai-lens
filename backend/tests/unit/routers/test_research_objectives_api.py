from __future__ import annotations

import asyncio

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
                "state": "partial",
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
        "objective_report": None,
        "existing_comparison_rows": [],
        "warnings": [],
    }


def _objective_report_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "report_id": "orp-1",
        "objective_id": "obj-1",
        "status": "generating",
        "stage": "requested",
        "message": "Objective report generation started.",
        "title": "How does heat treatment affect corrosion resistance of LPBF 316L?",
        "language": "zh",
        "model": "test-model",
        "data_version": "v1",
        "markdown": None,
        "warnings": [],
        "source_refs": [],
        "created_at": "2026-05-19T00:00:00+00:00",
        "updated_at": "2026-05-19T00:00:00+00:00",
        "generated_at": None,
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

    def request_objective_report(
        self,
        collection_id: str,
        objective_id: str,  # noqa: ARG002
        *,
        language: str = "zh",  # noqa: ARG002
        force_regenerate: bool = False,  # noqa: ARG002
    ) -> dict:
        return _objective_report_payload(collection_id)

    def get_objective_report_status(
        self,
        collection_id: str,
        objective_id: str,  # noqa: ARG002
    ) -> dict:
        return {
            **_objective_report_payload(collection_id),
            "status": "ready",
            "stage": "ready",
            "markdown": "# 研究目标\n\n报告正文。",
            "generated_at": "2026-05-19T00:00:01+00:00",
        }

    def generate_objective_report(
        self,
        collection_id: str,  # noqa: ARG002
        objective_id: str,  # noqa: ARG002
        *,
        language: str = "zh",  # noqa: ARG002
        force_regenerate: bool = False,  # noqa: ARG002
    ) -> dict:
        return self.get_objective_report_status(collection_id, objective_id)


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

    def request_objective_report(
        self,
        collection_id: str,
        objective_id: str,
        *,
        language: str = "zh",  # noqa: ARG002
        force_regenerate: bool = False,  # noqa: ARG002
    ) -> dict:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)


def test_objective_routes_return_contract_payload(monkeypatch):
    monkeypatch.setattr(
        objective_controller,
        "research_objective_service",
        FakeObjectiveService(),
    )

    objectives = asyncio.run(objective_controller.list_collection_objectives("col-1"))
    detail = asyncio.run(
        objective_controller.get_collection_objective_research_view("col-1", "obj-1")
    )

    assert objectives.collection_id == "col-1"
    assert objectives.objectives[0].objective_id == "obj-1"
    assert detail.objective.objective_id == "obj-1"
    assert detail.paper_frames[0].document_id == "paper-1"
    assert detail.evidence_units == []
    assert detail.logic_chain is None


def test_objective_routes_run_service_in_threadpool(monkeypatch):
    calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(
        objective_controller,
        "research_objective_service",
        FakeObjectiveService(),
    )
    monkeypatch.setattr(
        objective_controller,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )

    asyncio.run(objective_controller.list_collection_objectives("col-1"))
    asyncio.run(
        objective_controller.get_collection_objective_research_view("col-1", "obj-1")
    )

    assert calls == [
        ("list_objective_workspaces", ("col-1",), {}),
        ("get_objective_research_view", ("col-1", "obj-1"), {}),
    ]


def test_objective_report_routes_request_and_read_report(monkeypatch):
    background_tasks = []

    class FakeBackgroundTasks:
        def add_task(self, func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            background_tasks.append((func, args, kwargs))

    monkeypatch.setattr(
        objective_controller,
        "research_objective_service",
        FakeObjectiveService(),
    )
    request = objective_controller.ObjectiveReportRequest(language="zh")

    created = asyncio.run(
        objective_controller.create_collection_objective_report(
            "col-1",
            "obj-1",
            request,
            FakeBackgroundTasks(),
        )
    )
    fetched = asyncio.run(
        objective_controller.get_collection_objective_report("col-1", "obj-1")
    )

    assert created.status == "generating"
    assert created.markdown is None
    assert fetched.status == "ready"
    assert fetched.markdown == "# 研究目标\n\n报告正文。"
    assert len(background_tasks) == 1
    assert background_tasks[0][1] == ("col-1", "obj-1", request)


def test_objective_route_returns_409_when_not_ready(monkeypatch):
    monkeypatch.setattr(
        objective_controller,
        "research_objective_service",
        NotReadyObjectiveService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(objective_controller.list_collection_objectives("col-1"))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "research_objectives_not_ready"
    assert exc.detail["collection_id"] == "col-1"


def test_objective_detail_route_returns_404_for_missing_objective(monkeypatch):
    monkeypatch.setattr(
        objective_controller,
        "research_objective_service",
        MissingObjectiveService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            objective_controller.get_collection_objective_research_view(
                "col-1",
                "obj-missing",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "research_objective_not_found"
    assert exc.detail["objective_id"] == "obj-missing"

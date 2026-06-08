from __future__ import annotations

import asyncio

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.core.research_view_aggregation_service import (
    MaterialReportNotFoundError,
    ResearchViewDocumentNotFoundError,
    ResearchViewMaterialNotFoundError,
    ResearchViewNotReadyError,
)
from controllers.core import research_view as research_view_controller


def _collection_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "state": "empty",
        "overview": {
            "collection_id": collection_id,
            "document_count": 0,
            "sample_variant_count": 0,
            "measurement_count": 0,
            "condition_count": 0,
            "evidence_count": 0,
            "comparable_group_count": 0,
            "material_systems": [],
            "process_variables": [],
            "measured_properties": [],
            "condition_families": [],
        },
        "materials": [],
        "paper_coverage": [],
        "comparable_groups": [],
        "cross_paper_matrices": [],
        "trend_series": [],
        "evidence_links": {},
        "debug_links": {},
        "warnings": [],
    }


def _paper_payload(collection_id: str = "col-1", document_id: str = "paper-1") -> dict:
    return {
        "collection_id": collection_id,
        "document_id": document_id,
        "paper_title": "Paper",
        "state": "empty",
        "overview": {
            "document_id": document_id,
            "material_systems": [],
            "sample_variant_count": 0,
            "main_process_variables": [],
            "measured_properties": [],
            "condition_families": [],
            "warning_count": 0,
        },
        "materials": [],
        "sample_matrix": {
            "matrix_id": f"sample-matrix:{document_id}",
            "document_id": document_id,
            "state": "empty",
            "columns": [],
            "rows": [],
            "warnings": [],
        },
        "condition_series": [],
        "evidence_links": {},
        "debug_links": {},
        "warnings": [],
    }


def _materials_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "state": "ready",
        "materials": [
            {
                "material_id": "mat-316l-stainless-steel",
                "canonical_name": "316L stainless steel",
                "aliases": ["316L"],
                "paper_count": 1,
                "sample_count": 2,
                "process_families": ["LPBF"],
                "measured_properties": ["density"],
                "comparison_count": 1,
                "evidence_coverage": {
                    "observed_count": 1,
                    "with_evidence_count": 1,
                    "coverage": 1.0,
                },
                "state": "ready",
                "links": {},
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def _material_profile_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "material_id": "mat-316l-stainless-steel",
        "canonical_name": "316L stainless steel",
        "aliases": ["316L"],
        "state": "ready",
        "overview": {},
        "papers": [],
        "sample_matrix": {
            "matrix_id": "material-sample-matrix:mat-316l-stainless-steel",
            "document_id": None,
            "state": "empty",
            "columns": [],
            "rows": [],
            "warnings": [],
        },
        "process_parameter_ranges": [],
        "measured_properties": [],
        "comparison_groups": [],
        "condition_series": [],
        "evidence_refs": [],
        "debug_links": {},
        "warnings": [],
    }


def _paper_materials_payload(
    collection_id: str = "col-1",
    document_id: str = "paper-1",
) -> dict:
    return {
        "collection_id": collection_id,
        "document_id": document_id,
        "state": "ready",
        "materials": [
            {
                "material_id": "mat-316l-stainless-steel",
                "canonical_name": "316L stainless steel",
                "aliases": ["316L"],
                "sample_count": 1,
                "process_families": ["LPBF"],
                "measured_properties": ["density"],
                "comparison_count": 0,
                "evidence_coverage": {
                    "observed_count": 1,
                    "with_evidence_count": 1,
                    "coverage": 1.0,
                },
                "links": {},
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def _document_material_profile_payload(
    collection_id: str = "col-1",
    document_id: str = "paper-1",
) -> dict:
    return {
        "collection_id": collection_id,
        "document_id": document_id,
        "material_id": "mat-316l-stainless-steel",
        "canonical_name": "316L stainless steel",
        "aliases": ["316L"],
        "state": "ready",
        "overview": {},
        "sample_matrix": {
            "matrix_id": f"sample-matrix:{document_id}",
            "document_id": document_id,
            "state": "empty",
            "columns": [],
            "rows": [],
            "warnings": [],
        },
        "process_conditions": [],
        "test_conditions": [],
        "measured_properties": [],
        "within_paper_comparisons": [],
        "condition_series": [],
        "evidence_refs": [],
        "debug_links": {},
        "warnings": [],
    }


def _material_report_payload(collection_id: str = "col-1") -> dict:
    return {
        "collection_id": collection_id,
        "report_id": "mr-1",
        "material_id": "mat-316l-stainless-steel",
        "status": "generating",
        "stage": "requested",
        "message": "Material report generation started.",
        "title": "316L stainless steel 材料报告",
        "language": "zh",
        "model": "test-model",
        "data_version": "v1",
        "markdown": None,
        "warnings": [],
        "source_refs": [],
        "evidence_appendix": {},
        "created_at": "2026-05-19T00:00:00+00:00",
        "updated_at": "2026-05-19T00:00:00+00:00",
        "generated_at": None,
    }


class FakeResearchViewService:
    def get_collection_research_view(self, collection_id: str) -> dict:
        return _collection_payload(collection_id)

    def list_collection_materials(self, collection_id: str) -> dict:
        return _materials_payload(collection_id)

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        return _material_profile_payload(collection_id)

    def request_material_report(
        self,
        collection_id: str,
        material_id: str,  # noqa: ARG002
        *,
        language: str = "zh",  # noqa: ARG002
        force_regenerate: bool = False,  # noqa: ARG002
    ) -> dict:
        return _material_report_payload(collection_id)

    def get_material_report_status(
        self,
        collection_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        return {
            **_material_report_payload(collection_id),
            "status": "ready",
            "stage": "ready",
            "message": "Material report generated.",
            "markdown": "# 316L stainless steel 材料报告\n\n结论。",
            "generated_at": "2026-05-19T00:00:01+00:00",
        }

    def generate_material_report(
        self,
        collection_id: str,
        material_id: str,
        *,
        language: str = "zh",  # noqa: ARG002
        force_regenerate: bool = False,  # noqa: ARG002
    ) -> dict:
        return self.get_material_report_status(collection_id, material_id)

    def get_document_research_view(self, collection_id: str, document_id: str) -> dict:
        return _paper_payload(collection_id, document_id)

    def list_document_materials(self, collection_id: str, document_id: str) -> dict:
        return _paper_materials_payload(collection_id, document_id)

    def get_document_material_research_view(
        self,
        collection_id: str,
        document_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        return _document_material_profile_payload(collection_id, document_id)


class NotReadyResearchViewService:
    def get_collection_research_view(self, collection_id: str) -> dict:
        raise ResearchViewNotReadyError(collection_id)

    def list_collection_materials(self, collection_id: str) -> dict:
        raise ResearchViewNotReadyError(collection_id)

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        raise ResearchViewNotReadyError(collection_id)

    def get_document_research_view(self, collection_id: str, document_id: str) -> dict:  # noqa: ARG002
        raise ResearchViewNotReadyError(collection_id)

    def list_document_materials(self, collection_id: str, document_id: str) -> dict:  # noqa: ARG002
        raise ResearchViewNotReadyError(collection_id)

    def get_document_material_research_view(
        self,
        collection_id: str,
        document_id: str,  # noqa: ARG002
        material_id: str,  # noqa: ARG002
    ) -> dict:
        raise ResearchViewNotReadyError(collection_id)


class MissingDocumentResearchViewService:
    def get_collection_research_view(self, collection_id: str) -> dict:
        return _collection_payload(collection_id)

    def list_collection_materials(self, collection_id: str) -> dict:
        return _materials_payload(collection_id)

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        return _material_profile_payload(collection_id)

    def get_document_research_view(self, collection_id: str, document_id: str) -> dict:
        raise ResearchViewDocumentNotFoundError(collection_id, document_id)

    def list_document_materials(self, collection_id: str, document_id: str) -> dict:
        raise ResearchViewDocumentNotFoundError(collection_id, document_id)

    def get_document_material_research_view(
        self,
        collection_id: str,
        document_id: str,
        material_id: str,  # noqa: ARG002
    ) -> dict:
        raise ResearchViewDocumentNotFoundError(collection_id, document_id)


class MissingMaterialResearchViewService(FakeResearchViewService):
    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict:
        raise ResearchViewMaterialNotFoundError(collection_id, material_id)

    def get_document_material_research_view(
        self,
        collection_id: str,
        document_id: str,
        material_id: str,
    ) -> dict:
        raise ResearchViewMaterialNotFoundError(collection_id, material_id, document_id)


class MissingMaterialReportService(FakeResearchViewService):
    def get_material_report_status(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict:
        raise MaterialReportNotFoundError(collection_id, material_id)


def test_collection_research_view_route_returns_contract_payload(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )

    payload = asyncio.run(
        research_view_controller.get_collection_research_view("col-1")
    )

    assert payload.collection_id == "col-1"
    assert payload.state == "empty"
    assert payload.overview.collection_id == "col-1"


def test_collection_material_routes_return_contract_payload(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )

    materials = asyncio.run(
        research_view_controller.list_collection_materials("col-1")
    )
    profile = asyncio.run(
        research_view_controller.get_collection_material_research_view(
            "col-1",
            "mat-316l-stainless-steel",
        )
    )

    assert materials.collection_id == "col-1"
    assert materials.materials[0].material_id == "mat-316l-stainless-steel"
    assert profile.material_id == "mat-316l-stainless-steel"


def test_material_report_routes_request_and_read_report(monkeypatch):
    background_tasks = []

    class FakeBackgroundTasks:
        def add_task(self, func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            background_tasks.append((func, args, kwargs))

    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )
    request = research_view_controller.MaterialReportRequest(language="zh")

    created = asyncio.run(
        research_view_controller.create_collection_material_report(
            "col-1",
            "mat-316l-stainless-steel",
            request,
            FakeBackgroundTasks(),
        )
    )
    fetched = asyncio.run(
        research_view_controller.get_collection_material_report(
            "col-1",
            "mat-316l-stainless-steel",
        )
    )

    assert created.status == "generating"
    assert created.markdown is None
    assert fetched.status == "ready"
    assert fetched.markdown == "# 316L stainless steel 材料报告\n\n结论。"
    assert len(background_tasks) == 1
    assert background_tasks[0][1] == (
        "col-1",
        "mat-316l-stainless-steel",
        request,
    )


def test_material_report_route_returns_404_when_not_requested(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        MissingMaterialReportService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            research_view_controller.get_collection_material_report(
                "col-1",
                "mat-316l-stainless-steel",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "material_report_not_found"
    assert exc.detail["material_id"] == "mat-316l-stainless-steel"


def test_collection_material_routes_run_service_in_threadpool(monkeypatch):
    calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )
    monkeypatch.setattr(
        research_view_controller,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )

    asyncio.run(research_view_controller.list_collection_materials("col-1"))
    asyncio.run(
        research_view_controller.get_collection_material_research_view(
            "col-1",
            "mat-316l-stainless-steel",
        )
    )

    assert calls == [
        ("list_collection_materials", ("col-1",), {}),
        (
            "get_collection_material_research_view",
            ("col-1", "mat-316l-stainless-steel"),
            {},
        ),
    ]


def test_document_research_view_route_returns_contract_payload(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )

    payload = asyncio.run(
        research_view_controller.get_collection_document_research_view(
            "col-1",
            "paper-1",
        )
    )

    assert payload.collection_id == "col-1"
    assert payload.document_id == "paper-1"
    assert payload.sample_matrix.matrix_id == "sample-matrix:paper-1"


def test_document_material_routes_return_contract_payload(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        FakeResearchViewService(),
    )

    materials = asyncio.run(
        research_view_controller.list_collection_document_materials(
            "col-1",
            "paper-1",
        )
    )
    profile = asyncio.run(
        research_view_controller.get_collection_document_material_research_view(
            "col-1",
            "paper-1",
            "mat-316l-stainless-steel",
        )
    )

    assert materials.document_id == "paper-1"
    assert materials.materials[0].sample_count == 1
    assert profile.document_id == "paper-1"
    assert profile.material_id == "mat-316l-stainless-steel"


def test_collection_research_view_route_returns_409_when_not_ready(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        NotReadyResearchViewService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(research_view_controller.get_collection_research_view("col-1"))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "research_view_not_ready"
    assert exc.detail["collection_id"] == "col-1"


def test_collection_material_route_returns_404_for_missing_material(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        MissingMaterialResearchViewService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            research_view_controller.get_collection_material_research_view(
                "col-1",
                "mat-missing",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "research_view_material_not_found"
    assert exc.detail["material_id"] == "mat-missing"


def test_document_research_view_route_returns_404_for_missing_document(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        MissingDocumentResearchViewService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            research_view_controller.get_collection_document_research_view(
                "col-1",
                "paper-missing",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "research_view_document_not_found"
    assert exc.detail["document_id"] == "paper-missing"


def test_document_material_route_returns_404_for_missing_material(monkeypatch):
    monkeypatch.setattr(
        research_view_controller,
        "research_view_service",
        MissingMaterialResearchViewService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            research_view_controller.get_collection_document_material_research_view(
                "col-1",
                "paper-1",
                "mat-missing",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "research_view_material_not_found"
    assert exc.detail["document_id"] == "paper-1"

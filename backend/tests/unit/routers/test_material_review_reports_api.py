from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, HTTPException

from application.derived.material_review_report_service import (
    MaterialReviewReportNotFoundError,
    MaterialReviewReportNotReadyError,
)
from controllers.derived import material_review_reports as controller
from controllers.schemas.derived.material_review_report import (
    MaterialReviewReportRequest,
)


def _report_payload(status: str = "ready") -> dict[str, Any]:
    return {
        "report_id": "mrp_123",
        "collection_id": "col-1",
        "material_id": "mat-316l",
        "status": status,
        "stage": status,
        "message": "Review draft generated.",
        "title": "316L review",
        "language": "zh",
        "report_type": "review_draft",
        "include_appendix": True,
        "readiness": "preliminary",
        "readiness_reason": "Limited coverage.",
        "data_version": "material_profile:test",
        "warnings": [],
        "created_at": "2026-05-05T15:32:00+00:00",
        "updated_at": "2026-05-05T15:32:00+00:00",
        "generated_at": "2026-05-05T15:32:00+00:00" if status == "ready" else None,
        "pdf_url": "/api/v1/collections/col-1/materials/mat-316l/review-report.pdf"
        if status == "ready"
        else None,
        "markdown_url": "/api/v1/collections/col-1/materials/mat-316l/review-report.md"
        if status == "ready"
        else None,
    }


class _FakeMaterialReviewReportService:
    def __init__(self, pdf_path: Path | None = None) -> None:
        self.pdf_path = pdf_path
        self.request_calls: list[tuple[str, str, dict[str, Any]]] = []

    def request_review_report(
        self,
        collection_id: str,
        material_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.request_calls.append((collection_id, material_id, kwargs))
        return _report_payload("generating")

    def generate_review_report(
        self,
        collection_id: str,
        material_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _report_payload("ready")

    def get_review_report_status(self, collection_id: str, material_id: str) -> dict[str, Any]:
        return _report_payload("ready")

    def get_review_markdown(self, collection_id: str, material_id: str) -> str:
        return "# 316L review\n\nEvidence-backed draft [E01]."

    def get_review_pdf_path(self, collection_id: str, material_id: str) -> Path:
        assert self.pdf_path is not None
        return self.pdf_path


class _MissingReportService(_FakeMaterialReviewReportService):
    def get_review_report_status(self, collection_id: str, material_id: str) -> dict[str, Any]:
        raise MaterialReviewReportNotFoundError(collection_id, material_id)


class _NotReadyReportService(_FakeMaterialReviewReportService):
    def get_review_markdown(self, collection_id: str, material_id: str) -> str:
        raise MaterialReviewReportNotReadyError(collection_id, material_id, "generating")


def test_create_material_review_report_returns_generating_and_schedules_task(monkeypatch):
    fake = _FakeMaterialReviewReportService()
    monkeypatch.setattr(controller, "material_review_report_service", fake)
    request = MaterialReviewReportRequest(force_regenerate=True)
    background_tasks = BackgroundTasks()

    response = asyncio.run(
        controller.create_material_review_report(
            "col-1",
            "mat-316l",
            request,
            background_tasks,
        )
    )

    assert response.status == "generating"
    assert fake.request_calls[0][2]["force_regenerate"] is True
    assert len(background_tasks.tasks) == 1


def test_material_review_report_status_returns_payload(monkeypatch):
    monkeypatch.setattr(
        controller,
        "material_review_report_service",
        _FakeMaterialReviewReportService(),
    )

    response = asyncio.run(
        controller.get_material_review_report("col-1", "mat-316l")
    )

    assert response.report_id == "mrp_123"
    assert response.pdf_url.endswith("/review-report.pdf")


def test_material_review_report_markdown_returns_text(monkeypatch):
    monkeypatch.setattr(
        controller,
        "material_review_report_service",
        _FakeMaterialReviewReportService(),
    )

    response = asyncio.run(
        controller.get_material_review_report_markdown("col-1", "mat-316l")
    )

    assert response.media_type == "text/markdown; charset=utf-8"
    assert b"Evidence-backed draft" in response.body


def test_material_review_report_pdf_returns_file_response(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "review.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr(
        controller,
        "material_review_report_service",
        _FakeMaterialReviewReportService(pdf_path),
    )

    response = asyncio.run(
        controller.get_material_review_report_pdf("col-1", "mat-316l")
    )

    assert Path(response.path) == pdf_path
    assert response.media_type == "application/pdf"


def test_material_review_report_status_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(
        controller,
        "material_review_report_service",
        _MissingReportService(),
    )

    try:
        asyncio.run(controller.get_material_review_report("col-1", "mat-316l"))
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail["code"] == "material_review_report_not_found"
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_material_review_report_markdown_returns_409_when_not_ready(monkeypatch):
    monkeypatch.setattr(
        controller,
        "material_review_report_service",
        _NotReadyReportService(),
    )

    try:
        asyncio.run(
            controller.get_material_review_report_markdown("col-1", "mat-316l")
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "material_review_report_not_ready"
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")

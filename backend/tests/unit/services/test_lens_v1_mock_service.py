from __future__ import annotations

from application.mock.lens_v1_service import lens_v1_mock_service


def test_mock_service_exposes_expected_collections(monkeypatch):
    monkeypatch.setenv("LENS_ENABLE_MOCK_API", "1")

    items = lens_v1_mock_service.list_collections()
    ids = {item["collection_id"] for item in items}

    assert lens_v1_mock_service.is_enabled() is True
    assert {"col_mock_empty", "col_mock_processing", "col_mock_ready", "col_mock_limited"} <= ids


def test_mock_service_returns_ready_workspace_and_backbone_resources(monkeypatch):
    monkeypatch.setenv("LENS_ENABLE_MOCK_API", "1")

    workspace = lens_v1_mock_service.get_workspace("col_mock_ready")
    assert workspace["workflow"]["documents"]["status"] == "ready"
    assert workspace["workflow"]["comparisons"]["status"] == "ready"
    assert workspace["links"]["comparisons"] == "/api/v1/collections/col_mock_ready/comparisons"

    profiles = lens_v1_mock_service.list_document_profiles("col_mock_ready")
    assert profiles["total"] == 3
    assert profiles["items"][0]["title"] == "High-Rate Performance of Layered Oxide Cathodes"
    assert profiles["items"][0]["source_filename"] == "ready-paper-1.pdf"
    assert profiles["summary"]["by_doc_type"]["experimental"] == 2

    evidence = lens_v1_mock_service.list_evidence_cards("col_mock_ready")
    assert evidence["total"] == 3
    assert evidence["items"][0]["traceability_status"] == "direct"

    comparisons = lens_v1_mock_service.list_comparisons("col_mock_ready")
    assert comparisons["total"] == 2
    assert comparisons["items"][0]["comparability_status"] == "comparable"


def test_mock_service_returns_limited_collection_signals(monkeypatch):
    monkeypatch.setenv("LENS_ENABLE_MOCK_API", "1")

    workspace = lens_v1_mock_service.get_workspace("col_mock_limited")
    warning_codes = {item["code"] for item in workspace["warnings"]}
    assert workspace["workflow"]["protocol"]["status"] == "not_applicable"
    assert workspace["workflow"]["comparisons"]["status"] == "limited"
    assert {"review_heavy", "comparison_limited"} <= warning_codes

    task = lens_v1_mock_service.get_task("task_mock_limited_index")
    assert task["status"] == "partial_success"

    artifacts = lens_v1_mock_service.get_task_artifacts("task_mock_limited_index")
    assert artifacts["protocol_steps_ready"] is False

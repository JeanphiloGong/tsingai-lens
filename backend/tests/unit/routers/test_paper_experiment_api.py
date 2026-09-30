from __future__ import annotations

from main import create_app


def test_experiment_projection_routes_are_additive() -> None:
    app = create_app()
    routes = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }

    assert ("GET", "/api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-analysis") in routes
    assert (
        "GET",
        "/api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-analysis/export",
    ) in routes
    assert (
        "POST",
        "/api/v1/collections/{collection_id}/objectives/{objective_id}/analysis",
    ) in routes
    assert (
        "GET",
        "/api/v1/collections/{collection_id}/objectives/{objective_id}/findings",
    ) in routes


def test_feedback_product_routes_use_task_datasets_without_legacy_snapshot_readback() -> None:
    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/v1/feedback-datasets" in paths
    assert not any("/api/v1/dataset-snapshots" in path for path in paths)


def test_existing_analysis_request_contract_has_no_experiment_fields() -> None:
    app = create_app()
    operation = app.openapi()["paths"][
        "/api/v1/collections/{collection_id}/objectives/{objective_id}/analysis"
    ]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert request_schema["$ref"].endswith("/DocumentSelectionRequest")
    assert {
        (item["in"], item["name"])
        for item in operation["parameters"]
    } == {
        ("path", "collection_id"),
        ("path", "objective_id"),
    }
    document_selection_schema = app.openapi()["components"]["schemas"][
        "DocumentSelectionRequest"
    ]
    assert set(document_selection_schema["properties"]) == {"document_ids"}
    assert document_selection_schema["required"] == ["document_ids"]
    assert document_selection_schema["additionalProperties"] is False

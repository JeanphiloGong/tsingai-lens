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

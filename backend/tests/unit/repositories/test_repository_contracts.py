from __future__ import annotations

import ast
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("directory", ["domain", "application/repositories"])
def test_domain_and_repository_contracts_do_not_import_storage_or_http(directory):
    forbidden = {"sqlalchemy", "pydantic", "fastapi", "infra", "controllers"}
    if directory == "domain":
        forbidden.add("application")
    violations = []
    for path in (BACKEND / directory).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".", 1)[0] in forbidden:
                    violations.append(f"{path.relative_to(BACKEND)}:{node.lineno}: {module}")
    assert violations == []


def test_retired_central_repository_ports_are_not_forwarded():
    assert not (BACKEND / "domain/ports.py").exists()
    assert not (BACKEND / "domain/source/ports.py").exists()


def test_objective_query_result_reuses_the_domain_model():
    from typing import get_type_hints

    from application.repositories.objective_repository import ObjectiveRepository, StoredObjective
    from domain.core import ResearchObjective

    assert get_type_hints(StoredObjective)["objective"] is ResearchObjective
    assert StoredObjective.__module__ == ObjectiveRepository.__module__
    assert set(get_type_hints(StoredObjective)) == {"objective", "created_at", "updated_at"}

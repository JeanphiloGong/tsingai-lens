from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("directory", ["domain", "repositories"])
def test_domain_and_repositories_respect_their_dependencies(directory):
    forbidden = {"pydantic", "fastapi", "controllers", "application", "tests"}
    if directory == "domain":
        forbidden.update({"sqlalchemy", "infra", "repositories"})
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
    assert not list((BACKEND / "application/repositories").glob("*.py"))
    assert not list((BACKEND / "infra/persistence/memory").glob("*.py"))
    assert not list((BACKEND / "infra/persistence/postgres").glob("*_repository.py"))


def test_objective_query_result_reuses_the_domain_model():
    from typing import get_type_hints

    from domain.core import ResearchObjective
    from repositories.objective_repository import ObjectiveRepository, StoredObjective

    assert get_type_hints(StoredObjective)["objective"] is ResearchObjective
    assert StoredObjective.__module__ == ObjectiveRepository.__module__
    assert set(get_type_hints(StoredObjective)) == {"objective", "created_at", "updated_at"}

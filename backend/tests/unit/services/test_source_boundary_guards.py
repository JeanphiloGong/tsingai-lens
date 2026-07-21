from __future__ import annotations

import ast
from pathlib import Path


def _imports_infra_graphrag(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "infra.graphrag" or alias.name.startswith(
                    "infra.graphrag."
                ):
                    return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "infra.graphrag" or module.startswith("infra.graphrag."):
                return True
    return False


def _references_retired_core_persistence(path: Path) -> bool:
    retired_names = {
        "CoreFactRepository",
        "SqliteCoreFactRepository",
        "build_core_fact_repository",
        "core_fact_repository",
    }
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in retired_names:
            return True
        if isinstance(node, ast.Attribute) and node.attr in retired_names:
            return True
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in retired_names:
                return True
        if isinstance(node, ast.arg) and node.arg in retired_names:
            return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "infra.persistence.sqlite.core_fact_repository":
                return True
            if any(
                alias.name in retired_names or alias.asname in retired_names
                for alias in node.names
            ):
                return True
        if isinstance(node, ast.Import):
            if any(
                alias.name == "infra.persistence.sqlite.core_fact_repository"
                or alias.asname in retired_names
                for alias in node.names
            ):
                return True
    return False


def test_product_facing_modules_do_not_import_graphrag_outside_source_runtime():
    backend_root = Path(__file__).resolve().parents[3]
    scan_roots = [
        backend_root / "application",
        backend_root / "controllers",
    ]
    allowed_prefixes = {
        backend_root / "application" / "source",
    }

    violations: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*.py"):
            if any(path.is_relative_to(prefix) for prefix in allowed_prefixes):
                continue
            if _imports_infra_graphrag(path):
                violations.append(str(path.relative_to(backend_root)))

    assert violations == []


def test_maintained_runtime_does_not_reference_retired_core_persistence():
    backend_root = Path(__file__).resolve().parents[3]
    scan_roots = [
        backend_root / "application",
        backend_root / "controllers",
        backend_root / "domain",
        backend_root / "infra",
        backend_root / "scripts",
    ]
    paths = [backend_root / "main.py"]
    for root in scan_roots:
        paths.extend(root.rglob("*.py"))

    violations = [
        str(path.relative_to(backend_root))
        for path in paths
        if _references_retired_core_persistence(path)
    ]

    assert violations == []

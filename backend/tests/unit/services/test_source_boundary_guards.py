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

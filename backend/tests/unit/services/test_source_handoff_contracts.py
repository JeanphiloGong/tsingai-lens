from __future__ import annotations

import ast
from pathlib import Path


def _assignments_by_name(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


def _resolve_name_list(value: ast.AST, constants: dict[str, ast.AST]) -> list[str]:
    if not isinstance(value, ast.List):
        raise TypeError(f"expected list node, got {type(value).__name__}")

    items: list[str] = []
    for element in value.elts:
        if isinstance(element, ast.Constant):
            items.append(str(element.value))
            continue
        if isinstance(element, ast.Name):
            resolved = constants.get(element.id)
            if not isinstance(resolved, ast.Constant):
                raise TypeError(f"expected constant for {element.id}")
            items.append(str(resolved.value))
            continue
        raise TypeError(f"unsupported element type: {type(element).__name__}")
    return items


def test_text_unit_final_columns_only_expose_minimal_source_handoff():
    backend_root = Path(__file__).resolve().parents[3]
    schema_path = backend_root / "infra" / "source" / "contracts" / "artifact_schemas.py"
    assignments = _assignments_by_name(schema_path)

    columns = _resolve_name_list(assignments["TEXT_UNITS_FINAL_COLUMNS"], assignments)

    assert columns == [
        "id",
        "human_readable_id",
        "text",
        "n_tokens",
        "document_ids",
    ]


def test_pipeline_factory_defaults_to_minimal_source_handoff():
    backend_root = Path(__file__).resolve().parents[3]
    factory_path = (
        backend_root / "infra" / "source" / "runtime" / "workflows" / "factory.py"
    )
    source = factory_path.read_text(encoding="utf-8")
    assignments = _assignments_by_name(factory_path)

    workflows = ast.literal_eval(assignments["_source_handoff_workflows"])
    assert workflows == [
        "create_base_text_units",
        "create_final_documents",
        "create_final_text_units",
        "create_sections",
        "create_table_cells",
    ]
    assert 'IndexingMethod.Standard, ["load_input_documents", *_source_handoff_workflows]' in source
    assert 'IndexingMethod.Fast, ["load_input_documents", *_source_handoff_workflows]' in source


def test_create_final_text_units_no_longer_loads_legacy_graph_artifacts():
    backend_root = Path(__file__).resolve().parents[3]
    workflow_path = (
        backend_root
        / "infra"
        / "source"
        / "runtime"
        / "workflows"
        / "create_final_text_units.py"
    )
    source = workflow_path.read_text(encoding="utf-8")

    assert '"entities"' not in source
    assert '"relationships"' not in source
    assert '"covariates"' not in source
    assert "storage_has_table" not in source

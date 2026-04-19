from __future__ import annotations

import json
import sys
from hashlib import sha1
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from application.derived.graph_projection_service import load_core_graph_payload


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _semantic_node_id(prefix: str, label: str) -> str:
    return f"{prefix}:{sha1(label.encode('utf-8')).hexdigest()}"


def test_core_projection_builds_route_compatible_graph_payload(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": "col-1",
                "title": "Core Graph Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": ["methods_section_detected"],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": "col-1",
                "claim_text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-1",
                        "source_type": "text",
                        "section_id": None,
                        "block_id": None,
                        "snippet_id": "tu-1",
                        "figure_or_table": None,
                        "quote_span": "Flexural strength increased to 97 MPa.",
                    }
                ],
                "material_system": {"family": "epoxy composite", "composition": None},
                "condition_context": {
                    "process": {"temperatures_c": [80.0]},
                    "baseline": {"control": "untreated baseline"},
                    "test": {"method": "SEM"},
                },
                "confidence": 0.82,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": "col-1",
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "epoxy composite",
                "process_normalized": "80 C",
                "property_normalized": "flexural_strength",
                "baseline_normalized": "untreated baseline",
                "test_condition_normalized": "SEM",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": 97.0,
                "unit": "MPa",
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)

    nodes, edges, truncated = load_core_graph_payload(
        base_dir=output_dir,
        max_nodes=20,
        min_weight=0.0,
    )

    assert truncated is False
    assert len(nodes) == 7
    assert len(edges) == 6

    material_node_id = _semantic_node_id("mat", "epoxy composite")
    property_node_id = _semantic_node_id("prop", "flexural_strength")
    test_condition_node_id = _semantic_node_id("tc", "sem")
    baseline_node_id = _semantic_node_id("base", "untreated baseline")
    nodes_by_id = {node["id"]: node for node in nodes}
    assert set(nodes_by_id) == {
        "doc:paper-1",
        "evi:ev-1",
        "cmp:cmp-1",
        material_node_id,
        property_node_id,
        test_condition_node_id,
        baseline_node_id,
    }
    assert nodes_by_id["doc:paper-1"]["type"] == "document"
    assert nodes_by_id["evi:ev-1"]["type"] == "evidence"
    assert nodes_by_id["evi:ev-1"]["degree"] == 2
    assert nodes_by_id["cmp:cmp-1"]["type"] == "comparison"
    assert nodes_by_id["cmp:cmp-1"]["label"] == "epoxy composite | flexural_strength"
    assert nodes_by_id[material_node_id]["type"] == "material"
    assert nodes_by_id[property_node_id]["type"] == "property"
    assert nodes_by_id[test_condition_node_id]["type"] == "test_condition"
    assert nodes_by_id[baseline_node_id]["type"] == "baseline"

    edges_by_id = {edge["id"]: edge for edge in edges}
    assert set(edges_by_id) == {
        "edge:doc:paper-1:evi:ev-1",
        "edge:evi:ev-1:cmp:cmp-1",
        f"edge:cmp:cmp-1:{material_node_id}",
        f"edge:cmp:cmp-1:{property_node_id}",
        f"edge:cmp:cmp-1:{test_condition_node_id}",
        f"edge:cmp:cmp-1:{baseline_node_id}",
    }
    assert edges_by_id["edge:doc:paper-1:evi:ev-1"]["edge_description"] == (
        "document_to_evidence"
    )
    assert edges_by_id[f"edge:cmp:cmp-1:{material_node_id}"]["edge_description"] == (
        "comparison_to_material"
    )
    assert edges_by_id[f"edge:cmp:cmp-1:{property_node_id}"]["edge_description"] == (
        "comparison_to_property"
    )


def test_core_projection_skips_placeholder_semantic_nodes(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": "col-1",
                "title": "Placeholder Graph Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": "col-1",
                "claim_text": "Qualitative trend reported.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "epoxy composite", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.82,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": "col-1",
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "unspecified material system",
                "process_normalized": "700 C",
                "property_normalized": "qualitative",
                "baseline_normalized": "unspecified baseline",
                "test_condition_normalized": "--",
                "comparability_status": "limited",
                "comparability_warnings": [],
                "value": None,
                "unit": None,
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)

    nodes, edges, truncated = load_core_graph_payload(
        base_dir=output_dir,
        max_nodes=20,
        min_weight=0.0,
    )

    assert truncated is False
    assert {node["type"] for node in nodes} == {
        "document",
        "evidence",
        "comparison",
        "property",
    }
    assert {
        edge["edge_description"]
        for edge in edges
        if edge["edge_description"].startswith("comparison_to_")
    } == {"comparison_to_property"}


def test_core_projection_truncation_reserves_backbone_capacity(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": f"paper-{index}",
                "collection_id": "col-1",
                "title": f"Paper {index}",
                "source_filename": f"paper-{index}.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.9,
            }
            for index in range(1, 5)
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": f"ev-{index}",
                "document_id": f"paper-{index}",
                "collection_id": "col-1",
                "claim_text": f"Claim {index}",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "oxide cathode", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.82,
                "traceability_status": "direct",
            }
            for index in range(1, 5)
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": f"cmp-{index}",
                "collection_id": "col-1",
                "source_document_id": f"paper-{index}",
                "supporting_evidence_ids": [f"ev-{index}"],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": float(index),
                "unit": "mS/cm",
            }
            for index in range(1, 5)
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)

    nodes, _edges, truncated = load_core_graph_payload(
        base_dir=output_dir,
        max_nodes=10,
        min_weight=0.0,
    )

    assert truncated is True
    backbone_count = sum(
        1 for node in nodes if node["type"] in {"document", "evidence", "comparison"}
    )
    semantic_count = len(nodes) - backbone_count
    assert backbone_count >= 6
    assert semantic_count <= 4


def test_graph_service_serves_core_projection_without_legacy_graph_artifacts(
    monkeypatch,
    tmp_path,
):
    try:
        import fastapi  # noqa: F401
    except ImportError:
        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail):  # noqa: ANN001
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)

        monkeypatch.setitem(
            sys.modules,
            "fastapi",
            SimpleNamespace(HTTPException=_HTTPException),
        )

    import application.derived.graph_service as graph_service
    _patch_parquet(monkeypatch)

    from application.source.collection_service import CollectionService
    from application.source.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    monkeypatch.setattr(graph_service, "collection_service", collection_service)
    monkeypatch.setattr(graph_service, "artifact_registry_service", artifact_registry)

    collection = collection_service.create_collection("Core Projection Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Core Route Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": ["methods_section_detected"],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity increased to 12 mS/cm after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-1",
                        "source_type": "text",
                        "section_id": None,
                        "block_id": None,
                        "snippet_id": "tu-1",
                        "figure_or_table": None,
                        "quote_span": "Conductivity increased to 12 mS/cm after annealing.",
                    }
                ],
                "material_system": {"family": "oxide cathode", "composition": None},
                "condition_context": {
                    "process": {"temperatures_c": [700.0]},
                    "baseline": {"control": "as-prepared"},
                    "test": {"method": "EIS"},
                },
                "confidence": 0.83,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": collection_id,
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": 12.0,
                "unit": "mS/cm",
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = graph_service.get_collection_graph(
        collection_id=collection_id,
        max_nodes=20,
        min_weight=0.0,
    )

    assert payload["collection_id"] == collection_id
    assert len(payload["nodes"]) == 7
    assert len(payload["edges"]) == 6

    graphml_bytes, filename = graph_service.build_graphml(
        collection_id=collection_id,
        max_nodes=20,
        min_weight=0.0,
    )

    assert filename == f"{collection_id}.graphml"
    assert b"<graphml" in graphml_bytes


def test_graph_service_returns_one_hop_neighbors(monkeypatch, tmp_path):
    try:
        import fastapi  # noqa: F401
    except ImportError:
        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail):  # noqa: ANN001
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)

        monkeypatch.setitem(
            sys.modules,
            "fastapi",
            SimpleNamespace(HTTPException=_HTTPException),
        )

    import application.derived.graph_service as graph_service

    _patch_parquet(monkeypatch)

    from application.source.collection_service import CollectionService
    from application.source.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    monkeypatch.setattr(graph_service, "collection_service", collection_service)
    monkeypatch.setattr(graph_service, "artifact_registry_service", artifact_registry)

    collection = collection_service.create_collection("Graph Neighborhood Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Core Route Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity increased to 12 mS/cm after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "oxide cathode", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.83,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": collection_id,
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": 12.0,
                "unit": "mS/cm",
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = graph_service.get_collection_graph_neighbors(
        collection_id=collection_id,
        node_id="evi:ev-1",
    )

    assert payload["collection_id"] == collection_id
    assert payload["center_node_id"] == "evi:ev-1"
    assert payload["truncated"] is False
    assert {node["id"] for node in payload["nodes"]} == {
        "doc:paper-1",
        "evi:ev-1",
        "cmp:cmp-1",
    }
    assert {edge["id"] for edge in payload["edges"]} == {
        "edge:doc:paper-1:evi:ev-1",
        "edge:evi:ev-1:cmp:cmp-1",
    }

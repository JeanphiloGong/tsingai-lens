from __future__ import annotations

import json
import sys
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

    nodes, edges, truncated, community = load_core_graph_payload(
        base_dir=output_dir,
        max_nodes=20,
        min_weight=0.0,
    )

    assert truncated is False
    assert community is None
    assert len(nodes) == 3
    assert len(edges) == 2

    nodes_by_id = {node["id"]: node for node in nodes}
    assert set(nodes_by_id) == {"doc:paper-1", "evi:ev-1", "cmp:cmp-1"}
    assert nodes_by_id["doc:paper-1"]["type"] == "document"
    assert json.loads(nodes_by_id["doc:paper-1"]["node_document_ids"]) == ["paper-1"]
    assert nodes_by_id["evi:ev-1"]["type"] == "evidence"
    assert json.loads(nodes_by_id["evi:ev-1"]["node_text_unit_ids"]) == ["tu-1"]
    assert nodes_by_id["evi:ev-1"]["degree"] == 2
    assert nodes_by_id["cmp:cmp-1"]["type"] == "comparison"
    assert nodes_by_id["cmp:cmp-1"]["label"] == "epoxy composite | flexural_strength"
    assert json.loads(nodes_by_id["cmp:cmp-1"]["node_document_titles"]) == [
        "Core Graph Paper"
    ]

    edges_by_id = {edge["id"]: edge for edge in edges}
    assert set(edges_by_id) == {
        "edge:doc:paper-1:evi:ev-1",
        "edge:evi:ev-1:cmp:cmp-1",
    }
    assert edges_by_id["edge:doc:paper-1:evi:ev-1"]["edge_description"] == (
        "document_to_evidence"
    )
    assert json.loads(
        edges_by_id["edge:evi:ev-1:cmp:cmp-1"]["edge_text_unit_ids"]
    ) == ["tu-1"]


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
        community_id=None,
    )

    assert payload["collection_id"] == collection_id
    assert payload["community"] is None
    assert len(payload["nodes"]) == 3
    assert len(payload["edges"]) == 2

    graphml_bytes, filename = graph_service.build_graphml(
        collection_id=collection_id,
        max_nodes=20,
        min_weight=0.0,
        community_id=None,
    )

    assert filename == f"{collection_id}.graphml"
    assert b"<graphml" in graphml_bytes


def test_graph_service_rejects_legacy_community_filter(monkeypatch, tmp_path):
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

    collection = collection_service.create_collection("Filtered Graph Collection")
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

    try:
        graph_service.get_collection_graph(
            collection_id=collection_id,
            max_nodes=20,
            min_weight=0.0,
            community_id="1",
        )
    except graph_service.GraphFilterNotSupportedError as exc:
        assert exc.collection_id == collection_id
        assert exc.filter_name == "community_id"
    else:  # pragma: no cover
        raise AssertionError("expected GraphFilterNotSupportedError")

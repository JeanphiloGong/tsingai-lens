from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _ensure_fastapi_stub(monkeypatch) -> None:  # noqa: ANN001
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


def test_report_service_projects_core_patterns(monkeypatch, tmp_path):
    _ensure_fastapi_stub(monkeypatch)
    _patch_parquet(monkeypatch)

    from application.collections.service import CollectionService
    from application.reports import service as report_service
    from application.workspace.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    monkeypatch.setattr(report_service, "collection_service", collection_service)
    monkeypatch.setattr(report_service, "artifact_registry_service", artifact_registry)

    collection = collection_service.create_collection("Core Report Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Core Report Paper",
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

    assert not (output_dir / "entities.parquet").exists()
    assert not (output_dir / "relationships.parquet").exists()
    assert not (output_dir / "communities.parquet").exists()
    assert not (output_dir / "community_reports.parquet").exists()

    listing = report_service.list_community_reports(
        collection_id=collection_id,
        level=1,
        limit=10,
        offset=0,
        min_size=0,
        sort="rating",
    )
    assert listing.collection_id == collection_id
    assert listing.total == 1
    assert listing.items[0].community_id == 1
    assert listing.items[0].title == "oxide cathode | conductivity"

    detail = report_service.get_community_report_detail(
        collection_id=collection_id,
        community_id="1",
        level=1,
        entity_limit=20,
        relationship_limit=20,
        document_limit=20,
    )
    assert detail.collection_id == collection_id
    assert detail.community_id == 1
    assert detail.document_count == 1
    assert detail.text_unit_count == 1
    assert {item.type for item in detail.entities} == {
        "document",
        "evidence",
        "comparison",
    }
    assert {item.description for item in detail.relationships} == {
        "document_to_evidence",
        "evidence_to_comparison",
    }

    patterns = report_service.list_patterns(
        collection_id=collection_id,
        level=1,
        limit=10,
        sort="rating",
    )
    assert patterns.collection_id == collection_id
    assert patterns.total_communities == 1
    assert patterns.total_entities == 3
    assert patterns.total_relationships == 2
    assert patterns.total_documents == 1
    assert patterns.items[0].community_id == 1

from __future__ import annotations

import sys
from types import SimpleNamespace

from domain.core.comparison import ComparisonRowRecord
from domain.core.document_profile import DocumentProfile
from domain.core.evidence_backbone import EvidenceAnchor
from domain.core.fact_store import CoreFactSet
from infra.persistence.sqlite import SqliteCoreFactRepository


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


def _core_report_fact_set(collection_id: str) -> CoreFactSet:
    return CoreFactSet(
        paper_facts_ready=True,
        comparison_artifacts_ready=True,
        document_profiles=(
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "title": "Core Report Paper",
                    "source_filename": "paper.txt",
                    "doc_type": "experimental",
                    "parsing_warnings": [],
                    "confidence": 0.91,
                }
            ),
        ),
        evidence_anchors=(
            EvidenceAnchor.from_mapping(
                {
                    "anchor_id": "anchor-1",
                    "document_id": "paper-1",
                    "source_type": "text",
                    "snippet_id": "tu-1",
                    "quote_span": "Conductivity increased to 12 mS/cm after annealing.",
                }
            ),
        ),
        comparison_rows=(
            ComparisonRowRecord.from_mapping(
                {
                    "row_id": "cmp-1",
                    "collection_id": collection_id,
                    "comparable_result_id": "cres-1",
                    "source_document_id": "paper-1",
                    "supporting_evidence_ids": ["ev-1"],
                    "supporting_anchor_ids": ["anchor-1"],
                    "material_system_normalized": "oxide cathode",
                    "process_normalized": "700 C",
                    "property_normalized": "conductivity",
                    "baseline_normalized": "as-prepared",
                    "test_condition_normalized": "EIS",
                    "comparability_status": "comparable",
                    "comparability_warnings": [],
                    "comparability_basis": ["baseline_resolved"],
                    "result_summary": "12 mS/cm",
                    "result_source_type": "text",
                    "value": 12.0,
                    "unit": "mS/cm",
                }
            ),
        ),
    )


def test_report_service_projects_core_patterns(monkeypatch, tmp_path):
    _ensure_fastapi_stub(monkeypatch)

    from application.source.collection_service import CollectionService
    import application.derived.report_service as report_service

    collection_service = CollectionService(tmp_path / "collections")
    core_fact_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    monkeypatch.setattr(report_service, "collection_service", collection_service)
    monkeypatch.setattr(report_service, "core_fact_repository", core_fact_repository)

    collection = collection_service.create_collection("Core Report Collection")
    collection_id = collection["collection_id"]

    core_fact_repository.replace_collection_facts(
        collection_id,
        _core_report_fact_set(collection_id),
    )

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

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from tests.support.collection_service import build_test_collection_service
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.paper_facts_service import PaperFactsService
from controllers.core import evidence as evidence_controller
from domain.core import CoreFactSet, EvidenceAnchor, MeasurementResult, SampleVariant
from infra.persistence.sqlite import SqliteSourceArtifactRepository


@pytest.fixture()
def evidence_services(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    document_profile_service = DocumentProfileService(
        collection_service,
        source_artifact_repository=source_repository,
    )
    paper_facts_service = PaperFactsService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        document_profile_service=document_profile_service,
    )

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(paper_facts_service=paper_facts_service),
        )
    )
    return collection_service, paper_facts_service, request


def test_evidence_route_returns_409_when_cards_are_not_ready(evidence_services):
    collection_service, _paper_facts_service, request = evidence_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            evidence_controller.list_collection_evidence_cards(
                record["collection_id"],
                request,
            )
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "evidence_cards_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_evidence_route_returns_404_for_missing_collection(evidence_services):
    _collection_service, _paper_facts_service, request = evidence_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            evidence_controller.list_collection_evidence_cards("col_missing", request)
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_evidence_route_returns_200_with_empty_cards_after_stage_generated(
    evidence_services,
):
    collection_service, paper_facts_service, request = evidence_services
    record = collection_service.create_collection(name="Empty Evidence Collection")
    collection_id = record["collection_id"]
    paper_facts_service.core_fact_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(paper_facts_ready=True),
    )

    payload = asyncio.run(
        evidence_controller.list_collection_evidence_cards(collection_id, request)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0


def test_evidence_card_route_returns_single_card(evidence_services):
    collection_service, paper_facts_service, request = evidence_services
    record = collection_service.create_collection(name="Single Evidence Collection")
    collection_id = record["collection_id"]
    paper_facts_service.core_fact_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            paper_facts_ready=True,
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "paper-1",
                        "locator_type": "text",
                        "locator_confidence": "direct",
                        "source_type": "text",
                        "quote": "Conductivity improved after annealing.",
                    }
                ),
            ),
            sample_variants=(
                SampleVariant.from_mapping(
                    {
                        "variant_id": "var-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_label": "A1",
                        "host_material_system": {"family": "oxide cathode"},
                    }
                ),
            ),
            measurement_results=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "res-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_id": "var-1",
                        "property_normalized": "conductivity",
                        "result_type": "scalar",
                        "value_payload": {
                            "value": 12.0,
                            "statement": "Conductivity improved after annealing.",
                        },
                        "unit": "mS/cm",
                        "evidence_anchor_ids": ["anchor-1"],
                        "traceability_status": "direct",
                        "result_source_type": "text",
                    }
                ),
            ),
        ),
    )

    payload = asyncio.run(
        evidence_controller.get_collection_evidence_card(
            collection_id,
            "ev_result_res-1",
            request,
        )
    )

    assert payload.evidence_id == "ev_result_res-1"
    assert payload.collection_id == collection_id
    assert payload.claim_type == "property"

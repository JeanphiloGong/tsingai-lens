from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from application.comparisons.service import ComparisonService
from application.documents.service import DocumentProfileService
from application.evidence.service import EvidenceCardService


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def test_evidence_and_comparison_services_build_backbone_artifacts(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.artifact_registry_service import ArtifactRegistryService
    from application.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        evidence_card_service,
    )

    collection = collection_service.create_collection("Evidence Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Epoxy Composite Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                        "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-3",
                "text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    profiles = document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = evidence_card_service.build_evidence_cards(collection_id, output_dir)
    comparisons = comparison_service.build_comparison_rows(collection_id, output_dir)

    assert not profiles.empty
    assert len(evidence) >= 2
    assert set(evidence["claim_type"]) >= {"process", "characterization", "property"}
    assert not comparisons.empty
    assert "comparability_status" in comparisons.columns
    assert "limited" in set(comparisons["comparability_status"]) or "comparable" in set(
        comparisons["comparability_status"]
    )
    artifacts = artifact_registry.get(collection_id)
    assert artifacts["document_profiles_ready"] is True
    assert artifacts["evidence_cards_ready"] is True
    assert artifacts["comparison_rows_ready"] is True


def test_evidence_cards_parquet_write_handles_empty_nested_contexts(tmp_path):
    pytest.importorskip("pyarrow")

    from application.collections.service import CollectionService
    from application.documents.service import DocumentProfileService
    from application.evidence.service import EvidenceCardService
    from application.workspace.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Process Only Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Process Only Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The slurry was stirred for 2 h and dried at 80 C under Ar.",
                        "Characterization",
                        "SEM was used to inspect the coating.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The slurry was stirred for 2 h and dried at 80 C under Ar.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = evidence_card_service.build_evidence_cards(collection_id, output_dir)

    assert not evidence.empty
    assert output_dir.joinpath("evidence_cards.parquet").exists()
    reloaded = pd.read_parquet(output_dir / "evidence_cards.parquet")
    assert not reloaded.empty
    assert isinstance(reloaded.iloc[0]["condition_context"], str)


def test_evidence_service_normalizes_array_backed_condition_contexts(tmp_path):
    from application.collections.service import CollectionService
    from application.documents.service import DocumentProfileService
    from application.evidence.service import EvidenceCardService
    from application.workspace.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    normalized = evidence_card_service._normalize_condition_context_payload(
        {
            "process": {
                "temperatures_c": np.array([80.0, 600.0]),
                "durations": np.array(["2 h", "4 h"], dtype=object),
                "atmosphere": "Ar",
            },
            "baseline": {
                "control": None,
            },
            "test": {
                "methods": np.array(["XRD", "SEM"], dtype=object),
                "method": None,
            },
        }
    )

    assert normalized == {
        "process": {
            "temperatures_c": [80.0, 600.0],
            "durations": ["2 h", "4 h"],
            "atmosphere": "Ar",
        },
        "baseline": {
            "control": None,
        },
        "test": {
            "methods": ["XRD", "SEM"],
            "method": None,
        },
    }


def test_comparison_service_builds_rows_from_array_backed_nested_contexts(tmp_path):
    from application.collections.service import CollectionService
    from application.workspace.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        DocumentProfileService(collection_service, artifact_registry),
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        evidence_card_service,
    )

    row = comparison_service._build_row_from_card(
        pd.Series(
            {
                "evidence_id": "evi-1",
                "collection_id": "col-1",
                "document_id": "paper-1",
                "claim_text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "claim_type": "property",
                "condition_context": {
                    "process": {
                        "temperatures_c": np.array([80.0]),
                        "durations": np.array(["2 h"], dtype=object),
                        "atmosphere": "Ar",
                    },
                    "baseline": {
                        "control": "untreated baseline",
                    },
                    "test": {
                        "methods": np.array(["SEM"], dtype=object),
                        "method": None,
                    },
                },
                "material_system": {
                    "family": "epoxy composite",
                    "composition": None,
                },
                "evidence_anchors": [],
                "traceability_status": "direct",
            }
        )
    )

    assert row["process_normalized"] == "80 C, 2 h, under Ar"
    assert row["baseline_normalized"] == "untreated baseline"
    assert row["test_condition_normalized"] == "SEM"
    assert row["comparability_status"] == "comparable"


def test_evidence_and_comparison_services_round_trip_real_parquet_storage(tmp_path):
    pytest.importorskip("pyarrow")

    from application.collections.service import CollectionService
    from application.documents.service import DocumentProfileService
    from application.evidence.service import EvidenceCardService
    from application.workspace.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        evidence_card_service,
    )

    collection = collection_service.create_collection("Round Trip Evidence Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Epoxy Composite Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "SEM was used to characterize the powders.",
                        "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = evidence_card_service.build_evidence_cards(collection_id, output_dir)
    comparisons = comparison_service.build_comparison_rows(collection_id, output_dir)

    assert not evidence.empty
    assert not comparisons.empty

    stored_evidence = pd.read_parquet(output_dir / "evidence_cards.parquet")
    stored_comparisons = pd.read_parquet(output_dir / "comparison_rows.parquet")
    assert isinstance(stored_evidence.iloc[0]["evidence_anchors"], str)
    assert isinstance(stored_evidence.iloc[0]["material_system"], str)
    assert isinstance(stored_evidence.iloc[0]["condition_context"], str)
    assert isinstance(stored_comparisons.iloc[0]["supporting_evidence_ids"], str)
    assert isinstance(stored_comparisons.iloc[0]["comparability_warnings"], str)

    restored_evidence = evidence_card_service.read_evidence_cards(collection_id)
    restored_comparisons = comparison_service.read_comparison_rows(collection_id)
    assert isinstance(restored_evidence.iloc[0]["evidence_anchors"], list)
    assert isinstance(restored_evidence.iloc[0]["material_system"], dict)
    assert isinstance(restored_evidence.iloc[0]["condition_context"], dict)
    assert isinstance(restored_comparisons.iloc[0]["supporting_evidence_ids"], list)
    assert isinstance(restored_comparisons.iloc[0]["comparability_warnings"], list)


def test_evidence_service_list_recovers_quote_span_as_string(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.artifact_registry_service import ArtifactRegistryService
    from application.collection_service import CollectionService
    from controllers.schemas.evidence import EvidenceCardListResponse

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Evidence Quote Span Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    cards = pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "The document reports process evidence.",
                "claim_type": "process",
                "evidence_source_type": "method",
                "evidence_anchors": json.dumps(
                    [
                        {
                            "anchor_id": "anchor-1",
                            "source_type": "method",
                            "section_id": "sec-1",
                            "block_id": None,
                            "snippet_id": "tu-1",
                            "figure_or_table": None,
                            "quote_span": "[31]",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "material_system": json.dumps(
                    {"family": "composite", "composition": None},
                    ensure_ascii=False,
                ),
                "condition_context": json.dumps(
                    {"process": {}, "baseline": {}, "test": {}},
                    ensure_ascii=False,
                ),
                "confidence": 0.8,
                "traceability_status": "direct",
            }
        ]
    )
    cards.to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = evidence_card_service.list_evidence_cards(collection_id)
    assert payload["items"][0]["evidence_anchors"][0]["quote_span"] == "[31]"

    response = EvidenceCardListResponse(**payload)
    assert response.items[0].evidence_anchors[0].quote_span == "[31]"

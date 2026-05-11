from __future__ import annotations

import numpy as np
import pandas as pd

from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from domain.core.document_profile import DocumentProfile
from domain.source import SourceArtifactSet
from infra.source.runtime.source_evidence import build_blocks


def _build_profile_service(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    return collection_service, artifact_registry, DocumentProfileService(
        collection_service,
        artifact_registry,
    )


def _write_source_artifacts(
    profile_service: DocumentProfileService,
    collection_id: str,
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> None:
    blocks = build_blocks(documents, text_units)
    profile_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=documents.to_dict(orient="records"),
            text_units=(
                [] if text_units is None else text_units.to_dict(orient="records")
            ),
            blocks=blocks.to_dict(orient="records"),
        ),
    )


def test_document_profile_service_builds_profiles_and_summary(tmp_path):
    collection_service, artifact_registry, profile_service = _build_profile_service(
        tmp_path
    )
    collection = collection_service.create_collection("Profiled Collection")
    collection_id = collection["collection_id"]

    documents = pd.DataFrame(
        [
            {
                "id": "exp-1",
                "title": "Composite Experimental Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            },
            {
                "id": "rev-1",
                "title": "A Review of Composite Fillers",
                "text": "This review summarizes recent advances in epoxy composite fillers.",
            },
            {
                "id": "mix-1",
                "title": "Review and Experimental Notes on Ceramic Coatings",
                "text": "\n".join(
                    [
                        "This review also reports a small validation study.",
                        "Experimental Section",
                        "Solutions were mixed and heated at 90 C for 4 h.",
                        "Characterization",
                        "SEM was used to inspect the coating.",
                    ]
                ),
            },
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-exp-1",
                "text": "Powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["exp-1"],
            },
            {
                "id": "tu-exp-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["exp-1"],
            },
            {
                "id": "tu-mix-1",
                "text": "Solutions were mixed and heated at 90 C for 4 h.",
                "document_ids": ["mix-1"],
            },
        ]
    )
    _write_source_artifacts(profile_service, collection_id, documents, text_units)
    artifact_registry.upsert(
        collection_id,
        collection_service.get_paths(collection_id).output_dir,
    )

    payload = profile_service.list_document_profiles(collection_id)

    assert payload["count"] == 3
    items = {item["document_id"]: item for item in payload["items"]}
    assert items["exp-1"]["title"] == "Composite Experimental Study"
    assert items["exp-1"]["doc_type"] == "experimental"
    assert items["rev-1"]["doc_type"] == "review"
    assert items["mix-1"]["doc_type"] == "mixed"
    assert payload["summary"]["by_doc_type"] == {
        "experimental": 1,
        "mixed": 1,
        "review": 1,
    }
    facts = profile_service.core_fact_repository.read_collection_facts(collection_id)
    assert len(facts.document_profiles) == 3


def test_document_profile_service_returns_source_filename_from_file_mapping(tmp_path):
    collection_service, artifact_registry, profile_service = _build_profile_service(
        tmp_path
    )
    collection = collection_service.create_collection("Profiled Collection")
    collection_id = collection["collection_id"]
    file_record = collection_service.add_file(
        collection_id,
        "wang_2024_battery.txt",
        b"Experimental Section\nThe slurry was stirred for 2 h at 80 C.",
    )

    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": file_record["stored_filename"],
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The slurry was stirred for 2 h at 80 C.",
                        "Characterization",
                        "XRD was used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The slurry was stirred for 2 h at 80 C.",
                "document_ids": ["doc-1"],
            }
        ]
    )
    _write_source_artifacts(profile_service, collection_id, documents, text_units)
    artifact_registry.upsert(
        collection_id,
        collection_service.get_paths(collection_id).output_dir,
    )

    payload = profile_service.list_document_profiles(collection_id)

    item = payload["items"][0]
    assert item["document_id"] == "doc-1"
    assert item["title"] is None
    assert item["source_filename"] == "wang_2024_battery.txt"
    assert item["doc_type"] == "experimental"


def test_document_profile_service_short_circuits_insufficient_content(tmp_path):
    class ExplodingExtractor:
        def extract_document_profile(self, payload):  # noqa: ANN001
            raise AssertionError("extract_document_profile should not be called")

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    profile_service = DocumentProfileService(
        collection_service,
        artifact_registry,
        structured_extractor=ExplodingExtractor(),
    )
    collection = collection_service.create_collection("Sparse Profiles")
    collection_id = collection["collection_id"]
    documents = pd.DataFrame([{"id": "paper-1", "title": "", "text": ""}])
    text_units = pd.DataFrame(columns=["id", "text", "document_ids"])
    _write_source_artifacts(profile_service, collection_id, documents, text_units)
    artifact_registry.upsert(
        collection_id,
        collection_service.get_paths(collection_id).output_dir,
    )

    payload = profile_service.list_document_profiles(collection_id)

    item = payload["items"][0]
    assert item["doc_type"] == "uncertain"
    assert item["parsing_warnings"] == ["insufficient_content"]


def test_document_profile_service_normalizes_numpy_array_columns():
    profile_service = DocumentProfileService()

    profiles = [
        DocumentProfile.from_mapping(
            {
                "document_id": "doc-1",
                "collection_id": "col-1",
                "doc_type": "experimental",
                "parsing_warnings": np.array(["condition_context_weak"]),
                "confidence": 0.91,
            }
        )
    ]

    normalized = profile_service._normalize_profile_records(profiles, "col-1")

    assert normalized[0].to_record()["parsing_warnings"] == ["condition_context_weak"]


def test_document_profile_service_round_trips_repository_storage_fields(tmp_path):
    collection_service, artifact_registry, profile_service = _build_profile_service(
        tmp_path
    )
    collection = collection_service.create_collection("Round Trip Profiles")
    collection_id = collection["collection_id"]
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Experimental Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    _write_source_artifacts(profile_service, collection_id, documents, text_units)
    artifact_registry.upsert(
        collection_id,
        collection_service.get_paths(collection_id).output_dir,
    )

    profile_service.build_document_profiles(collection_id)

    restored = profile_service.read_document_profiles(collection_id)
    assert isinstance(restored[0].to_record()["parsing_warnings"], list)

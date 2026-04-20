from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from application.core.document_profile_service import DocumentProfileService
from infra.source.runtime.source_evidence import build_blocks


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _write_blocks(output_dir: Path, documents: pd.DataFrame, text_units: pd.DataFrame | None = None) -> None:
    build_blocks(documents, text_units).to_parquet(output_dir / "blocks.parquet", index=False)


def test_document_profile_service_builds_profiles_and_summary(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    profile_service = DocumentProfileService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Profiled Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

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
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_blocks(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    payload = profile_service.list_document_profiles(collection_id)

    assert payload["count"] == 3
    items = {item["document_id"]: item for item in payload["items"]}
    assert items["exp-1"]["title"] == "Composite Experimental Study"
    assert items["exp-1"]["source_filename"] is None
    assert items["exp-1"]["doc_type"] == "experimental"
    assert items["exp-1"]["protocol_extractable"] == "yes"
    assert items["exp-1"]["protocol_extractability_signals"] == []
    assert items["rev-1"]["title"] == "A Review of Composite Fillers"
    assert items["rev-1"]["doc_type"] == "review"
    assert items["rev-1"]["protocol_extractable"] == "no"
    assert items["rev-1"]["protocol_extractability_signals"] == []
    assert items["mix-1"]["title"] == "Review and Experimental Notes on Ceramic Coatings"
    assert items["mix-1"]["doc_type"] == "mixed"
    assert items["mix-1"]["protocol_extractable"] == "partial"
    assert items["mix-1"]["protocol_extractability_signals"] == []
    assert payload["summary"]["by_doc_type"] == {
        "experimental": 1,
        "mixed": 1,
        "review": 1,
    }
    assert payload["summary"]["by_protocol_extractable"] == {
        "no": 1,
        "partial": 1,
        "yes": 1,
    }
    assert output_dir.joinpath("document_profiles.parquet").exists()


def test_document_profile_service_returns_null_title_and_source_filename_from_file_mapping(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    profile_service = DocumentProfileService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Profiled Collection")
    collection_id = collection["collection_id"]
    file_record = collection_service.add_file(
        collection_id,
        "wang_2024_battery.txt",
        b"Experimental Section\nThe slurry was stirred for 2 h at 80 C.",
    )
    output_dir = collection_service.get_paths(collection_id).output_dir

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
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_blocks(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    payload = profile_service.list_document_profiles(collection_id)

    item = payload["items"][0]
    assert item["document_id"] == "doc-1"
    assert item["title"] is None
    assert item["source_filename"] == "wang_2024_battery.txt"
    assert item["doc_type"] == "experimental"
    assert item["protocol_extractable"] == "yes"
    assert item["protocol_extractability_signals"] == []


def test_document_profile_service_rebuilds_legacy_profiles_with_identity_fields(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    profile_service = DocumentProfileService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Legacy Profiled Collection")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nPowders were mixed in ethanol and dried at 80 C.",
    )
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and dried at 80 C.",
                        "Characterization",
                        "SEM was used to inspect the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed in ethanol and dried at 80 C.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    legacy_profiles = pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "doc_type": "experimental",
                "protocol_extractable": "partial",
                "protocol_extractability_signals": ["methods_section_detected"],
                "parsing_warnings": [],
                "confidence": 0.81,
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_blocks(output_dir, documents, text_units)
    legacy_profiles.to_parquet(output_dir / "document_profiles.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = profile_service.list_document_profiles(collection_id)

    item = payload["items"][0]
    assert item["title"] == "Composite Paper"
    assert item["source_filename"] == "paper.txt"
    assert item["doc_type"] == "experimental"
    assert item["protocol_extractable"] == "yes"
    assert item["protocol_extractability_signals"] == []


def test_document_profile_service_short_circuits_insufficient_content(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

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
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "",
                "text": "",
            }
        ]
    )
    text_units = pd.DataFrame(columns=["id", "text", "document_ids"])
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_blocks(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    payload = profile_service.list_document_profiles(collection_id)

    item = payload["items"][0]
    assert item["doc_type"] == "uncertain"
    assert item["protocol_extractable"] == "uncertain"
    assert item["protocol_extractability_signals"] == []
    assert item["parsing_warnings"] == ["insufficient_content"]


def test_document_profile_service_normalizes_numpy_array_columns():
    profile_service = DocumentProfileService()

    profiles = pd.DataFrame(
        [
            {
                "document_id": "doc-1",
                "collection_id": "col-1",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": np.array(["methods density", "condition completeness"]),
                "parsing_warnings": np.array(["condition_context_weak"]),
                "confidence": 0.91,
            }
        ]
    )

    normalized = profile_service._normalize_profiles_table(profiles, "col-1")

    assert normalized.iloc[0]["protocol_extractability_signals"] == [
        "methods density",
        "condition completeness",
    ]
    assert normalized.iloc[0]["parsing_warnings"] == ["condition_context_weak"]


def test_document_profile_service_round_trips_json_storage_fields(tmp_path):
    pytest.importorskip("pyarrow")

    from application.source.collection_service import CollectionService
    from application.source.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    profile_service = DocumentProfileService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Round Trip Profiles")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

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
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_blocks(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    profile_service.build_document_profiles(collection_id, output_dir)

    stored = pd.read_parquet(output_dir / "document_profiles.parquet")
    assert isinstance(stored.iloc[0]["protocol_extractability_signals"], str)
    assert isinstance(stored.iloc[0]["parsing_warnings"], str)

    restored = profile_service.read_document_profiles(collection_id)
    assert isinstance(restored.iloc[0]["protocol_extractability_signals"], list)
    assert isinstance(restored.iloc[0]["parsing_warnings"], list)

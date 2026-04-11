from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from application.documents.service import DocumentProfileService


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def test_document_profile_service_builds_profiles_and_summary(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.artifact_registry_service import ArtifactRegistryService
    from application.collection_service import CollectionService

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
    artifact_registry.upsert(collection_id, output_dir)

    payload = profile_service.list_document_profiles(collection_id)

    assert payload["count"] == 3
    items = {item["document_id"]: item for item in payload["items"]}
    assert items["exp-1"]["doc_type"] == "experimental"
    assert items["exp-1"]["protocol_extractable"] == "yes"
    assert items["rev-1"]["doc_type"] == "review"
    assert items["rev-1"]["protocol_extractable"] == "no"
    assert items["mix-1"]["doc_type"] == "mixed"
    assert items["mix-1"]["protocol_extractable"] == "partial"
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

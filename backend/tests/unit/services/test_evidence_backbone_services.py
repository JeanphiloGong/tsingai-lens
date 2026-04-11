from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

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

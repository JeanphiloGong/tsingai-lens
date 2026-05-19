from __future__ import annotations

import pytest

from application.source.reference_workflow_service import (
    SourceReferenceWorkflowService,
)
from domain.source import SourceArtifactSet, SourceBlock, SourceDocument
from infra.persistence.sqlite import SqliteSourceArtifactRepository


def test_source_reference_workflow_builds_and_persists_refs(tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    repository.replace_collection_artifacts(
        "col_refs",
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-1",
                    human_readable_id=0,
                    title="Paper",
                    text="Prior work [1] matters.\nReferences\n[1] Smith A. Paper. Journal. 2024.",
                ),
            ),
            blocks=(
                SourceBlock(
                    block_id="blk-body",
                    document_id="doc-1",
                    block_type="paragraph",
                    text="Prior work [1] matters.",
                    block_order=1,
                ),
                SourceBlock(
                    block_id="blk-ref-heading",
                    document_id="doc-1",
                    block_type="heading",
                    text="References",
                    block_order=2,
                ),
                SourceBlock(
                    block_id="blk-ref",
                    document_id="doc-1",
                    block_type="paragraph",
                    text="[1] Smith A. Paper. Journal. 2024.",
                    block_order=3,
                ),
            ),
        ),
    )
    service = SourceReferenceWorkflowService(source_artifact_repository=repository)

    result = service.build_collection_references("col_refs")

    assert result.to_summary() == {
        "collection_id": "col_refs",
        "entry_count": 1,
        "mention_count": 1,
        "resolution_count": 0,
        "candidate_count": 1,
    }
    restored = service.read_collection_references("col_refs")
    assert restored.references.entries[0].reference_id == "ref-doc-1-0001"
    assert restored.references.mentions[0].reference_id == "ref-doc-1-0001"
    assert restored.references.candidates[0].mention_count == 1


def test_source_reference_workflow_requires_source_artifacts(tmp_path):
    service = SourceReferenceWorkflowService(
        source_artifact_repository=SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    )

    with pytest.raises(FileNotFoundError, match="source artifacts not ready"):
        service.build_collection_references("missing_collection")

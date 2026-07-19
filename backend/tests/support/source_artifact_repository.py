from __future__ import annotations

from domain.source import (
    SourceArtifactSet,
    SourceReferenceSet,
    build_source_document_tree,
)


class MemorySourceArtifactRepository:
    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._artifacts: dict[tuple[str, str], SourceArtifactSet] = {}
        self._references: dict[tuple[str, str], SourceReferenceSet] = {}

    def replace_collection_artifacts(
        self,
        collection_id: str,
        build_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        self._artifacts[(collection_id, build_id)] = artifacts

    def read_collection_artifacts(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        selected_build_id = build_id or self.active_build_id
        return self._artifacts.get(
            (collection_id, selected_build_id), SourceArtifactSet()
        )

    def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._references[(collection_id, build_id)] = references

    def read_collection_references(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceReferenceSet:
        selected_build_id = build_id or self.active_build_id
        return self._references.get(
            (collection_id, selected_build_id), SourceReferenceSet()
        )

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ):
        artifacts = self.read_collection_artifacts(
            collection_id,
            build_id=build_id,
        )
        document = next(
            item for item in artifacts.documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=tuple(
                item for item in artifacts.blocks if item.document_id == document_id
            ),
            tables=tuple(
                item for item in artifacts.tables if item.document_id == document_id
            ),
            figures=tuple(
                item for item in artifacts.figures if item.document_id == document_id
            ),
            references=self.read_collection_references(
                collection_id,
                build_id=build_id,
            ),
        )

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id


__all__ = ["MemorySourceArtifactRepository"]

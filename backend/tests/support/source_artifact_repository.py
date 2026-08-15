from __future__ import annotations

from domain.source import (
    SourceDocument,
    SourceReferenceSet,
    build_source_document_tree,
)


class MemorySourceArtifactRepository:
    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._documents: dict[tuple[str, str], tuple[SourceDocument, ...]] = {}
        self._references: dict[tuple[str, str], SourceReferenceSet] = {}

    def replace_collection_documents(
        self,
        collection_id: str,
        build_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> None:
        self._documents[(collection_id, build_id)] = documents

    def read_collection_documents(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        selected_build_id = build_id or self.active_build_id
        return self._documents.get((collection_id, selected_build_id), ())

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
        documents = self.read_collection_documents(
            collection_id,
            build_id=build_id,
        )
        document = next(
            item for item in documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=document.blocks,
            tables=document.tables,
            figures=document.figures,
            references=self.read_collection_references(
                collection_id,
                build_id=build_id,
            ),
        )

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id


__all__ = ["MemorySourceArtifactRepository"]

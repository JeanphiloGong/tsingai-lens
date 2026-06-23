from __future__ import annotations

import pytest

from application.source.collection_service import CollectionService
from application.source.document_markdown_service import (
    DocumentMarkdownNotReadyError,
    DocumentMarkdownService,
    SourceDocumentNotFoundError,
)
from domain.source import SourceArtifactSet


def _build_markdown_service(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    return collection_service, DocumentMarkdownService(collection_service)


def test_document_markdown_service_projects_source_blocks_and_tables(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Markdown Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Battery Paper",
                    "text": "ignored when block structure is available",
                    "metadata": {
                        "source_filename": "battery.pdf",
                        "source_parser": "docling",
                    },
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-title",
                    "block_type": "title",
                    "block_order": 1,
                    "text": "Battery Paper",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-abstract-heading",
                    "block_type": "heading",
                    "block_order": 2,
                    "heading_level": 1,
                    "text": "Abstract",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-abstract",
                    "block_type": "paragraph",
                    "block_order": 3,
                    "heading_path": "Abstract",
                    "text": "Conductivity improved to 12 mS/cm.",
                    "text_unit_ids": ["tu-abstract"],
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-list",
                    "block_type": "list_item",
                    "block_order": 4,
                    "heading_path": "Abstract",
                    "text": "Annealed at 700 C.",
                    "page": 2,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-table-caption",
                    "block_type": "table_caption",
                    "block_order": 6,
                    "heading_path": "Results",
                    "text": "Table 1. Conductivity summary.",
                    "page": 3,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-results-heading",
                    "block_type": "heading",
                    "block_order": 5,
                    "heading_level": 1,
                    "heading_path": "Results",
                    "text": "Results",
                    "page": 3,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-results",
                    "block_type": "paragraph",
                    "block_order": 8,
                    "heading_path": "Results",
                    "text": "Results section text appears before the table.",
                    "page": 3,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-refs-heading",
                    "block_type": "heading",
                    "block_order": 10,
                    "heading_level": 1,
                    "heading_path": "References",
                    "text": "References",
                    "page": 10,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-ref",
                    "block_type": "paragraph",
                    "block_order": 11,
                    "heading_path": "References",
                    "text": "Reference text should appear in the paper reader.",
                    "page": 10,
                },
            ],
            tables=[
                {
                    "document_id": "paper-1",
                    "table_id": "tbl-1",
                    "table_order": 1,
                    "caption_text": "Table 1. Conductivity summary.",
                    "caption_block_id": "blk-table-caption",
                    "page": 3,
                    "heading_path": "Results",
                    "column_headers": ["Sample", "Conductivity"],
                    "table_matrix": [
                        ["Sample", "Conductivity"],
                        ["A", "12 mS/cm"],
                    ],
                }
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert payload["title"] == "Battery Paper"
    assert payload["source_filename"] == "battery.pdf"
    assert payload["parser"] == "docling"
    assert "# Battery Paper" in payload["markdown"]
    assert "## Abstract" in payload["markdown"]
    assert "Conductivity improved to 12 mS/cm." in payload["markdown"]
    assert "- Annealed at 700 C." in payload["markdown"]
    assert "## Results" in payload["markdown"]
    assert "Results section text appears before the table." in payload["markdown"]
    assert "**Table.** Table 1. Conductivity summary." in payload["markdown"]
    assert "| Sample | Conductivity |" in payload["markdown"]
    assert "| A | 12 mS/cm |" in payload["markdown"]
    assert "## References" in payload["markdown"]
    assert "Reference text should appear in the paper reader." in payload["markdown"]
    assert payload["warnings"] == []
    assert payload["markdown"].index("## Results") < payload["markdown"].index(
        "Results section text appears before the table."
    )
    assert payload["markdown"].index("Results section text appears before the table.") < (
        payload["markdown"].index("**Table.** Table 1. Conductivity summary.")
    )
    assert payload["markdown"].index("**Table.** Table 1. Conductivity summary.") < (
        payload["markdown"].index("## References")
    )

    source_map = {item["artifact_id"]: item for item in payload["source_map"]}
    assert source_map["blk-abstract"]["artifact_type"] == "block"
    assert source_map["blk-abstract"]["text_unit_ids"] == ["tu-abstract"]
    assert source_map["blk-abstract"]["heading_path"] == "Abstract"
    assert source_map["tbl-1"]["artifact_type"] == "table"
    assert source_map["tbl-1"]["table_id"] == "tbl-1"


def test_document_markdown_service_falls_back_to_document_text(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Markdown Fallback Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "",
                    "text": "Paragraph one.\n\nParagraph two.",
                }
            ]
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert payload["markdown"] == "Paragraph one.\n\nParagraph two."
    assert payload["warnings"] == ["block_structure_missing"]


def test_document_markdown_service_reports_not_ready(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Markdown Pending Collection")

    with pytest.raises(DocumentMarkdownNotReadyError):
        markdown_service.get_document_markdown(collection["collection_id"], "paper-1")


def test_document_markdown_service_reports_missing_document(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Markdown Missing Document")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[{"id": "paper-2", "title": "Other Paper", "text": "Text"}]
        ),
    )

    with pytest.raises(SourceDocumentNotFoundError):
        markdown_service.get_document_markdown(collection_id, "paper-1")

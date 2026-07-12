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


def test_document_markdown_service_projects_figure_images(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Figure Markdown Collection")
    collection_id = collection["collection_id"]
    figure_asset = collection_service.get_paths(collection_id).output_dir / "image_assets" / "fig-1.png"
    figure_asset.parent.mkdir(parents=True, exist_ok=True)
    figure_asset.write_bytes(b"fake-png")
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Figure Paper",
                    "text": "ignored when figure structure is available",
                }
            ],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "figure_label": "Fig. 1",
                    "caption_text": "Fig. 1. Microstructure after annealing.",
                    "page": 4,
                    "heading_path": "Results",
                    "image_path": "image_assets/fig-1.png",
                    "image_mime_type": "image/png",
                    "image_width": 640,
                    "image_height": 360,
                }
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert (
        f"![Fig. 1](/api/v1/collections/{collection_id}/documents/"
        "paper-1/figures/fig-1/image)"
    ) in payload["markdown"]
    assert "**Figure.** Fig. 1. Microstructure after annealing." in payload["markdown"]
    source_map = {item["artifact_id"]: item for item in payload["source_map"]}
    assert source_map["fig-1"]["artifact_type"] == "figure"
    assert source_map["fig-1"]["figure_id"] == "fig-1"


def test_document_markdown_service_keeps_caption_when_figure_image_file_is_missing(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Missing Figure Asset Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "figure_label": "Fig. 1",
                    "caption_text": "Fig. 1. Microstructure after annealing.",
                    "page": 4,
                    "heading_path": "Results",
                    "image_path": "image_assets/missing-fig-1.png",
                    "image_mime_type": "image/png",
                }
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert "![Fig. 1]" not in payload["markdown"]
    assert "**Figure.** Fig. 1. Microstructure after annealing." in payload["markdown"]


def test_document_markdown_service_keeps_caption_when_figure_image_is_missing(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Figure Caption Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "figure_label": "Fig. 1",
                    "caption_text": "Fig. 1. Microstructure after annealing.",
                    "page": 4,
                    "heading_path": "Results",
                    "image_path": None,
                }
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert "![Fig. 1]" not in payload["markdown"]
    assert "**Figure.** Fig. 1. Microstructure after annealing." in payload["markdown"]


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


def test_document_markdown_service_filters_pdf_glyph_garbage(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Garbled Markdown Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Paper With Encoded Headers",
                    "text": "ignored when block structure is available",
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-heading",
                    "block_type": "heading",
                    "block_order": 1,
                    "heading_level": 1,
                    "text": "Introduction",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-garbled-header",
                    "block_type": "paragraph",
                    "block_order": 2,
                    "text": "4DWHULDOV xFLHQFH c (QJLQHHULQJ E OiU iSiUG lnyfvf",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-good",
                    "block_type": "paragraph",
                    "block_order": 3,
                    "heading_path": "Introduction",
                    "text": "Readable scientific content remains visible.",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-garbled-footer",
                    "block_type": "paragraph",
                    "block_order": 4,
                    "text": "SOil,USOIt\x8b iSiU 9KH EXWKRUVK 3XEOLVKHG E\\ (OVHYLHU",
                    "page": 1,
                },
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert "Readable scientific content remains visible." in payload["markdown"]
    assert "4DWHULDOV" not in payload["markdown"]
    assert "SOil,USOIt" not in payload["markdown"]
    assert payload["warnings"] == ["garbled_text_blocks_skipped"]
    source_map = {item["artifact_id"]: item for item in payload["source_map"]}
    assert "blk-good" in source_map
    assert "blk-garbled-header" not in source_map


def test_document_markdown_service_keeps_readable_block_with_replacement_glyph(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Readable Glyph Collection")
    collection_id = collection["collection_id"]
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Readable Paper",
                    "text": "ignored when block structure is available",
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-conclusion-heading",
                    "block_type": "heading",
                    "block_order": 1,
                    "heading_level": 1,
                    "text": "4. Conclusion",
                    "page": 12,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-readable-conclusion",
                    "block_type": "list_item",
                    "block_order": 2,
                    "heading_path": "4. Conclusion",
                    "text": (
                        "\ufffd The  SLM  samples  processed  at  higher  scanning  "
                        "speed exhibited better densification, refined microstructure, "
                        "and excellent mechanical properties."
                    ),
                    "page": 12,
                },
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert "\ufffd" not in payload["markdown"]
    assert (
        "- The SLM samples processed at higher scanning speed exhibited better "
        "densification, refined microstructure, and excellent mechanical properties."
    ) in payload["markdown"]
    assert payload["warnings"] == []
    source_map = {item["artifact_id"]: item for item in payload["source_map"]}
    assert "blk-readable-conclusion" in source_map


def test_document_markdown_service_uses_original_filename_for_display(tmp_path):
    collection_service, markdown_service = _build_markdown_service(tmp_path)
    collection = collection_service.create_collection("Stored Filename Collection")
    collection_id = collection["collection_id"]
    collection_service.repository.write_files(
        collection_id,
        [
            {
                "original_filename": "P001-Readable Paper.pdf",
                "stored_filename": "abc123_P001-Readable Paper.pdf",
            }
        ],
    )
    markdown_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "abc123_P001-Readable Paper.pdf",
                    "text": "ignored when block structure is available",
                    "metadata": {
                        "source_path": "abc123_P001-Readable Paper.pdf",
                        "source_parser": "docling",
                    },
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-good",
                    "block_type": "paragraph",
                    "block_order": 1,
                    "text": "Readable paper body.",
                    "page": 1,
                }
            ],
        ),
    )

    payload = markdown_service.get_document_markdown(collection_id, "paper-1")

    assert payload["title"] == "P001-Readable Paper.pdf"
    assert payload["source_filename"] == "P001-Readable Paper.pdf"
    assert payload["markdown"].startswith("# P001-Readable Paper.pdf")
    assert "abc123_P001" not in payload["markdown"]


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

from __future__ import annotations

import base64

import pytest

from infra.source.ingestion.normalized_import import normalize_upload


def test_normalize_upload_builds_text_batch_for_plain_text():
    batch = normalize_upload(
        filename="paper.txt",
        content=b"Experimental Section\nMix and anneal.",
        media_type="text/plain",
    )

    assert len(batch.documents) == 1
    assert len(batch.text_units) == 1
    assert batch.documents[0].origin_channel == "upload"
    assert batch.documents[0].original_filename == "paper.txt"
    assert batch.documents[0].stored_filename.endswith("_paper.txt")
    assert batch.documents[0].ingest_status == "normalized"
    assert batch.documents[0].checksum
    assert batch.text_units[0].source_document_id == batch.documents[0].source_document_id
    assert batch.text_units[0].text == "Experimental Section\nMix and anneal."
    assert batch.text_units[0].char_count == len("Experimental Section\nMix and anneal.")
    assert batch.source_metadata.channel == "upload"
    assert batch.source_metadata.adapter_name == "upload"
    assert batch.source_metadata.raw_locator == "paper.txt"
    assert batch.source_metadata.warnings == ()


def test_normalize_upload_preserves_pdf_payload_for_pdf():
    batch = normalize_upload(
        filename="paper.pdf",
        content=b"%PDF-1.4 test",
        media_type="application/pdf",
        adapter_name="upload_pdf",
        goal_context={"intent": "compare"},
    )

    assert batch.documents[0].original_filename == "paper.pdf"
    assert batch.documents[0].stored_filename.endswith("_paper.pdf")
    assert base64.b64decode(batch.documents[0].storage_payload_base64) == b"%PDF-1.4 test"
    assert batch.text_units == ()
    assert batch.source_metadata.adapter_name == "upload_pdf"
    assert batch.source_metadata.goal_context == {"intent": "compare"}


def test_normalize_upload_rejects_unsupported_binary_upload():
    with pytest.raises(ValueError) as exc_info:
        normalize_upload(
            filename="paper.bin",
            content=b"\xff\xd8\xff\xe0",
            media_type="application/octet-stream",
        )

    assert "unsupported upload type" in str(exc_info.value)

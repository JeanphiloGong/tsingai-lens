from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter
import pytest

from infra.source.ingestion.upload_validation import validate_upload


def _valid_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    payload = BytesIO()
    writer.write(payload)
    return payload.getvalue()


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("paper.TXT", None),
        ("paper.md", None),
        ("paper.markdown", None),
        ("paper.csv", None),
        ("paper.tsv", None),
        ("paper.json", None),
        ("paper", "text/plain"),
        ("paper", "application/json"),
        ("paper", "application/xml"),
        ("paper.pdf", "text/plain"),
    ],
)
def test_validate_upload_accepts_text_extensions_and_media_types(filename, media_type):
    validate_upload(filename, b"Experimental Section\nMix and anneal.", media_type)


def test_validate_upload_accepts_readable_pdf():
    validate_upload("paper.PDF", _valid_pdf_bytes(), "application/pdf")


@pytest.mark.parametrize("content", [_valid_pdf_bytes()[:100], b"", b"not a PDF"])
def test_validate_upload_rejects_unreadable_pdf(content):
    with pytest.raises(
        ValueError,
        match="PDF is damaged, incomplete, password-protected, or otherwise unreadable",
    ):
        validate_upload(
            filename="truncated.pdf",
            content=content,
            media_type="application/pdf",
        )


def test_validate_upload_rejects_unsupported_binary_upload():
    with pytest.raises(ValueError) as exc_info:
        validate_upload(
            filename="paper.bin",
            content=b"\xff\xd8\xff\xe0",
            media_type="application/octet-stream",
        )

    assert "unsupported upload type" in str(exc_info.value)


def test_validate_upload_rejects_non_utf8_text():
    with pytest.raises(ValueError, match="text upload must be valid UTF-8"):
        validate_upload("paper.txt", b"\xff", "text/plain")


def test_validate_upload_rejects_empty_text_but_accepts_whitespace():
    with pytest.raises(ValueError, match="uploaded file is empty"):
        validate_upload("paper.txt", b"", "text/plain")
    validate_upload("paper.txt", b" \n\t", "text/plain")

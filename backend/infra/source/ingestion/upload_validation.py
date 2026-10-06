"""Validate uploaded bytes without transforming the original file."""

from pathlib import Path


_UNREADABLE_PDF_MESSAGE = (
    "PDF is damaged, incomplete, password-protected, or otherwise unreadable."
)


def validate_upload(filename: str, content: bytes, media_type: str | None) -> None:
    suffix = Path(filename).suffix.lower()
    if (
        suffix in {".txt", ".md", ".markdown", ".csv", ".tsv", ".json"}
        or (media_type and media_type.startswith("text/"))
        or media_type in {"application/json", "application/xml"}
    ):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("text upload must be valid UTF-8") from exc
        if not content:
            raise ValueError("uploaded file is empty")
    elif suffix == ".pdf":
        _validate_pdf_upload(content)
    else:
        raise ValueError(f"unsupported upload type: {filename}")


def _validate_pdf_upload(content: bytes) -> None:
    from pypdfium2 import PdfDocument

    try:
        document = PdfDocument(content)
        try:
            page_count = len(document)
        finally:
            document.close()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_UNREADABLE_PDF_MESSAGE) from exc
    if page_count < 1:
        raise ValueError(_UNREADABLE_PDF_MESSAGE)

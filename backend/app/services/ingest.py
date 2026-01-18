"""Input ingestion helpers."""

import logging

import fitz
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def pdf_to_text(content: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF (fitz)."""
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            texts = []
            for page in doc:
                texts.append(page.get_text("text"))
        return "\n".join(texts)
    except Exception as exc:
        logger.exception("PDF parsing failed")
        raise HTTPException(status_code=400, detail=f"PDF解析失败: {exc}") from exc

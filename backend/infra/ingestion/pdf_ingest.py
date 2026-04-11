"""Input ingestion helpers."""

import logging

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None

logger = logging.getLogger(__name__)


def pdf_to_text(content: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF (fitz)."""
    if fitz is None:
        raise RuntimeError("PyMuPDF 未安装，无法处理 PDF")
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            texts = []
            for page in doc:
                texts.append(page.get_text("text"))
        return "\n".join(texts)
    except Exception as exc:
        logger.exception("PDF parsing failed")
        raise ValueError(f"PDF解析失败: {exc}") from exc

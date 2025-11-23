import base64
import csv
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
import markdown
import pandas as pd
from docx import Document as DocxDocument


def read_pdf(path: Path) -> Tuple[str, List[Dict]]:
    """Extract text and a lightweight image manifest from PDF."""
    doc = fitz.open(path)
    texts: List[str] = []
    images: List[Dict] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        texts.append(page.get_text("text"))

        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            b64 = base64.b64encode(image_bytes).decode("ascii")
            images.append(
                {
                    "id": f"{page_index}-{img_index}",
                    "page": page_index + 1,
                    "ext": base_image.get("ext", "png"),
                    "data": b64,
                }
            )

    return "\n".join(texts), images


def read_docx(path: Path) -> str:
    doc = DocxDocument(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def read_markdown(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    html = markdown.markdown(text)
    return html


def read_txt(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_csv(path: Path, limit: int = 50) -> str:
    """Read CSV into text representation; limit rows to avoid huge payloads."""
    rows: List[str] = []
    with open(path, newline="", encoding="utf-8") as fp:
        reader = csv.reader(fp)
        for i, row in enumerate(reader):
            rows.append(", ".join(row))
            if i >= limit:
                rows.append("... (truncated)")
                break
    return "\n".join(rows)


def load_file(path: Path) -> Tuple[str, List[Dict]]:
    """Load supported file types and return (text, images)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in {".docx", ".doc"}:
        return read_docx(path), []
    if suffix in {".md", ".markdown"}:
        return read_markdown(path), []
    if suffix in {".csv"}:
        return read_csv(path), []
    if suffix in {".txt"}:
        return read_txt(path), []
    raise ValueError(f"Unsupported file type: {suffix}")

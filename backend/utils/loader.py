import base64
import csv
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional for environments without PDF support
    fitz = None
import markdown
from docx import Document as DocxDocument


def _require_fitz():
    if fitz is None:
        return False
    return True


def read_pdf(path: Path) -> Tuple[List[Tuple[int, str]], List[Dict]]:
    """Extract per-page text (1-based page numbers) and a lightweight image manifest from PDF."""
    if not _require_fitz():
        # Fallback: return placeholder text if PyMuPDF is unavailable in this interpreter
        placeholder = f"[PDF parsing unavailable in current environment] {path.name}"
        return [(1, placeholder)], []
    doc = fitz.open(path)
    pages: List[Tuple[int, str]] = []
    images: List[Dict] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        pages.append((page_index + 1, page.get_text("text")))

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

    return pages, images


def read_docx(path: Path) -> List[Tuple[int, str]]:
    doc = DocxDocument(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return [(1, "\n".join(paragraphs))]


def read_markdown(path: Path) -> List[Tuple[int, str]]:
    text = Path(path).read_text(encoding="utf-8")
    html = markdown.markdown(text)
    return [(1, html)]


def read_txt(path: Path) -> List[Tuple[int, str]]:
    return [(1, Path(path).read_text(encoding="utf-8"))]


def read_csv(path: Path, limit: int = 50) -> List[Tuple[int, str]]:
    """Read CSV into text representation; limit rows to avoid huge payloads."""
    rows: List[str] = []
    with open(path, newline="", encoding="utf-8") as fp:
        reader = csv.reader(fp)
        for i, row in enumerate(reader):
            rows.append(", ".join(row))
            if i >= limit:
                rows.append("... (truncated)")
                break
    return [(1, "\n".join(rows))]


def load_file(path: Path) -> Tuple[List[Tuple[int, str]], List[Dict]]:
    """Load supported file types and return ([(page_no, text)], images)."""
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

from typing import Dict, List, Tuple


def chunk_pages(pages: List[Tuple[int, str]], max_chars: int = 800, overlap: int = 100) -> List[Tuple[str, Dict]]:
    """Chunk per-page text with small overlap; carry page number and chunk_id."""
    chunks: List[Tuple[str, Dict]] = []
    chunk_id = 0
    for page_no, text in pages:
        cleaned = text.replace("\r", "\n").replace("\u3000", " ").strip()
        paragraphs = [p.strip() for p in cleaned.split("\n") if p.strip()]
        for para in paragraphs:
            start = 0
            while start < len(para):
                end = min(start + max_chars, len(para))
                chunk_text = para[start:end]
                meta = {"page": page_no, "chunk_id": chunk_id}
                chunks.append((chunk_text, meta))
                chunk_id += 1
                if end == len(para):
                    break
                start = max(0, end - overlap)
    return chunks

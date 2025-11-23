from typing import List


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> List[str]:
    """Simple sliding window chunker to keep context for embeddings."""
    cleaned = text.replace("\r", "\n").replace("\u3000", " ").strip()
    paragraphs = [p.strip() for p in cleaned.split("\n") if p.strip()]
    chunks: List[str] = []

    for para in paragraphs:
        start = 0
        while start < len(para):
            end = min(start + max_chars, len(para))
            chunk = para[start:end]
            chunks.append(chunk)
            if end == len(para):
                break
            start = max(0, end - overlap)

    return chunks

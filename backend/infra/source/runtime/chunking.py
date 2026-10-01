# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Token chunking used by the Source runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import tiktoken

EncodedText = list[int]
DecodeFn = Callable[[EncodedText], str]
EncodeFn = Callable[[str], EncodedText]


@dataclass
class TextChunk:
    """One token-bounded text window."""

    text_chunk: str
    n_tokens: int


def get_encoding_fn(encoding_name: str) -> tuple[EncodeFn, DecodeFn]:
    """Get encoder and decoder for a token encoding."""
    encoding = tiktoken.get_encoding(encoding_name)

    def encode(text: str) -> list[int]:
        if not isinstance(text, str):
            text = f"{text}"
        return encoding.encode(text)

    def decode(tokens: list[int]) -> str:
        return encoding.decode(tokens)

    return encode, decode


def chunk_text(
    text: str,
    size: int,
    overlap: int,
    encoding_model: str,
) -> list[TextChunk]:
    """Split one document into overlapping token windows."""
    encode, decode = get_encoding_fn(encoding_model)
    token_ids = encode(text)
    step = size - overlap
    chunks: list[TextChunk] = []

    for start in range(0, len(token_ids), step):
        chunk_ids = token_ids[start : start + size]
        chunks.append(TextChunk(decode(chunk_ids), len(chunk_ids)))
        if start + size >= len(token_ids):
            break

    return chunks

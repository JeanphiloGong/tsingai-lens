# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Chunking helpers used by the Source runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd
import tiktoken

from infra.source.runtime.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.runtime.progress import ProgressTicker, progress_ticker

EncodedText = list[int]
DecodeFn = Callable[[EncodedText], str]
EncodeFn = Callable[[str], EncodedText]


@dataclass(frozen=True)
class TokenChunkerOptions:
    """Token chunking options."""

    chunk_overlap: int
    tokens_per_chunk: int
    decode: DecodeFn
    encode: EncodeFn


@dataclass
class TextChunk:
    """Chunk payload with source metadata."""

    text_chunk: str
    source_doc_indices: list[int]
    n_tokens: int | None = None


@dataclass
class ChunkingConfig:
    """Minimal chunking config used by the Source runtime."""

    size: int
    overlap: int
    encoding_model: str


ChunkInput = str | list[str] | list[tuple[str, str]]
ChunkStrategy = Callable[[list[str], ChunkingConfig, ProgressTicker], Iterable[TextChunk]]


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
    input_frame: pd.DataFrame,
    column: str,
    size: int,
    overlap: int,
    encoding_model: str,
    strategy: Any,
    callbacks: WorkflowCallbacks,
) -> pd.Series:
    """Chunk a piece of text into smaller pieces."""
    strategy_exec = load_strategy(strategy)
    tick = progress_ticker(callbacks.progress, _get_num_total(input_frame, column))
    config = ChunkingConfig(
        size=size,
        overlap=overlap,
        encoding_model=encoding_model,
    )

    return cast(
        "pd.Series",
        input_frame.apply(
            cast(
                "Any",
                lambda row: run_strategy(strategy_exec, row[column], config, tick),
            ),
            axis=1,
        ),
    )


def run_strategy(
    strategy_exec: ChunkStrategy,
    input_value: ChunkInput,
    config: ChunkingConfig,
    tick: ProgressTicker,
) -> list[str | tuple[list[str] | None, str, int]]:
    """Run a chunking strategy."""
    if isinstance(input_value, str):
        return [item.text_chunk for item in strategy_exec([input_value], config, tick)]

    texts = [item if isinstance(item, str) else item[1] for item in input_value]
    strategy_results = strategy_exec(texts, config, tick)

    results = []
    for strategy_result in strategy_results:
        doc_indices = strategy_result.source_doc_indices
        if isinstance(input_value[doc_indices[0]], str):
            results.append(strategy_result.text_chunk)
        else:
            doc_ids = [input_value[doc_idx][0] for doc_idx in doc_indices]
            results.append((doc_ids, strategy_result.text_chunk, strategy_result.n_tokens))
    return results


def load_strategy(strategy: Any) -> ChunkStrategy:
    """Load the requested chunking strategy."""
    strategy_name = _normalize_strategy_name(strategy)
    if strategy_name == "tokens":
        return run_tokens
    if strategy_name == "sentence":
        _bootstrap_nltk()
        return run_sentences
    raise ValueError(f"Unknown strategy: {strategy_name}")


def run_tokens(
    input_texts: list[str],
    config: ChunkingConfig,
    tick: ProgressTicker,
) -> Iterable[TextChunk]:
    """Chunk text using token windows."""
    encode, decode = get_encoding_fn(config.encoding_model)
    return split_multiple_texts_on_tokens(
        input_texts,
        TokenChunkerOptions(
            chunk_overlap=config.overlap,
            tokens_per_chunk=config.size,
            encode=encode,
            decode=decode,
        ),
        tick,
    )


def run_sentences(
    input_texts: list[str],
    _config: ChunkingConfig,
    tick: ProgressTicker,
) -> Iterable[TextChunk]:
    """Chunk text by sentence."""
    import nltk

    for doc_idx, text in enumerate(input_texts):
        for sentence in nltk.sent_tokenize(text):
            yield TextChunk(
                text_chunk=sentence,
                source_doc_indices=[doc_idx],
            )
        tick(1)


def split_multiple_texts_on_tokens(
    texts: list[str], tokenizer: TokenChunkerOptions, tick: ProgressTicker
) -> list[TextChunk]:
    """Split multiple texts and return chunks with metadata."""
    result = []
    mapped_ids = []

    for source_doc_idx, text in enumerate(texts):
        encoded = tokenizer.encode(text)
        tick(1)
        mapped_ids.append((source_doc_idx, encoded))

    input_ids = [
        (source_doc_idx, token_id)
        for source_doc_idx, token_ids in mapped_ids
        for token_id in token_ids
    ]

    start_idx = 0
    cur_idx = min(start_idx + tokenizer.tokens_per_chunk, len(input_ids))
    chunk_ids = input_ids[start_idx:cur_idx]

    while start_idx < len(input_ids):
        chunk_text_value = tokenizer.decode([token_id for _, token_id in chunk_ids])
        doc_indices = list({doc_idx for doc_idx, _ in chunk_ids})
        result.append(TextChunk(chunk_text_value, doc_indices, len(chunk_ids)))
        if cur_idx == len(input_ids):
            break
        start_idx += tokenizer.tokens_per_chunk - tokenizer.chunk_overlap
        cur_idx = min(start_idx + tokenizer.tokens_per_chunk, len(input_ids))
        chunk_ids = input_ids[start_idx:cur_idx]

    return result


def _get_num_total(output: pd.DataFrame, column: str) -> int:
    num_total = 0
    for row in output[column]:
        if isinstance(row, str):
            num_total += 1
        else:
            num_total += len(row)
    return num_total


def _normalize_strategy_name(strategy: Any) -> str:
    return str(getattr(strategy, "value", strategy))


_nltk_bootstrapped = False


def _bootstrap_nltk() -> None:
    """Bootstrap nltk resources lazily."""
    global _nltk_bootstrapped
    if _nltk_bootstrapped:
        return

    import nltk
    from nltk.corpus import wordnet as wn

    nltk.download("punkt")
    nltk.download("punkt_tab")
    nltk.download("averaged_perceptron_tagger")
    nltk.download("averaged_perceptron_tagger_eng")
    nltk.download("maxent_ne_chunker")
    nltk.download("maxent_ne_chunker_tab")
    nltk.download("words")
    nltk.download("wordnet")
    wn.ensure_loaded()
    _nltk_bootstrapped = True

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


BACKEND_ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_BATCH_SIZE = 64


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare TF-IDF and embedding retrieval over canonical PostgreSQL "
            "Source text units. This benchmark does not change runtime retrieval."
        )
    )
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-api-key")
    return parser.parse_args()


def rank_tfidf(
    corpus: list[dict[str, str]],
    queries: list[dict[str, Any]],
) -> dict[str, list[str]]:
    text_unit_ids = [item["text_unit_id"] for item in corpus]
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(
        [item["text"] for item in corpus] + [item["query"] for item in queries]
    )
    scores = cosine_similarity(matrix[len(corpus) :], matrix[: len(corpus)])
    return {
        query["id"]: _rank_ids(text_unit_ids, query_scores)
        for query, query_scores in zip(queries, scores, strict=True)
    }


def rank_embeddings(
    *,
    text_unit_ids: list[str],
    corpus_vectors: np.ndarray,
    query_ids: list[str],
    query_vectors: np.ndarray,
) -> dict[str, list[str]]:
    scores = cosine_similarity(query_vectors, corpus_vectors)
    return {
        query_id: _rank_ids(text_unit_ids, query_scores)
        for query_id, query_scores in zip(query_ids, scores, strict=True)
    }


def evaluate_ranking(
    *,
    ranked_ids: list[str],
    relevant_ids: set[str],
    locators: dict[str, dict[str, Any]],
    k: int,
) -> dict[str, Any]:
    top_ids = ranked_ids[:k]
    top_set = set(top_ids)
    ranking = []
    for rank, text_unit_id in enumerate(top_ids, start=1):
        locator = locators.get(text_unit_id, {})
        ranking.append(
            {
                "rank": rank,
                "text_unit_id": text_unit_id,
                "relevant": text_unit_id in relevant_ids,
                "document_ids": locator.get("document_ids", []),
                "blocks": locator.get("blocks", []),
                "preview": locator.get("preview", ""),
            }
        )
    return {
        "recall_at_k": len(top_set & relevant_ids) / len(relevant_ids),
        "traceability_at_k": (
            sum(_is_traceable(locators.get(text_unit_id)) for text_unit_id in top_ids)
            / len(top_ids)
            if top_ids
            else 0.0
        ),
        "false_positive_ids": [
            text_unit_id for text_unit_id in top_ids if text_unit_id not in relevant_ids
        ],
        "miss_ids": sorted(relevant_ids - top_set),
        "ranking": ranking,
    }


def validate_fixture(
    fixture: dict[str, Any],
    *,
    collection_id: str,
    available_ids: set[str],
    locators: dict[str, dict[str, Any]],
) -> None:
    if fixture.get("schema_version") != 1:
        raise ValueError("fixture schema_version must be 1")
    filters = fixture.get("filters")
    if not isinstance(filters, dict) or filters.get("collection_id") != collection_id:
        raise ValueError("fixture collection filter does not match requested collection")
    document_ids = filters.get("document_ids")
    if not isinstance(document_ids, list) or not document_ids:
        raise ValueError("fixture document filter must be a non-empty list")
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("fixture document filter contains duplicate IDs")
    queries = fixture.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("fixture queries must be a non-empty list")
    query_ids = [query.get("id") for query in queries]
    if any(not query_id for query_id in query_ids) or len(set(query_ids)) != len(
        query_ids
    ):
        raise ValueError("fixture query IDs must be non-empty and unique")
    for query in queries:
        if not str(query.get("query", "")).strip():
            raise ValueError(f"fixture query text is empty: {query['id']}")
        relevant_ids = query.get("relevant_text_unit_ids")
        if not isinstance(relevant_ids, list) or not relevant_ids:
            raise ValueError(f"fixture relevant IDs are empty: {query['id']}")
        source_locators = query.get("source_locators")
        if not isinstance(source_locators, list) or {
            item.get("text_unit_id") for item in source_locators
        } != set(relevant_ids):
            raise ValueError(
                f"fixture source locators must match relevant IDs: {query['id']}"
            )
    gold_ids = {
        text_unit_id
        for query in queries
        for text_unit_id in query["relevant_text_unit_ids"]
    }
    invalid_ids = sorted(
        text_unit_id
        for text_unit_id in gold_ids
        if text_unit_id not in available_ids
        or not _is_traceable(locators.get(text_unit_id))
    )
    if invalid_ids:
        raise ValueError(
            "gold text units are missing or untraceable: " + ", ".join(invalid_ids)
        )
    mismatched_locators = []
    for query in queries:
        for expected in query["source_locators"]:
            actual = locators[expected["text_unit_id"]]
            block_matches = any(
                block.get("document_id") == expected.get("document_id")
                and block.get("block_id") == expected.get("block_id")
                and block.get("page") == expected.get("page")
                for block in actual["blocks"]
            )
            if expected.get("document_id") not in actual["document_ids"] or not block_matches:
                mismatched_locators.append(expected["text_unit_id"])
    if mismatched_locators:
        raise ValueError(
            "gold locator does not match canonical Source: "
            + ", ".join(sorted(mismatched_locators))
        )


def embed_texts(client: OpenAI, model: str, texts: list[str]) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        response = client.embeddings.create(
            model=model,
            input=texts[start : start + EMBEDDING_BATCH_SIZE],
        )
        vectors.extend(
            item.embedding for item in sorted(response.data, key=lambda item: item.index)
        )
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding provider returned {len(vectors)} vectors for {len(texts)} texts"
        )
    return np.asarray(vectors, dtype=float)


def normalize_embedding_base_url(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/embeddings")


def build_locators(text_units: list[Any], blocks: list[Any]) -> dict[str, dict[str, Any]]:
    locators = {
        text_unit.text_unit_id: {
            "document_ids": list(text_unit.document_ids),
            "blocks": [],
            "preview": " ".join(text_unit.text.split())[:280],
        }
        for text_unit in text_units
    }
    for block in blocks:
        for text_unit_id in block.text_unit_ids:
            if text_unit_id in locators:
                locators[text_unit_id]["blocks"].append(
                    {
                        "block_id": block.block_id,
                        "document_id": block.document_id,
                        "page": block.page,
                    }
                )
    return locators


def build_results(
    *,
    fixture: dict[str, Any],
    rankings: dict[str, dict[str, list[str]]],
    locators: dict[str, dict[str, Any]],
    k: int,
) -> dict[str, Any]:
    method_results: dict[str, Any] = {}
    for method, query_rankings in rankings.items():
        query_results = []
        for query in fixture["queries"]:
            evaluation = evaluate_ranking(
                ranked_ids=query_rankings[query["id"]],
                relevant_ids=set(query["relevant_text_unit_ids"]),
                locators=locators,
                k=k,
            )
            query_results.append(
                {"query_id": query["id"], "query": query["query"], **evaluation}
            )
        method_results[method] = {
            "recall_at_k": sum(item["recall_at_k"] for item in query_results)
            / len(query_results),
            "traceability_at_k": sum(
                item["traceability_at_k"] for item in query_results
            )
            / len(query_results),
            "queries": query_results,
        }
    return method_results


def main() -> int:
    args = parse_args()
    if args.k <= 0:
        raise SystemExit("--k must be greater than 0")
    sys.path.insert(0, str(BACKEND_ROOT))
    from infra.persistence.database import (  # noqa: PLC0415
        DatabaseSettings,
        build_database_engine,
        build_session_factory,
    )
    from infra.persistence.postgres.source_artifact_repository import (  # noqa: PLC0415
        PostgresSourceArtifactRepository,
    )

    fixture = json.loads(args.fixture.resolve().read_text(encoding="utf-8"))
    engine = build_database_engine(DatabaseSettings())
    try:
        repository = PostgresSourceArtifactRepository(build_session_factory(engine))
        text_units = repository.list_text_units(args.collection_id)
        blocks = repository.list_blocks(args.collection_id)
    finally:
        engine.dispose()
    if not text_units:
        raise SystemExit(f"collection has no active Source text units: {args.collection_id}")

    locators = build_locators(text_units, blocks)
    filtered_document_ids = set(fixture.get("filters", {}).get("document_ids", []))
    text_units = [
        text_unit
        for text_unit in text_units
        if filtered_document_ids.intersection(text_unit.document_ids)
    ]
    corpus = [
        {"text_unit_id": text_unit.text_unit_id, "text": text_unit.text}
        for text_unit in text_units
    ]
    validate_fixture(
        fixture,
        collection_id=args.collection_id,
        available_ids={item["text_unit_id"] for item in corpus},
        locators=locators,
    )

    model = args.embedding_model or os.getenv("EMBEDDING_MODEL", "").strip()
    base_url = normalize_embedding_base_url(
        args.embedding_base_url or os.getenv("EMBEDDING_BASE_URL", "").strip()
    )
    api_key = args.embedding_api_key or os.getenv("EMBEDDING_API_KEY", "").strip()
    if not model:
        raise SystemExit("EMBEDDING_MODEL is unresolved; set it or pass --embedding-model")
    if not api_key and base_url:
        api_key = "not-needed"
    if not api_key:
        raise SystemExit(
            "EMBEDDING_API_KEY is unresolved; set it or pass --embedding-api-key"
        )

    queries = fixture["queries"]
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    corpus_vectors = embed_texts(client, model, [item["text"] for item in corpus])
    query_vectors = embed_texts(client, model, [query["query"] for query in queries])
    rankings = {
        "tfidf": rank_tfidf(corpus, queries),
        "embedding": rank_embeddings(
            text_unit_ids=[item["text_unit_id"] for item in corpus],
            corpus_vectors=corpus_vectors,
            query_ids=[query["id"] for query in queries],
            query_vectors=query_vectors,
        ),
    }
    output = {
        "schema_version": 1,
        "collection_id": args.collection_id,
        "fixture": fixture["name"],
        "filters": fixture["filters"],
        "corpus_text_unit_count": len(corpus),
        "k": args.k,
        "embedding_model": model,
        "methods": build_results(
            fixture=fixture,
            rankings=rankings,
            locators=locators,
            k=args.k,
        ),
        "decision_status": "awaiting_human_decision",
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _rank_ids(text_unit_ids: list[str], scores: np.ndarray) -> list[str]:
    return [
        text_unit_id
        for text_unit_id, _ in sorted(
            zip(text_unit_ids, scores, strict=True),
            key=lambda item: (-float(item[1]), item[0]),
        )
    ]


def _is_traceable(locator: dict[str, Any] | None) -> bool:
    return bool(locator and locator.get("document_ids") and locator.get("blocks"))


if __name__ == "__main__":
    raise SystemExit(main())

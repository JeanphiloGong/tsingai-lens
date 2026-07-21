from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


def _load_benchmark_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "benchmarks" / "source_text_unit_retrieval.py"
    spec = importlib.util.spec_from_file_location(
        "source_text_unit_retrieval",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rank_tfidf_returns_most_relevant_text_unit_first() -> None:
    benchmark = _load_benchmark_module()
    corpus = [
        {"text_unit_id": "tu-b", "text": "scan speed controls melt pool overlap"},
        {"text_unit_id": "tu-a", "text": "corrosion resistance after heat treatment"},
        {"text_unit_id": "tu-c", "text": "higher scanning speed reduces melt pool size"},
    ]

    rankings = benchmark.rank_tfidf(
        corpus,
        [{"id": "q1", "query": "scanning speed and melt pool size"}],
    )

    assert rankings["q1"][0] == "tu-c"
    assert set(rankings["q1"]) == {"tu-a", "tu-b", "tu-c"}


def test_rank_embeddings_uses_cosine_similarity_and_stable_ties() -> None:
    benchmark = _load_benchmark_module()

    rankings = benchmark.rank_embeddings(
        text_unit_ids=["tu-b", "tu-a", "tu-c"],
        corpus_vectors=np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
        query_ids=["q1"],
        query_vectors=np.array([[1.0, 0.0]]),
    )

    assert rankings["q1"] == ["tu-a", "tu-b", "tu-c"]


def test_evaluate_ranking_reports_recall_traceability_false_positives_and_misses() -> None:
    benchmark = _load_benchmark_module()
    locators = {
        "relevant-found": {
            "document_ids": ["doc-1"],
            "blocks": [{"block_id": "block-1", "page": 4}],
        },
        "false-positive": {
            "document_ids": ["doc-2"],
            "blocks": [{"block_id": "block-2", "page": 7}],
        },
        "untraceable": {"document_ids": ["doc-3"], "blocks": []},
    }

    result = benchmark.evaluate_ranking(
        ranked_ids=["relevant-found", "false-positive", "untraceable"],
        relevant_ids={"relevant-found", "relevant-missed"},
        locators=locators,
        k=3,
    )

    assert result["recall_at_k"] == 0.5
    assert result["traceability_at_k"] == pytest.approx(2 / 3)
    assert result["false_positive_ids"] == ["false-positive", "untraceable"]
    assert result["miss_ids"] == ["relevant-missed"]
    assert result["ranking"][0]["document_ids"] == ["doc-1"]
    assert result["ranking"][0]["blocks"] == [{"block_id": "block-1", "page": 4}]


def test_validate_fixture_rejects_missing_or_untraceable_gold_ids() -> None:
    benchmark = _load_benchmark_module()
    fixture = {
        "schema_version": 1,
        "name": "test",
        "filters": {"collection_id": "col-1", "document_ids": ["doc-1"]},
        "queries": [
            {
                "id": "q1",
                "query": "question",
                "relevant_text_unit_ids": ["missing", "untraceable"],
                "source_locators": [
                    {
                        "text_unit_id": "missing",
                        "document_id": "doc-1",
                        "block_id": "block-1",
                        "page": 1,
                    },
                    {
                        "text_unit_id": "untraceable",
                        "document_id": "doc-1",
                        "block_id": "block-2",
                        "page": 2,
                    },
                ],
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="gold text units are missing or untraceable: missing, untraceable",
    ):
        benchmark.validate_fixture(
            fixture,
            collection_id="col-1",
            available_ids={"untraceable"},
            locators={"untraceable": {"document_ids": ["doc-1"], "blocks": []}},
        )


def test_validate_fixture_rejects_locator_that_does_not_match_source() -> None:
    benchmark = _load_benchmark_module()
    fixture = {
        "schema_version": 1,
        "name": "test",
        "filters": {"collection_id": "col-1", "document_ids": ["doc-1"]},
        "queries": [
            {
                "id": "q1",
                "query": "question",
                "relevant_text_unit_ids": ["tu-1"],
                "source_locators": [
                    {
                        "text_unit_id": "tu-1",
                        "document_id": "doc-1",
                        "block_id": "block-wrong",
                        "page": 4,
                    }
                ],
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="gold locator does not match canonical Source: tu-1",
    ):
        benchmark.validate_fixture(
            fixture,
            collection_id="col-1",
            available_ids={"tu-1"},
            locators={
                "tu-1": {
                    "document_ids": ["doc-1"],
                    "blocks": [
                        {
                            "block_id": "block-1",
                            "document_id": "doc-1",
                            "page": 4,
                        }
                    ],
                }
            },
        )


def test_normalize_embedding_base_url_accepts_configured_endpoint_url() -> None:
    benchmark = _load_benchmark_module()

    assert (
        benchmark.normalize_embedding_base_url(
            "https://embedding.example/v1/embeddings/"
        )
        == "https://embedding.example/v1"
    )
    assert (
        benchmark.normalize_embedding_base_url("https://embedding.example/v1")
        == "https://embedding.example/v1"
    )

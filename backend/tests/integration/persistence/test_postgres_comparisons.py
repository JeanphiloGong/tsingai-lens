from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from domain.core import ComparisonFactSet
from domain.core.comparison_assembly import ComparableResultAssembler, ComparisonInputRecords
from infra.persistence.postgres.comparison_repository import PostgresComparisonRepository
from infra.persistence.postgres.models.comparison import CollectionComparableResultRecord
from infra.persistence.postgres.paper_fact_repository import PostgresPaperFactRepository
from tests.integration.persistence.test_postgres_paper_facts import _paper_facts
from tests.integration.persistence.test_postgres_source_artifacts import (
    _artifacts,
    _finish,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio


async def _write_paper_build(source_repository, builds, build_id: str):
    task = _task(f"task_{build_id}")
    await builds.add_task(task, build_id=build_id)
    await source_repository.replace_collection_documents(
        "col_source",
        build_id,
        _artifacts(),
    )
    paper = _paper_facts()
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    await repository.replace_document_profiles(
        "col_source",
        build_id,
        paper.document_profiles,
    )
    await repository.replace_paper_facts("col_source", build_id, paper)
    return task, paper


def _comparison_facts(paper=None, *, ready: bool = True) -> ComparisonFactSet:
    paper = paper or _paper_facts()
    semantics = ComparableResultAssembler().assemble_semantic_records(
        collection_id="col_source",
        records=ComparisonInputRecords(
            sample_variants=paper.sample_variants,
            measurement_results=tuple(
                replace(result, claim_scope="current_work")
                for result in paper.measurement_results
            ),
            test_conditions=paper.test_conditions,
            baseline_references=paper.baseline_references,
        ),
    )
    return ComparisonFactSet(
        comparison_artifacts_ready=ready,
        comparable_results=semantics.comparable_results,
        collection_comparable_results=semantics.collection_comparable_results,
        pairwise_comparison_relations=semantics.pairwise_comparison_relations,
    )


async def test_comparison_repository_round_trips_only_the_active_build(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task, paper = await _write_paper_build(
        source_repository,
        builds,
        "build_comparisons",
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts(paper)

    await repository.replace("col_source", "build_comparisons", expected)

    assert await repository.read("col_source") == ComparisonFactSet()
    assert await repository.read(
        "col_source", build_id="build_comparisons"
    ) == expected

    await _finish(builds, task, success=True)

    assert await repository.read("col_source") == expected
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace("col_source", "build_comparisons", expected)


async def test_failed_comparison_build_cannot_replace_active_facts(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresComparisonRepository(source_repository.session_factory)
    active_task, active_paper = await _write_paper_build(
        source_repository,
        builds,
        "build_comparisons_active",
    )
    active = _comparison_facts(active_paper)
    await repository.replace("col_source", "build_comparisons_active", active)
    await _finish(builds, active_task, success=True)

    failed_task, failed_paper = await _write_paper_build(
        source_repository,
        builds,
        "build_comparisons_failed",
    )
    failed = _comparison_facts(failed_paper)
    await repository.replace("col_source", "build_comparisons_failed", failed)
    await _finish(builds, failed_task, success=False)

    assert await repository.read("col_source") == active
    assert await repository.read(
        "col_source", build_id="build_comparisons_failed"
    ) == failed


async def test_comparison_replacement_is_atomic_for_invalid_source_and_anchor(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    _task_record, paper = await _write_paper_build(
        source_repository,
        builds,
        "build_comparisons_atomic",
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts(paper)
    await repository.replace("col_source", "build_comparisons_atomic", expected)

    comparable = expected.comparable_results[0]
    invalid_source = replace(comparable, source_result_id="missing-result")
    with pytest.raises(ValueError, match="source result"):
        await repository.replace(
            "col_source",
            "build_comparisons_atomic",
            replace(expected, comparable_results=(invalid_source,)),
        )
    assert await repository.read(
        "col_source", build_id="build_comparisons_atomic"
    ) == expected

    invalid_anchor = replace(
        comparable,
        evidence=replace(comparable.evidence, direct_anchor_ids=("missing-anchor",)),
    )
    with pytest.raises(ValueError, match="evidence anchor"):
        await repository.replace(
            "col_source",
            "build_comparisons_atomic",
            replace(expected, comparable_results=(invalid_anchor,)),
        )
    assert await repository.read(
        "col_source", build_id="build_comparisons_atomic"
    ) == expected


async def test_collection_assessment_rejects_cross_collection_build_lineage(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    _task_record, paper = await _write_paper_build(
        source_repository,
        builds,
        "build_comparison_assessment_lineage",
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts(paper)
    await repository.replace(
        "col_source",
        "build_comparison_assessment_lineage",
        expected,
    )

    with pytest.raises(IntegrityError):
        async with source_repository.session_factory.begin() as session:
            assessment = await session.get(
                CollectionComparableResultRecord,
                (
                    "build_comparison_assessment_lineage",
                    expected.collection_comparable_results[0].comparable_result_id,
                ),
            )
            assert assessment is not None
            assessment.collection_id = "col_other"

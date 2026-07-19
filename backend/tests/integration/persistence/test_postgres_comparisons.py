from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.core import ComparisonFactSet, PairwiseComparisonRelation
from domain.core.objective_comparison_projection import (
    project_objective_comparison_semantics,
)
from domain.source import CollectionRecord
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.comparison_repository import (
    PostgresComparisonRepository,
)
from infra.persistence.postgres.models.comparison import (
    CollectionComparableResultRecord,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_objectives import (
    _objective_facts,
    _write_build,
)
from infra.persistence.postgres.paper_fact_repository import PostgresPaperFactRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.test_postgres_paper_facts import _paper_facts
from tests.integration.persistence.test_postgres_source_artifacts import (
    BACKEND_ROOT,
    NOW,
    _artifacts,
    _collection_import,
    _finish,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def _comparison_facts(*, ready: bool = True) -> ComparisonFactSet:
    semantics = project_objective_comparison_semantics(
        collection_id="col_source",
        evidence_units=_objective_facts().objective_evidence_units,
    )
    return ComparisonFactSet(
        comparison_artifacts_ready=ready,
        comparable_results=semantics.comparable_results,
        collection_comparable_results=semantics.collection_comparable_results,
        pairwise_comparison_relations=semantics.pairwise_comparison_relations,
    )


def test_comparison_repository_round_trips_only_the_active_build(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _write_build(
        source_repository,
        builds,
        "build_comparisons",
        _objective_facts(),
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts()

    repository.replace("col_source", "build_comparisons", expected)

    assert repository.read("col_source") == ComparisonFactSet()
    assert repository.read("col_source", build_id="build_comparisons") == expected

    _finish(builds, task, success=True)

    assert repository.read("col_source") == expected
    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace("col_source", "build_comparisons", expected)


def test_failed_comparison_build_cannot_replace_active_facts(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresComparisonRepository(source_repository.session_factory)
    active_task = _write_build(
        source_repository,
        builds,
        "build_comparisons_active",
        _objective_facts("How does processing affect strength?"),
    )
    active = _comparison_facts()
    repository.replace("col_source", "build_comparisons_active", active)
    _finish(builds, active_task, success=True)

    failed_task = _write_build(
        source_repository,
        builds,
        "build_comparisons_failed",
        _objective_facts("How does processing affect fatigue?"),
    )
    failed = replace(
        active,
        comparable_results=(
            replace(active.comparable_results[0], variant_label="Failed build"),
        ),
    )
    repository.replace("col_source", "build_comparisons_failed", failed)
    _finish(builds, failed_task, success=False)

    assert repository.read("col_source") == active
    assert repository.read("col_source", build_id="build_comparisons_failed") == failed


def test_empty_ready_comparison_build_is_distinct_from_not_generated(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _write_build(
        source_repository,
        builds,
        "build_comparisons_empty",
        _objective_facts(),
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = ComparisonFactSet(comparison_artifacts_ready=True)

    assert repository.read("col_source") == ComparisonFactSet()
    repository.replace("col_source", "build_comparisons_empty", expected)
    assert repository.read("col_source", build_id="build_comparisons_empty") == expected

    _finish(builds, task, success=True)
    assert repository.read("col_source") == expected


def test_comparison_replacement_is_atomic_for_invalid_source_and_anchor(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _write_build(
        source_repository,
        builds,
        "build_comparisons_atomic",
        _objective_facts(),
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts()
    repository.replace("col_source", "build_comparisons_atomic", expected)

    comparable = expected.comparable_results[0]
    invalid_source = replace(comparable, source_result_id="missing-unit")
    with pytest.raises(ValueError, match="source result"):
        repository.replace(
            "col_source",
            "build_comparisons_atomic",
            replace(expected, comparable_results=(invalid_source,)),
        )
    assert (
        repository.read("col_source", build_id="build_comparisons_atomic") == expected
    )

    invalid_anchor = replace(
        comparable,
        evidence=replace(comparable.evidence, direct_anchor_ids=("missing-anchor",)),
    )
    with pytest.raises(ValueError, match="evidence anchor"):
        repository.replace(
            "col_source",
            "build_comparisons_atomic",
            replace(expected, comparable_results=(invalid_anchor,)),
        )
    assert (
        repository.read("col_source", build_id="build_comparisons_atomic") == expected
    )

    _finish(builds, task, success=True)


def test_collection_assessment_rejects_cross_collection_build_lineage(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    _write_build(
        source_repository,
        builds,
        "build_comparison_assessment_lineage",
        _objective_facts(),
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)
    expected = _comparison_facts()
    repository.replace(
        "col_source",
        "build_comparison_assessment_lineage",
        expected,
    )

    with pytest.raises(IntegrityError):
        with source_repository.session_factory.begin() as session:
            assessment = session.get(
                CollectionComparableResultRecord,
                (
                    "build_comparison_assessment_lineage",
                    expected.collection_comparable_results[0].comparable_result_id,
                ),
            )
            assert assessment is not None
            assessment.collection_id = "col_other"


def test_paper_measurement_comparison_round_trips_ordered_lineage_and_pairwise(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _task("task_build_paper_comparisons")
    builds.add_task(task, build_id="build_paper_comparisons")
    source_repository.replace_collection_artifacts(
        "col_source",
        "build_paper_comparisons",
        _artifacts(),
    )
    paper = _paper_facts()
    second_anchor = replace(paper.evidence_anchors[0], anchor_id="anchor-2")
    second_observation = replace(
        paper.characterization_observations[0],
        observation_id="observation-2",
        evidence_anchor_ids=("anchor-2",),
    )
    second_feature = replace(
        paper.structure_features[0],
        feature_id="feature-2",
        source_observation_ids=("observation-2",),
    )
    second_variant = replace(
        paper.sample_variants[0],
        variant_id="variant-2",
        variant_label="Sample B",
        structure_feature_ids=("feature-2",),
        source_anchor_ids=("anchor-2",),
    )
    first_result = replace(
        paper.measurement_results[0],
        evidence_anchor_ids=("anchor-2", "anchor-1"),
        structure_feature_ids=("feature-2", "feature-1"),
        characterization_observation_ids=("observation-2", "observation-1"),
    )
    second_result = replace(
        paper.measurement_results[0],
        result_id="result-2",
        variant_id="variant-2",
        baseline_id=None,
        evidence_anchor_ids=("anchor-2",),
        structure_feature_ids=("feature-2",),
        characterization_observation_ids=("observation-2",),
    )
    expanded_paper = replace(
        paper,
        evidence_anchors=(paper.evidence_anchors[0], second_anchor),
        sample_variants=(paper.sample_variants[0], second_variant),
        measurement_results=(first_result, second_result),
        characterization_observations=(
            paper.characterization_observations[0],
            second_observation,
        ),
        structure_features=(paper.structure_features[0], second_feature),
    )
    paper_repository = PostgresPaperFactRepository(source_repository.session_factory)
    paper_repository.replace_document_profiles(
        "col_source",
        "build_paper_comparisons",
        expanded_paper.document_profiles,
    )
    paper_repository.replace_paper_facts(
        "col_source",
        "build_paper_comparisons",
        expanded_paper,
    )
    PostgresObjectiveRepository(source_repository.session_factory).replace(
        "col_source",
        "build_paper_comparisons",
        _objective_facts(),
    )

    objective_result = _comparison_facts().comparable_results[0]
    comparable = replace(
        objective_result,
        source_result_id="result-1",
        binding=replace(
            objective_result.binding,
            variant_id="variant-1",
            baseline_id="baseline-1",
            test_condition_id="condition-1",
        ),
        evidence=replace(
            objective_result.evidence,
            direct_anchor_ids=("anchor-2", "anchor-1"),
            evidence_ids=("ev_result_result-1",),
            structure_feature_ids=("feature-2", "feature-1"),
            characterization_observation_ids=("observation-2", "observation-1"),
        ),
    )
    scoped = replace(
        _comparison_facts().collection_comparable_results[0],
        comparable_result_id=comparable.comparable_result_id,
    )
    pairwise = PairwiseComparisonRelation.from_mapping(
        {
            "relation_id": "relation-1",
            "collection_id": "col_source",
            "document_id": "srcdoc_runtime",
            "current_variant_id": "variant-1",
            "reference_variant_id": "variant-2",
            "comparison_axis": "temperature",
            "property_normalized": "strength",
            "current_result_id": "result-1",
            "reference_result_id": "result-2",
            "current_value": 100,
            "reference_value": 90,
            "unit": "MPa",
            "direction": "higher",
            "evidence_anchor_ids": ["anchor-2", "anchor-1"],
            "confidence": 0.9,
        }
    )
    expected = ComparisonFactSet(
        comparison_artifacts_ready=True,
        comparable_results=(comparable,),
        collection_comparable_results=(scoped,),
        pairwise_comparison_relations=(pairwise,),
    )
    repository = PostgresComparisonRepository(source_repository.session_factory)

    repository.replace("col_source", "build_paper_comparisons", expected)

    assert repository.read("col_source", build_id="build_paper_comparisons") == expected
    _finish(builds, task, success=True)


def test_pairwise_relation_rejects_result_from_another_build(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    historical_task = _write_build(
        source_repository,
        builds,
        "build_comparison_history",
        _objective_facts(),
    )
    _finish(builds, historical_task, success=True)
    current_task = _task("task_build_comparison_current")
    builds.add_task(current_task, build_id="build_comparison_current")
    source_repository.replace_collection_artifacts(
        "col_source",
        "build_comparison_current",
        _artifacts(),
    )
    paper = _paper_facts()
    current_paper = replace(
        paper,
        measurement_results=(
            replace(paper.measurement_results[0], result_id="result-current"),
        ),
    )
    paper_repository = PostgresPaperFactRepository(source_repository.session_factory)
    paper_repository.replace_document_profiles(
        "col_source",
        "build_comparison_current",
        current_paper.document_profiles,
    )
    paper_repository.replace_paper_facts(
        "col_source",
        "build_comparison_current",
        current_paper,
    )
    PostgresObjectiveRepository(source_repository.session_factory).replace(
        "col_source",
        "build_comparison_current",
        _objective_facts(),
    )
    relation = PairwiseComparisonRelation.from_mapping(
        {
            "relation_id": "cross-build-relation",
            "collection_id": "col_source",
            "document_id": "srcdoc_runtime",
            "current_variant_id": "variant-1",
            "reference_variant_id": "variant-1",
            "comparison_axis": "temperature",
            "property_normalized": "strength",
            "current_result_id": "result-1",
            "reference_result_id": "result-current",
            "evidence_anchor_ids": ["anchor-1"],
        }
    )

    with pytest.raises(ValueError, match="pairwise result"):
        PostgresComparisonRepository(source_repository.session_factory).replace(
            "col_source",
            "build_comparison_current",
            ComparisonFactSet(
                comparison_artifacts_ready=True,
                pairwise_comparison_relations=(relation,),
            ),
        )


def test_comparison_schema_has_no_persisted_row_projection(
    source_repositories,
) -> None:
    source_repository, _ = source_repositories

    table_names = set(
        inspect(source_repository.session_factory.kw["bind"]).get_table_names()
    )

    assert "comparison_rows" not in table_names
    assert "core_comparison_rows" not in table_names


def test_postgresql_enforces_comparison_contract() -> None:
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith(
        "_test"
    ):
        pytest.fail(
            "LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database"
        )

    engine = create_engine(url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            command.upgrade(config, "head")
        sessions = build_session_factory(engine)
        PostgresAuthRepository(sessions).add_user(
            {
                "user_id": "user_comparisons",
                "email": "comparisons@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
            }
        )
        collections = PostgresCollectionRepository(sessions)
        collections.add_collection(
            CollectionRecord(
                collection_id="col_source",
                owner_user_id="user_comparisons",
                name="Comparison collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        collections.add_collection_import(
            _collection_import("stored-paper.pdf"),
            updated_at=NOW,
        )
        source_repository = PostgresSourceArtifactRepository(sessions)
        builds = PostgresBuildRepository(sessions)
        task = _write_build(
            source_repository,
            builds,
            "build_comparisons_postgresql",
            _objective_facts(),
        )
        repository = PostgresComparisonRepository(sessions)
        expected = _comparison_facts()

        repository.replace("col_source", "build_comparisons_postgresql", expected)

        assert repository.read("col_source") == ComparisonFactSet()
        assert (
            repository.read("col_source", build_id="build_comparisons_postgresql")
            == expected
        )
        assert "comparison_rows" not in inspect(engine).get_table_names()

        _finish(builds, task, success=True)
        assert repository.read("col_source") == expected
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()

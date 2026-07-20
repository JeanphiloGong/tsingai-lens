from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import CollectionRecord
from domain.core.document_profile import DocumentProfile
from domain.core.evidence_backbone import (
    BaselineReference,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    SampleVariant,
    StructureFeature,
    TestCondition as DomainTestCondition,
)
from domain.core.paper_fact import PaperFactSet
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.paper_fact import PaperFactDocumentProfile
from infra.persistence.postgres.paper_fact_repository import PostgresPaperFactRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.test_postgres_source_artifacts import (
    BACKEND_ROOT,
    NOW,
    REAL_SOURCE_BLOCK_ID,
    REAL_SOURCE_DOCUMENT_ID,
    REAL_SOURCE_TABLE_ID,
    _artifacts,
    _collection_import,
    _finish,
    _real_shape_artifacts,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def _paper_facts(title: str = "Profiled paper") -> PaperFactSet:
    anchor = EvidenceAnchor.from_mapping(
        {
            "anchor_id": "anchor-1",
            "document_id": "srcdoc_runtime",
            "locator_type": "block",
            "locator_confidence": "high",
            "source_type": "text",
            "section_id": "Methods",
            "char_range": {"start": 8, "end": 14},
            "page": 1,
            "quote": "Result",
            "deep_link": "#block-1",
            "block_id": "block-1",
        }
    )
    variant = SampleVariant.from_mapping(
        {
            "variant_id": "variant-1",
            "document_id": "srcdoc_runtime",
            "collection_id": "col_source",
            "domain_profile": "core_neutral",
            "variant_label": "Sample A",
            "host_material_system": {"name": "Alloy A"},
            "composition": "A-1B",
            "variable_axis_type": "temperature",
            "variable_value": 600,
            "process_context": {"temperature_c": 600},
            "profile_payload": {"source": "table"},
            "structure_feature_ids": ["feature-1"],
            "source_anchor_ids": ["anchor-1"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        }
    )
    condition = DomainTestCondition.from_mapping(
        {
            "test_condition_id": "condition-1",
            "document_id": "srcdoc_runtime",
            "collection_id": "col_source",
            "domain_profile": "core_neutral",
            "property_type": "strength",
            "template_type": "tensile",
            "scope_level": "variant",
            "condition_payload": {"temperature_c": 25},
            "condition_completeness": "complete",
            "missing_fields": [],
            "evidence_anchor_ids": ["anchor-1"],
            "confidence": 0.8,
            "epistemic_status": "directly_observed",
        }
    )
    baseline = BaselineReference.from_mapping(
        {
            "baseline_id": "baseline-1",
            "document_id": "srcdoc_runtime",
            "collection_id": "col_source",
            "domain_profile": "core_neutral",
            "variant_id": "variant-1",
            "baseline_type": "control",
            "baseline_label": "Untreated",
            "baseline_scope": "document",
            "evidence_anchor_ids": ["anchor-1"],
            "confidence": 0.8,
            "epistemic_status": "directly_observed",
        }
    )
    observation = CharacterizationObservation.from_mapping(
        {
            "observation_id": "observation-1",
            "document_id": "srcdoc_runtime",
            "collection_id": "col_source",
            "variant_id": "variant-1",
            "characterization_type": "SEM",
            "observation_text": "Dense grains",
            "observed_value": 10,
            "observed_unit": "um",
            "condition_context": {"mode": "secondary_electron"},
            "evidence_anchor_ids": ["anchor-1"],
            "confidence": 0.85,
            "epistemic_status": "directly_observed",
        }
    )
    feature = StructureFeature.from_mapping(
        {
            "feature_id": "feature-1",
            "document_id": "srcdoc_runtime",
            "collection_id": "col_source",
            "variant_id": "variant-1",
            "feature_type": "grain_size",
            "feature_value": 10,
            "feature_unit": "um",
            "qualitative_descriptor": "fine",
            "source_observation_ids": ["observation-1"],
            "confidence": 0.8,
            "epistemic_status": "normalized_from_evidence",
        }
    )
    return PaperFactSet(
        paper_facts_ready=True,
        document_profiles=(
            DocumentProfile.from_mapping(
                {
                    "document_id": "srcdoc_runtime",
                    "collection_id": "col_source",
                    "title": title,
                    "source_filename": "paper.pdf",
                    "doc_type": "experimental",
                    "parsing_warnings": ["synthetic"],
                    "confidence": 0.95,
                }
            ),
        ),
        evidence_anchors=(anchor,),
        method_facts=(
            MethodFact.from_mapping(
                {
                    "method_id": "method-1",
                    "document_id": "srcdoc_runtime",
                    "collection_id": "col_source",
                    "domain_profile": "core_neutral",
                    "method_role": "characterization",
                    "method_name": "SEM",
                    "method_payload": {"voltage_kv": 10},
                    "evidence_anchor_ids": ["anchor-1"],
                    "confidence": 0.9,
                    "epistemic_status": "directly_observed",
                }
            ),
        ),
        sample_variants=(variant,),
        test_conditions=(condition,),
        baseline_references=(baseline,),
        measurement_results=(
            MeasurementResult.from_mapping(
                {
                    "result_id": "result-1",
                    "document_id": "srcdoc_runtime",
                    "collection_id": "col_source",
                    "domain_profile": "core_neutral",
                    "variant_id": "variant-1",
                    "property_normalized": "strength",
                    "result_type": "scalar",
                    "claim_scope": "variant",
                    "value_payload": {"value": 100},
                    "unit": "MPa",
                    "test_condition_id": "condition-1",
                    "baseline_id": "baseline-1",
                    "structure_feature_ids": ["feature-1"],
                    "characterization_observation_ids": ["observation-1"],
                    "evidence_anchor_ids": ["anchor-1"],
                    "traceability_status": "direct",
                    "result_source_type": "text",
                    "epistemic_status": "normalized_from_evidence",
                }
            ),
        ),
        characterization_observations=(observation,),
        structure_features=(feature,),
    )


def test_paper_fact_repository_round_trips_build_and_document_lineage(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_paper_facts")
    builds.add_task(task, build_id="build_paper_facts")
    source_repository.replace_collection_artifacts(
        "col_source", "build_paper_facts", _artifacts()
    )
    expected = _paper_facts()

    repository.replace_document_profiles(
        "col_source", "build_paper_facts", expected.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_paper_facts", expected)

    assert repository.read("col_source") == PaperFactSet()
    assert repository.read("col_source", build_id="build_paper_facts") == expected
    with repository.session_factory() as session:
        row = session.scalar(select(PaperFactDocumentProfile))
        assert row is not None
        assert row.document_version_id.startswith("docver_")
        assert row.source_document_id == "srcdoc_runtime"

    _finish(builds, task, success=True)
    assert repository.read("col_source") == expected


def test_failed_paper_fact_build_cannot_replace_active_facts(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    first_task = _task("task_facts_first")
    builds.add_task(first_task, build_id="build_facts_first")
    source_repository.replace_collection_artifacts(
        "col_source", "build_facts_first", _artifacts("First")
    )
    first = _paper_facts("First")
    repository.replace_document_profiles(
        "col_source", "build_facts_first", first.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_facts_first", first)
    _finish(builds, first_task, success=True)

    failed_task = _task("task_facts_failed")
    builds.add_task(failed_task, build_id="build_facts_failed")
    source_repository.replace_collection_artifacts(
        "col_source", "build_facts_failed", _artifacts("Failed")
    )
    failed = _paper_facts("Failed")
    repository.replace_document_profiles(
        "col_source", "build_facts_failed", failed.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_facts_failed", failed)
    _finish(builds, failed_task, success=False)

    assert repository.read("col_source") == first
    assert repository.read("col_source", build_id="build_facts_failed") == failed


def test_paper_fact_repository_preserves_entity_and_link_order(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_order")
    builds.add_task(task, build_id="build_facts_order")
    source_repository.replace_collection_artifacts(
        "col_source", "build_facts_order", _artifacts()
    )
    facts = _paper_facts()
    anchor_1 = facts.evidence_anchors[0]
    anchor_2 = replace(anchor_1, anchor_id="anchor-2", quote="Second anchor")
    observation_1 = facts.characterization_observations[0]
    observation_2 = replace(
        observation_1,
        observation_id="observation-2",
        observation_text="Second observation",
    )
    feature_1 = facts.structure_features[0]
    feature_2 = replace(
        feature_1,
        feature_id="feature-2",
        source_observation_ids=("observation-2", "observation-1"),
    )
    ordered = replace(
        facts,
        evidence_anchors=(anchor_2, anchor_1),
        method_facts=(
            replace(
                facts.method_facts[0],
                evidence_anchor_ids=("anchor-2", "anchor-1"),
            ),
        ),
        sample_variants=(
            replace(
                facts.sample_variants[0],
                structure_feature_ids=("feature-2", "feature-1"),
                source_anchor_ids=("anchor-2", "anchor-1"),
            ),
        ),
        test_conditions=(
            replace(
                facts.test_conditions[0],
                evidence_anchor_ids=("anchor-2", "anchor-1"),
            ),
        ),
        baseline_references=(
            replace(
                facts.baseline_references[0],
                evidence_anchor_ids=("anchor-2", "anchor-1"),
            ),
        ),
        characterization_observations=(
            replace(
                observation_2,
                evidence_anchor_ids=("anchor-2", "anchor-1"),
            ),
            replace(
                observation_1,
                evidence_anchor_ids=("anchor-1", "anchor-2"),
            ),
        ),
        structure_features=(feature_2, feature_1),
        measurement_results=(
            replace(
                facts.measurement_results[0],
                structure_feature_ids=("feature-2", "feature-1"),
                characterization_observation_ids=(
                    "observation-2",
                    "observation-1",
                ),
                evidence_anchor_ids=("anchor-2", "anchor-1"),
            ),
        ),
    )

    repository.replace_document_profiles(
        "col_source", "build_facts_order", ordered.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_facts_order", ordered)

    assert repository.read("col_source", build_id="build_facts_order") == ordered


def test_paper_fact_replacement_is_atomic_and_keeps_profiles_separate(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_replace")
    builds.add_task(task, build_id="build_facts_replace")
    source_repository.replace_collection_artifacts(
        "col_source", "build_facts_replace", _artifacts()
    )
    original = _paper_facts("Original profile")
    repository.replace_document_profiles(
        "col_source", "build_facts_replace", original.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_facts_replace", original)

    invalid = replace(
        original,
        method_facts=(
            replace(
                original.method_facts[0],
                evidence_anchor_ids=("missing-anchor",),
            ),
        ),
    )
    with pytest.raises(IntegrityError):
        repository.replace_paper_facts("col_source", "build_facts_replace", invalid)
    assert repository.read("col_source", build_id="build_facts_replace") == original

    replacement = PaperFactSet(paper_facts_ready=True)
    repository.replace_paper_facts("col_source", "build_facts_replace", replacement)
    assert repository.read("col_source", build_id="build_facts_replace") == replace(
        replacement, document_profiles=original.document_profiles
    )


def test_paper_fact_repository_rejects_wrong_source_lineage_and_completed_builds(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_lineage")
    builds.add_task(task, build_id="build_facts_lineage")
    source_repository.replace_collection_artifacts(
        "col_source", "build_facts_lineage", _artifacts()
    )
    facts = _paper_facts()

    missing_source = replace(
        facts,
        method_facts=(replace(facts.method_facts[0], document_id="missing-document"),),
    )
    with pytest.raises(FileNotFoundError, match="source document not found"):
        repository.replace_paper_facts(
            "col_source", "build_facts_lineage", missing_source
        )
    mismatched_collection = replace(
        facts,
        method_facts=(replace(facts.method_facts[0], collection_id="col_other"),),
    )
    with pytest.raises(ValueError, match="paper fact collection mismatch"):
        repository.replace_paper_facts(
            "col_source", "build_facts_lineage", mismatched_collection
        )
    with pytest.raises(FileNotFoundError, match="collection build not found"):
        repository.replace_paper_facts("col_other", "build_facts_lineage", facts)

    repository.replace_document_profiles(
        "col_source", "build_facts_lineage", facts.document_profiles
    )
    repository.replace_paper_facts("col_source", "build_facts_lineage", facts)
    _finish(builds, task, success=True)

    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace_document_profiles(
            "col_source", "build_facts_lineage", facts.document_profiles
        )
    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace_paper_facts("col_source", "build_facts_lineage", facts)
    assert repository.read("col_source") == facts


def test_postgresql_enforces_paper_fact_contract() -> None:
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
                "user_id": "user_source",
                "email": "source@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
            }
        )
        collections = PostgresCollectionRepository(sessions)
        collections.add_collection(
            CollectionRecord(
                collection_id="col_source",
                owner_user_id="user_source",
                name="Source collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        collections.add_collection_import(
            _collection_import("stored-paper.pdf"), updated_at=NOW
        )
        source_repository = PostgresSourceArtifactRepository(sessions)
        builds = PostgresBuildRepository(sessions)
        repository = PostgresPaperFactRepository(sessions)
        task = _task("task_facts_postgresql")
        builds.add_task(task, build_id="build_facts_postgresql")
        source_repository.replace_collection_artifacts(
            "col_source", "build_facts_postgresql", _real_shape_artifacts()
        )
        facts = _paper_facts()
        facts = replace(
            facts,
            document_profiles=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.document_profiles
            ),
            evidence_anchors=tuple(
                replace(
                    item,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    block_id=REAL_SOURCE_BLOCK_ID,
                    figure_or_table=REAL_SOURCE_TABLE_ID,
                )
                for item in facts.evidence_anchors
            ),
            method_facts=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.method_facts
            ),
            sample_variants=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.sample_variants
            ),
            test_conditions=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.test_conditions
            ),
            baseline_references=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.baseline_references
            ),
            measurement_results=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.measurement_results
            ),
            characterization_observations=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.characterization_observations
            ),
            structure_features=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.structure_features
            ),
        )

        repository.replace_document_profiles(
            "col_source", "build_facts_postgresql", facts.document_profiles
        )
        repository.replace_paper_facts("col_source", "build_facts_postgresql", facts)
        assert repository.read("col_source", build_id="build_facts_postgresql") == facts

        invalid = replace(
            facts,
            method_facts=(
                replace(
                    facts.method_facts[0],
                    evidence_anchor_ids=("missing-anchor",),
                ),
            ),
        )
        with pytest.raises(IntegrityError):
            repository.replace_paper_facts(
                "col_source", "build_facts_postgresql", invalid
            )
        assert repository.read("col_source", build_id="build_facts_postgresql") == facts

        _finish(builds, task, success=True)
        with pytest.raises(ValueError, match="collection build is not writable"):
            repository.replace_paper_facts(
                "col_source", "build_facts_postgresql", facts
            )
        assert repository.read("col_source") == facts
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE collections CASCADE"))
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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
from infra.persistence.postgres.models.paper_fact import PaperFactDocumentProfile
from infra.persistence.postgres.paper_fact_repository import PostgresPaperFactRepository
from tests.integration.persistence.test_postgres_source_artifacts import (
    REAL_SOURCE_BLOCK_ID,
    REAL_SOURCE_DOCUMENT_ID,
    REAL_SOURCE_TABLE_ID,
    _artifacts,
    _finish,
    _real_shape_artifacts,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio


def _paper_facts(title: str = "Profiled paper") -> PaperFactSet:
    anchor = EvidenceAnchor.from_mapping(
        {
            "anchor_id": "anchor-1",
            "document_id": "srcdoc_runtime",
            "source_kind": "block",
            "source_ref": "block-1",
            "source_type": "text",
            "page": 1,
            "quote": "Result",
            "deep_link": "#block-1",
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


async def test_paper_fact_repository_round_trips_build_and_document_lineage(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_paper_facts")
    await builds.add_task(task, build_id="build_paper_facts")
    await source_repository.replace_collection_documents(
        "col_source", "build_paper_facts", _artifacts()
    )
    expected = _paper_facts()

    await repository.replace_document_profiles(
        "col_source", "build_paper_facts", expected.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_paper_facts", expected
    )

    assert await repository.read("col_source") == PaperFactSet()
    assert await repository.read(
        "col_source", build_id="build_paper_facts"
    ) == expected
    async with repository.session_factory() as session:
        row = await session.scalar(select(PaperFactDocumentProfile))
        assert row is not None
        assert row.document_version_id.startswith("docver_")
        assert row.source_document_id == "srcdoc_runtime"

    await _finish(builds, task, success=True)
    assert await repository.read("col_source") == expected


async def test_failed_paper_fact_build_cannot_replace_active_facts(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    first_task = _task("task_facts_first")
    await builds.add_task(first_task, build_id="build_facts_first")
    await source_repository.replace_collection_documents(
        "col_source", "build_facts_first", _artifacts("First")
    )
    first = _paper_facts("First")
    await repository.replace_document_profiles(
        "col_source", "build_facts_first", first.document_profiles
    )
    await repository.replace_paper_facts("col_source", "build_facts_first", first)
    await _finish(builds, first_task, success=True)

    failed_task = _task("task_facts_failed")
    await builds.add_task(failed_task, build_id="build_facts_failed")
    await source_repository.replace_collection_documents(
        "col_source", "build_facts_failed", _artifacts("Failed")
    )
    failed = _paper_facts("Failed")
    await repository.replace_document_profiles(
        "col_source", "build_facts_failed", failed.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_facts_failed", failed
    )
    await _finish(builds, failed_task, success=False)

    assert await repository.read("col_source") == first
    assert await repository.read(
        "col_source", build_id="build_facts_failed"
    ) == failed


async def test_paper_fact_repository_preserves_entity_and_link_order(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_order")
    await builds.add_task(task, build_id="build_facts_order")
    await source_repository.replace_collection_documents(
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

    await repository.replace_document_profiles(
        "col_source", "build_facts_order", ordered.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_facts_order", ordered
    )

    assert await repository.read(
        "col_source", build_id="build_facts_order"
    ) == ordered


async def test_paper_fact_replacement_is_atomic_and_keeps_profiles_separate(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_replace")
    await builds.add_task(task, build_id="build_facts_replace")
    await source_repository.replace_collection_documents(
        "col_source", "build_facts_replace", _artifacts()
    )
    original = _paper_facts("Original profile")
    await repository.replace_document_profiles(
        "col_source", "build_facts_replace", original.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_facts_replace", original
    )

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
        await repository.replace_paper_facts(
            "col_source", "build_facts_replace", invalid
        )
    assert await repository.read(
        "col_source", build_id="build_facts_replace"
    ) == original

    replacement = PaperFactSet(paper_facts_ready=True)
    await repository.replace_paper_facts(
        "col_source", "build_facts_replace", replacement
    )
    assert await repository.read(
        "col_source", build_id="build_facts_replace"
    ) == replace(
        replacement, document_profiles=original.document_profiles
    )


async def test_paper_fact_repository_rejects_wrong_source_lineage_and_completed_builds(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresPaperFactRepository(source_repository.session_factory)
    task = _task("task_facts_lineage")
    await builds.add_task(task, build_id="build_facts_lineage")
    await source_repository.replace_collection_documents(
        "col_source", "build_facts_lineage", _artifacts()
    )
    facts = _paper_facts()

    missing_source = replace(
        facts,
        method_facts=(replace(facts.method_facts[0], document_id="missing-document"),),
    )
    with pytest.raises(FileNotFoundError, match="source document not found"):
        await repository.replace_paper_facts(
            "col_source", "build_facts_lineage", missing_source
        )
    mismatched_collection = replace(
        facts,
        method_facts=(replace(facts.method_facts[0], collection_id="col_other"),),
    )
    with pytest.raises(ValueError, match="paper fact collection mismatch"):
        await repository.replace_paper_facts(
            "col_source", "build_facts_lineage", mismatched_collection
        )
    with pytest.raises(FileNotFoundError, match="collection build not found"):
        await repository.replace_paper_facts(
            "col_other", "build_facts_lineage", facts
        )

    await repository.replace_document_profiles(
        "col_source", "build_facts_lineage", facts.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_facts_lineage", facts
    )
    await _finish(builds, task, success=True)

    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_document_profiles(
            "col_source", "build_facts_lineage", facts.document_profiles
        )
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_paper_facts(
            "col_source", "build_facts_lineage", facts
        )
    assert await repository.read("col_source") == facts


async def test_postgresql_enforces_paper_fact_contract(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    sessions = source_repository.session_factory
    repository = PostgresPaperFactRepository(sessions)
    task = _task("task_facts_postgresql")
    await builds.add_task(task, build_id="build_facts_postgresql")
    await source_repository.replace_collection_documents(
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
                source_kind="block",
                source_ref=REAL_SOURCE_BLOCK_ID,
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

    await repository.replace_document_profiles(
        "col_source", "build_facts_postgresql", facts.document_profiles
    )
    await repository.replace_paper_facts(
        "col_source", "build_facts_postgresql", facts
    )
    assert await repository.read(
        "col_source", build_id="build_facts_postgresql"
    ) == facts

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
        await repository.replace_paper_facts(
            "col_source", "build_facts_postgresql", invalid
        )
    assert await repository.read(
        "col_source", build_id="build_facts_postgresql"
    ) == facts

    await _finish(builds, task, success=True)
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_paper_facts(
            "col_source", "build_facts_postgresql", facts
        )
    assert await repository.read("col_source") == facts

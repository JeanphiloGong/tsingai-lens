from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from application.core.objectives.analysis import experiment_analysis_writer
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    ReportedInterpretation,
    SourceReference,
)
from domain.source import Collection, Document
from infra.persistence import database
from repositories.auth_repository import AuthRepository, AuthUserRecord
from repositories.collection_repository import (
    CollectionRepository,
    StoredCollection,
    StoredDocument,
)
from repositories.paper_experiment_repository import (
    PaperExperimentRepository,
)
from exceptions import ResourceConflictException
from sqlalchemy.exc import IntegrityError
from tests.unit.application.test_experiment_analysis_writer import (
    _physical_split_experiment,
)

pytestmark = pytest.mark.anyio


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


@pytest.fixture
async def paper_experiment_repository(postgres_session_factory):
    auth = AuthRepository()
    await auth.add_user(
        AuthUserRecord(
            user_id="experiment-owner",
            email="experiment-owner@example.test",
            display_name=None,
            password_hash="synthetic-password-hash",
            created_at=NOW,
        )
    )
    collections = CollectionRepository()
    collection = StoredCollection(
        collection=Collection(
            collection_id="experiment-collection",
            owner_user_id="experiment-owner",
            name="Experiment collection",
            description=None,
            status="idle",
        ),
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )
    await collections.add_collection(collection)
    await collections.add_documents(
        collection.collection.collection_id,
        (
            StoredDocument(
                document=Document(
                    document_id="paper-experiment-doc",
                    original_filename="paper.pdf",
                    sha256="a" * 64,
                    media_type="application/pdf",
                    status="ready",
                    size_bytes=10,
                ),
                stored_filename="paper.pdf",
                storage_key="experiment-collection/paper.pdf",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        ),
        updated_at=NOW.isoformat(),
    )
    return PaperExperimentRepository()


async def test_source_only_batch_rolls_back_every_revision_on_write_failure(
    paper_experiment_repository,
    postgres_session_factory,
    monkeypatch,
):
    repository = paper_experiment_repository
    experiment_analysis_writer.PaperExperimentRepo = repository
    experiment_analysis_writer.ExperimentAnalysisRepo = object()
    writer = experiment_analysis_writer
    output = _physical_split_experiment("paper-experiment-doc", distinct_boundary=True)
    add_revision = repository.add_revision
    calls = 0

    async def fail_second(db, revision, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second revision failed")
        return await add_revision(db, revision, **kwargs)

    monkeypatch.setattr(repository, "add_revision", fail_second)
    with pytest.raises(RuntimeError, match="second revision failed"):
        async with postgres_session_factory() as db, db.begin():
            await writer.write_paper_experiment_revisions(
                experiment_outputs=(output,),
                db=db,
            )
    assert calls == 2
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await repository.list_latest_for_document(db, "paper-experiment-doc") == ()
        )


async def test_source_only_concurrent_saves_without_objective_are_idempotent(
    paper_experiment_repository,
    postgres_session_factory,
):
    repository = paper_experiment_repository
    experiment_analysis_writer.PaperExperimentRepo = repository
    experiment_analysis_writer.ExperimentAnalysisRepo = object()
    writer = experiment_analysis_writer
    output = _physical_split_experiment("paper-experiment-doc", distinct_boundary=True)

    async def save():
        async with postgres_session_factory() as db, db.begin():
            return await writer.write_paper_experiment_revisions(
                experiment_outputs=(output,),
                db=db,
                created_by="experiment-owner",
            )

    first, second = await asyncio.gather(save(), save())
    assert len(first.revisions) == len(second.revisions) == 2
    assert {item.revision_id for item in first.revisions} == {
        item.revision_id for item in second.revisions
    }
    assert first.selections == first.findings == ()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            len(await repository.list_latest_for_document(db, "paper-experiment-doc"))
            == 2
        )


def _revision(version: int = 1) -> PaperExperimentRevision:
    return PaperExperimentRevision(
        experiment_id="experiment-1",
        document_id="paper-experiment-doc",
        experiment_version=int(version or 0),
        source_fingerprint=f"prepared-{version}",
        label="Preheat tensile series",
        scope_description="NP and P150 under one tensile method",
        design_type="parallel",
        identity_status="identified",
        binding_status="bound",
        variants=(
            ExperimentalVariant(
                variant_key="np",
                variant_label="NP",
                binding_status="direct",
                identity_specificity="partial",
                missing_dimensions=("preheat temperature",),
                identity_evidence=("table-1", "methods-2"),
            ),
            ExperimentalVariant(
                variant_key="p150",
                variant_label="P150",
                binding_status="direct",
                identity_specificity="exact",
                identity_evidence=("table-1",),
            ),
        ),
        test_conditions=(
            ExperimentTestCondition(
                test_key="tensile",
                test_type="tensile test",
                binding_status="direct",
                protocol_specificity="partial",
                test_identity_status="identified",
                protocol_completeness="partial",
                missing_parameters=("strain rate",),
                method="uniaxial tensile test",
                standard="ASTM E8",
                outcome_scope=("elongation", "yield_strength"),
                binding_source_refs=(
                    SourceReference(
                        document_id="paper-experiment-doc",
                        source_fingerprint="prepared-1",
                        source_kind="block",
                        source_ref="methods-2",
                        quote="Tensile tests were performed ...",
                    ),
                ),
                protocol_evidence=("methods-2",),
            ),
        ),
        measurements=(
            ExperimentMeasurementResult(
                measurement_key="np-elongation",
                outcome="elongation",
                variant_key="np",
                test_key="tensile",
                value=72,
                unit="%",
                statistics=dict({"n": 5, "error": 2, "error_kind": "unknown"}),
                binding_status="direct",
            ),
            ExperimentMeasurementResult(
                measurement_key="p150-elongation",
                outcome="elongation",
                variant_key="p150",
                test_key="tensile",
                value=82,
                unit="%",
                statistics=dict({"n": 5, "error": 1, "error_kind": "unknown"}),
                binding_status="direct",
            ),
        ),
        comparisons=(
            ExperimentComparison(
                comparison_key="np-to-p150",
                baseline_variant_key="np",
                target_variant_key="p150",
                outcome="elongation",
                baseline_measurement_keys=("np-elongation",),
                target_measurement_keys=("p150-elongation",),
                direction="increase",
                status="ready",
                relation_status="direct",
            ),
        ),
        reported_interpretations=(
            ReportedInterpretation(
                statement="Preheating increased elongation in this series.",
                kind="result_summary",
                measurement_keys=("np-elongation", "p150-elongation"),
                comparison_keys=("np-to-p150",),
            ),
        ),
    )


async def test_repository_round_trips_complete_revision(
    paper_experiment_repository,
) -> None:
    expected = _revision()

    async with database.AsyncSessionLocal() as db, db.begin():
        stored = await paper_experiment_repository.add_revision(
            db, expected, created_by="test-agent", created_at=NOW
        )

    assert stored.revision_id > 0
    assert stored.revision == expected
    stored_variant = stored.revision.variants[0]
    assert stored_variant.identity_specificity == "partial"
    assert stored_variant.missing_dimensions == ("preheat temperature",)
    assert stored_variant.identity_evidence == ("table-1", "methods-2")
    stored_test = stored.revision.test_conditions[0]
    assert stored_test.protocol_specificity == "partial"
    assert stored_test.test_identity_status == "identified"
    assert stored_test.protocol_completeness == "partial"
    assert stored_test.missing_parameters == ("strain rate",)
    assert stored_test.method == "uniaxial tensile test"
    assert stored_test.standard == "ASTM E8"
    assert stored_test.outcome_scope == ("elongation", "yield_strength")
    assert stored_test.protocol_evidence == ("methods-2",)
    assert len(stored_test.binding_source_refs) == 1
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.read_revision(db, "experiment-1", 1)
        ) == stored
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.read_revision_by_id(
                db, stored.revision_id
            )
        ) == stored


async def test_new_version_does_not_replace_old_revision(
    paper_experiment_repository,
) -> None:
    async with database.AsyncSessionLocal() as db, db.begin():
        first = await paper_experiment_repository.add_revision(
            db, _revision(), created_at=NOW
        )
    async with database.AsyncSessionLocal() as db, db.begin():
        second = await paper_experiment_repository.add_revision(
            db, _revision(2), created_at=NOW.replace(minute=1)
        )

    assert second.revision_id != first.revision_id
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.read_revision(db, "experiment-1", 1)
        ).revision == first.revision
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.read_latest_revision(db, "experiment-1")
        ).revision == second.revision


async def test_latest_revision_allocation_serializes_shared_write_transactions(
    paper_experiment_repository,
    postgres_session_factory,
) -> None:
    """The first revision must not race when two writers see an empty head."""

    async with database.AsyncSessionLocal() as first_db, first_db.begin():
        assert (
            await paper_experiment_repository.read_latest_revision(
                first_db, "experiment-concurrent"
            )
            is None
        )

        async def read_second_head():
            async with database.AsyncSessionLocal() as db, db.begin():
                return await paper_experiment_repository.read_latest_revision(
                    db, "experiment-concurrent"
                )

        task = asyncio.create_task(read_second_head())
        await asyncio.sleep(0.05)
        assert not task.done()

    assert await asyncio.wait_for(task, timeout=2) is None


async def test_document_identity_resolution_lock_is_shared_and_transaction_scoped(
    paper_experiment_repository,
    postgres_session_factory,
) -> None:
    """Rereads of one paper cannot resolve identities concurrently."""

    async with database.AsyncSessionLocal() as first_db, first_db.begin():
        await paper_experiment_repository.lock_document(
            first_db, "paper-experiment-doc"
        )

        async def acquire_second_lock():
            async with database.AsyncSessionLocal() as db, db.begin():
                await paper_experiment_repository.lock_document(
                    db, "paper-experiment-doc"
                )
                return True

        task = asyncio.create_task(acquire_second_lock())
        await asyncio.sleep(0.05)
        assert not task.done()

    assert await asyncio.wait_for(task, timeout=2) is True


async def test_same_version_is_idempotent_but_conflicting_version_is_rejected(
    paper_experiment_repository,
) -> None:
    async with database.AsyncSessionLocal() as db, db.begin():
        first = await paper_experiment_repository.add_revision(
            db, _revision(), created_at=NOW
        )
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.add_revision(
                db, _revision(), created_at=NOW
            )
            == first
        )

    conflicting = replace(_revision(), label="Changed after publication")
    with pytest.raises(ResourceConflictException) as rejected:
        async with database.AsyncSessionLocal() as db, db.begin():
            await paper_experiment_repository.add_revision(
                db, conflicting, created_at=NOW
            )

    assert rejected.value.code == 200204
    assert rejected.value.data["code"] == "paper_experiment_revision_immutable"
    assert rejected.value.data["experiment_id"] == "experiment-1"
    assert rejected.value.data["experiment_version"] == 1
    async with database.AsyncSessionLocal() as db:
        assert await paper_experiment_repository.read_revision(db, "experiment-1", 1) == first


async def test_concurrent_conflicting_versions_return_one_business_conflict(
    paper_experiment_repository, monkeypatch,
) -> None:
    ready = asyncio.Event()
    readers = 0

    async def save(revision):
        nonlocal readers
        async with database.AsyncSessionLocal() as db, db.begin():
            scalar = db.scalar

            async def read_before_either_insert(statement):
                nonlocal readers
                result = await scalar(statement)
                monkeypatch.setattr(db, "scalar", scalar)
                readers += 1
                if readers == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=5)
                return result

            monkeypatch.setattr(db, "scalar", read_before_either_insert)
            return await paper_experiment_repository.add_revision(db, revision, created_at=NOW)

    outcomes = await asyncio.gather(
        save(_revision()), save(replace(_revision(), label="Competing interpretation")),
        return_exceptions=True,
    )
    conflicts = [item for item in outcomes if isinstance(item, ResourceConflictException)]
    assert len(conflicts) == 1
    assert conflicts[0].code == 200204
    assert conflicts[0].data["code"] == "paper_experiment_revision_identity_conflict"
    assert conflicts[0].data["experiment_id"] == "experiment-1"
    saved = next(item for item in outcomes if not isinstance(item, Exception))
    async with database.AsyncSessionLocal() as db:
        assert await paper_experiment_repository.list_latest_for_document(db, "paper-experiment-doc") == (saved,)


async def test_unrelated_integrity_failure_propagates_and_rolls_back(
    paper_experiment_repository,
) -> None:
    with pytest.raises(IntegrityError):
        async with database.AsyncSessionLocal() as db, db.begin():
            await paper_experiment_repository.add_revision(
                db, replace(_revision(), document_id="missing-document"),
            )

    async with database.AsyncSessionLocal() as db:
        assert await paper_experiment_repository.list_latest_for_document(db, "paper-experiment-doc") == ()


async def test_invalid_domain_revision_does_not_create_experiment_head(
    paper_experiment_repository,
) -> None:
    revision = _revision()

    with pytest.raises(ValueError, match="variant outside"):
        invalid = replace(
            revision,
            measurements=(
                replace(revision.measurements[0], variant_key="missing"),
                *revision.measurements[1:],
            ),
        )
        async with database.AsyncSessionLocal() as db, db.begin():
            await paper_experiment_repository.add_revision(db, invalid, created_at=NOW)

    async with database.AsyncSessionLocal() as db, db.begin():
        assert (
            await paper_experiment_repository.read_revision(db, "experiment-1", 1)
        ) is None

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from application.repositories.auth_repository import AuthUserRecord
from application.repositories.paper_experiment_repository import (
    PaperExperimentRevisionConflictError,
)
from domain.core.paper_experiment import PaperExperimentRevision
from domain.source import Collection, Document
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.paper_experiment_repository import (
    PostgresPaperExperimentRepository,
)


pytestmark = pytest.mark.anyio


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


@pytest.fixture
async def paper_experiment_repository(postgres_session_factory):
    auth = PostgresAuthRepository(postgres_session_factory)
    await auth.add_user(
        AuthUserRecord(
            user_id="experiment-owner",
            email="experiment-owner@example.test",
            display_name=None,
            password_hash="synthetic-password-hash",
            created_at=NOW,
        )
    )
    collections = PostgresCollectionRepository(postgres_session_factory)
    collection = Collection.create(
        collection_id="experiment-collection",
        owner_user_id="experiment-owner",
        name="Experiment collection",
        description=None,
        now_iso=NOW.isoformat(),
    )
    await collections.add_collection(collection)
    await collections.add_documents(
        collection.collection_id,
        (
            Document(
                document_id="paper-experiment-doc",
                original_filename="paper.pdf",
                stored_filename="paper.pdf",
                storage_key="experiment-collection/paper.pdf",
                sha256="a" * 64,
                media_type="application/pdf",
                status="ready",
                size_bytes=10,
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        ),
        updated_at=NOW.isoformat(),
    )
    return PostgresPaperExperimentRepository(postgres_session_factory)


def _revision(version: int = 1) -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": "experiment-1",
            "document_id": "paper-experiment-doc",
            "experiment_version": version,
            "source_fingerprint": f"prepared-{version}",
            "label": "Preheat tensile series",
            "scope_description": "NP and P150 under one tensile method",
            "design_type": "parallel",
            "identity_status": "identified",
            "binding_status": "bound",
            "variants": [
                {
                    "variant_key": "np",
                    "variant_label": "NP",
                    "binding_status": "direct",
                },
                {
                    "variant_key": "p150",
                    "variant_label": "P150",
                    "binding_status": "direct",
                },
            ],
            "test_conditions": [
                {
                    "test_key": "tensile",
                    "test_type": "tensile test",
                    "binding_status": "direct",
                }
            ],
            "measurements": [
                {
                    "measurement_key": "np-elongation",
                    "variant_key": "np",
                    "test_key": "tensile",
                    "outcome": "elongation",
                    "value": 72,
                    "unit": "%",
                    "statistics": {"n": 5, "error": 2, "error_kind": "unknown"},
                    "binding_status": "direct",
                },
                {
                    "measurement_key": "p150-elongation",
                    "variant_key": "p150",
                    "test_key": "tensile",
                    "outcome": "elongation",
                    "value": 82,
                    "unit": "%",
                    "statistics": {"n": 5, "error": 1, "error_kind": "unknown"},
                    "binding_status": "direct",
                },
            ],
            "comparisons": [
                {
                    "comparison_key": "np-to-p150",
                    "baseline_variant_key": "np",
                    "target_variant_key": "p150",
                    "outcome": "elongation",
                    "baseline_measurement_keys": ["np-elongation"],
                    "target_measurement_keys": ["p150-elongation"],
                    "basis": "reported",
                    "direction": "increase",
                    "status": "ready",
                    "relation_status": "direct",
                }
            ],
            "reported_interpretations": [
                {
                    "statement": "Preheating increased elongation in this series.",
                    "kind": "result_summary",
                    "measurement_keys": ["np-elongation", "p150-elongation"],
                    "comparison_keys": ["np-to-p150"],
                }
            ],
        }
    )


async def test_repository_round_trips_complete_revision(
    paper_experiment_repository,
) -> None:
    expected = _revision()

    stored = await paper_experiment_repository.add_revision(
        expected,
        created_by="test-agent",
        created_at=NOW,
    )

    assert stored.revision_id > 0
    assert stored.revision == expected
    assert (
        await paper_experiment_repository.read_revision("experiment-1", 1)
    ) == stored
    assert (
        await paper_experiment_repository.read_revision_by_id(stored.revision_id)
    ) == stored


async def test_new_version_does_not_replace_old_revision(
    paper_experiment_repository,
) -> None:
    first = await paper_experiment_repository.add_revision(_revision(), created_at=NOW)
    second = await paper_experiment_repository.add_revision(
        _revision(2), created_at=NOW.replace(minute=1)
    )

    assert second.revision_id != first.revision_id
    assert (
        await paper_experiment_repository.read_revision("experiment-1", 1)
    ).revision == first.revision
    assert (
        await paper_experiment_repository.read_latest_revision("experiment-1")
    ).revision == second.revision


async def test_same_version_is_idempotent_but_conflicting_version_is_rejected(
    paper_experiment_repository,
) -> None:
    first = await paper_experiment_repository.add_revision(_revision(), created_at=NOW)
    assert await paper_experiment_repository.add_revision(_revision(), created_at=NOW) == first

    conflicting = replace(_revision(), label="Changed after publication")
    with pytest.raises(PaperExperimentRevisionConflictError):
        await paper_experiment_repository.add_revision(conflicting, created_at=NOW)


async def test_invalid_domain_revision_does_not_create_experiment_head(
    paper_experiment_repository,
) -> None:
    payload = _revision().to_record()
    payload["measurements"][0]["variant_key"] = "missing"

    with pytest.raises(ValueError, match="variant outside"):
        invalid = PaperExperimentRevision.from_mapping(payload)
        await paper_experiment_repository.add_revision(invalid, created_at=NOW)

    assert (
        await paper_experiment_repository.read_revision("experiment-1", 1)
    ) is None

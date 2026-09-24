from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.core.objectives.analysis.paper_experiment_reuse import (
    PaperExperimentReadRequest,
    PaperExperimentReuseService,
)
from application.repositories.paper_experiment_repository import (
    PaperExperimentRevisionConflictError,
    StoredPaperExperimentRevision,
)
from domain.core.paper_experiment import PaperExperimentRevision


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class MemoryPaperExperimentRepository:
    def __init__(self) -> None:
        self.records: list[StoredPaperExperimentRevision] = []
        self.next_id = 1

    async def add_revision(self, revision, *, created_by=None, created_at=None):
        for record in self.records:
            if (
                record.revision.experiment_id == revision.experiment_id
                and record.revision.experiment_version == revision.experiment_version
            ):
                if record.revision == revision:
                    return record
                raise PaperExperimentRevisionConflictError("conflicting revision")
        record = StoredPaperExperimentRevision(
            revision_id=self.next_id,
            revision=revision,
            created_at=created_at or NOW,
            created_by=created_by,
        )
        self.next_id += 1
        self.records.append(record)
        return record

    async def read_revision(self, experiment_id, experiment_version):
        return next(
            (
                item
                for item in self.records
                if item.revision.experiment_id == experiment_id
                and item.revision.experiment_version == experiment_version
            ),
            None,
        )

    async def read_revision_by_id(self, revision_id):
        return next((item for item in self.records if item.revision_id == revision_id), None)

    async def read_latest_revision(self, experiment_id):
        records = [
            item for item in self.records if item.revision.experiment_id == experiment_id
        ]
        return max(records, key=lambda item: item.revision.experiment_version, default=None)

    async def list_latest_for_document(self, document_id):
        records = [
            item for item in self.records if item.revision.document_id == document_id
        ]
        latest: dict[str, StoredPaperExperimentRevision] = {}
        for item in records:
            current = latest.get(item.revision.experiment_id)
            if current is None or item.revision.experiment_version > current.revision.experiment_version:
                latest[item.revision.experiment_id] = item
        return tuple(latest.values())


def _revision(version: int = 1, *, outcome: str = "elongation") -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": "exp-1",
            "document_id": "paper-1",
            "experiment_version": version,
            "source_fingerprint": f"source-{version}",
            "label": "Tensile series",
            "scope_description": "Two variants",
            "variants": [{"variant_key": "a", "variant_label": "A"}],
            "measurements": [
                {
                    "measurement_key": "m1",
                    "variant_key": "a",
                    "outcome": outcome,
                    "value": 72,
                }
            ],
        }
    )


@pytest.mark.anyio
async def test_reuses_existing_revision_when_requested_content_is_present():
    repository = MemoryPaperExperimentRepository()
    original = await repository.add_revision(_revision())
    service = PaperExperimentReuseService(repository)
    called = False

    def fail_builder(_existing, _version):
        nonlocal called
        called = True
        raise AssertionError("a sufficient revision must not be rebuilt")

    result = await service.read_or_reread(
        PaperExperimentReadRequest("paper-1", outcomes=("elongation",)),
        build_revision=fail_builder,
    )

    assert result.stored == original
    assert result.created_revision is False
    assert called is False


@pytest.mark.anyio
async def test_missing_context_creates_same_identity_successor_and_keeps_old_revision():
    repository = MemoryPaperExperimentRepository()
    original = await repository.add_revision(_revision())
    service = PaperExperimentReuseService(repository)

    def reread(existing, version):
        assert existing is not None
        assert existing.revision.experiment_id == "exp-1"
        return PaperExperimentRevision.from_mapping(
            {
                **_revision(version).to_record(),
                "source_fingerprint": "source-with-methods",
                "test_conditions": [
                    {
                        "test_key": "tensile",
                        "test_type": "tensile",
                        "parameters": [{"name": "temperature", "value": 293, "unit": "K"}],
                    }
                ],
            }
        )

    result = await service.read_or_reread(
        PaperExperimentReadRequest(
            "paper-1",
            outcomes=("elongation",),
            required_context_names=("temperature",),
        ),
        build_revision=reread,
    )

    assert result.created_revision is True
    assert result.reread_required is True
    assert result.stored.revision.experiment_id == original.revision.experiment_id
    assert result.stored.revision.experiment_version == 2
    assert (await repository.read_revision("exp-1", 1)).revision == original.revision


@pytest.mark.anyio
async def test_reread_cannot_switch_experiment_identity():
    repository = MemoryPaperExperimentRepository()
    await repository.add_revision(_revision())
    service = PaperExperimentReuseService(repository)

    def wrong_identity(_existing, version):
        return PaperExperimentRevision.from_mapping(
            {**_revision(version).to_record(), "experiment_id": "other"}
        )

    with pytest.raises(ValueError, match="preserve experiment identity"):
        await service.read_or_reread(
            PaperExperimentReadRequest("paper-1", outcomes=("missing",)),
            build_revision=wrong_identity,
        )

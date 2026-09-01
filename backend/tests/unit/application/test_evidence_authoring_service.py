from __future__ import annotations

import pytest

from application.core.objectives.evidence_authoring_service import (
    EvidenceAuthoringService,
)
from domain.source import SourceBlock, SourceDocument
from infra.persistence.memory.source_artifact_repository import (
    MemorySourceArtifactRepository,
)
from tests.unit.services.test_evaluation_services import (
    _published_objective_repository,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _CollectionService:
    async def get_collection_for_user(
        self, collection_id: str, user_id: str
    ) -> dict:
        if collection_id != "col-gold" or user_id != "user-researcher":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


async def _service():
    objective_repository = await _published_objective_repository()
    source_repository = MemorySourceArtifactRepository()
    await source_repository.replace_document(
        "col-gold",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Temperature and strength",
            text="At 500 C, tensile strength increased to 620 MPa.",
            blocks=(
                SourceBlock(
                    block_id="block-7",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=(
                        "At 500 C, tensile strength increased to 620 MPa. "
                        "The specimens were tested along the build direction."
                    ),
                    block_order=7,
                    page=7,
                    heading_path="Results > Tensile properties",
                ),
            ),
        ),
    )
    return (
        EvidenceAuthoringService(
            collection_service=_CollectionService(),
            objective_repository=objective_repository,
            source_artifact_repository=source_repository,
        ),
        objective_repository,
        source_repository,
    )


def _draft(**overrides):
    draft = {
        "collection_id": "col-gold",
        "objective_id": "obj-1",
        "source_analysis_version": 1,
        "document_id": "doc-1",
        "source_kind": "text_window",
        "source_ref": "block-7",
        "source_excerpt": "At 500 C, tensile strength increased to 620 MPa.",
        "evidence_role": "direct_result",
        "changed_variables": (
            {
                "name": "temperature",
                "baseline_value": 400,
                "target_value": 500,
                "unit": "C",
            },
        ),
        "comparison": {
            "baseline_label": "400 C",
            "target_label": "500 C",
            "axis_names": ["temperature"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "tensile strength",
            "value": 620,
            "baseline_value": 580,
            "target_value": 620,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "At 500 C, tensile strength increased to 620 MPa.",
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {
            "material": [{"name": "alloy", "value": "Alloy A"}],
            "sample": [],
            "process": [],
            "test": [{"name": "orientation", "value": "build direction"}],
        },
        "supersedes_evidence_id": None,
        "authoring_note": "Checked against the Results paragraph.",
        "created_by_user_id": "user-researcher",
    }
    draft.update(overrides)
    return draft


async def test_creates_grounded_evidence_in_new_immutable_version() -> None:
    service, repository, _source_repository = await _service()

    result = await service.create_version(**_draft())

    assert result.analysis.analysis_version == 2
    assert result.evidence.analysis_version == 2
    assert result.evidence.origin == "human_authored"
    assert result.evidence.source_analysis_version == 1
    assert result.evidence.created_by_user_id == "user-researcher"
    assert result.evidence.source_ref == "block-7"
    assert result.evidence.page_numbers == (7,)
    assert result.evidence.supports_finding is True

    original, original_total = await repository.list_evidence(
        "col-gold", "obj-1", 1, offset=0, limit=20
    )
    current, current_total = await repository.list_evidence(
        "col-gold", "obj-1", 2, offset=0, limit=20
    )
    assert original_total == 1
    assert current_total == 2
    assert original[0].analysis_version == 1
    assert {item.evidence_id for item in current} == {
        "evidence-1",
        result.evidence.evidence_id,
    }
    old_finding = await repository.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    cloned_finding = await repository.read_finding(
        "col-gold", "obj-1", 2, "finding-1"
    )
    assert old_finding is not None and cloned_finding is not None
    assert old_finding.supporting_evidence_ids == ("evidence-1",)
    assert cloned_finding.supporting_evidence_ids == ("evidence-1",)


async def test_revision_creates_lineage_and_keeps_old_finding_valid() -> None:
    service, repository, _source_repository = await _service()

    result = await service.create_version(
        **_draft(
            supersedes_evidence_id="evidence-1",
            source_excerpt="At 500 C, tensile strength increased to 620 MPa.",
        )
    )

    assert result.evidence.evidence_id != "evidence-1"
    assert result.evidence.origin == "human_revised"
    assert result.evidence.supersedes_evidence_id == "evidence-1"
    records, total = await repository.list_evidence(
        "col-gold", "obj-1", 2, offset=0, limit=20
    )
    assert total == 2
    previous = next(item for item in records if item.evidence_id == "evidence-1")
    assert previous.superseded_by_evidence_id == result.evidence.evidence_id
    assert previous.supports_finding is True
    finding = await repository.read_finding("col-gold", "obj-1", 2, "finding-1")
    assert finding is not None
    finding.validate_sources(records, await repository.list_contributions("col-gold", "obj-1", 2))


async def test_revision_rejects_an_already_superseded_evidence_version() -> None:
    service, repository, _source_repository = await _service()

    first_revision = await service.create_version(
        **_draft(supersedes_evidence_id="evidence-1")
    )

    with pytest.raises(ValueError, match="no longer the current Source version"):
        await service.create_version(
            **_draft(
                source_analysis_version=2,
                supersedes_evidence_id="evidence-1",
            )
        )

    objective = await repository.read_objective("col-gold", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == first_revision.analysis.analysis_version


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"source_excerpt": "The paper never reports this invented result."},
            "excerpt is not contained",
        ),
        ({"source_ref": "block-missing"}, "Source was not found"),
        ({"document_id": "doc-outside"}, "analysis document scope"),
        (
            {"supersedes_evidence_id": "evidence-missing"},
            "revision Evidence was not found",
        ),
    ],
)
async def test_rejects_ungrounded_or_out_of_scope_drafts_without_publication(
    overrides: dict, message: str
) -> None:
    service, repository, _source_repository = await _service()

    with pytest.raises((FileNotFoundError, ValueError), match=message):
        await service.create_version(**_draft(**overrides))

    objective = await repository.read_objective("col-gold", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == 1


async def test_rejects_stale_version_and_cross_collection_user() -> None:
    service, repository, _source_repository = await _service()
    await service.create_version(**_draft())

    with pytest.raises(ValueError, match="source analysis version is stale"):
        await service.create_version(**_draft())
    with pytest.raises(FileNotFoundError, match="collection not found"):
        await service.create_version(
            **_draft(collection_id="col-other", created_by_user_id="user-other")
        )

    objective = await repository.read_objective("col-gold", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == 2

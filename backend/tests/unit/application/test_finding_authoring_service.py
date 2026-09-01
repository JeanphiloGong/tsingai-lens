from __future__ import annotations

import pytest

from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
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


def _service(repository) -> FindingAuthoringService:
    return FindingAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
    )


async def test_creates_new_manual_finding_version_from_published_evidence() -> None:
    repository = await _published_objective_repository()
    service = _service(repository)

    result = await service.create_version(
        collection_id="col-gold",
        objective_id="obj-1",
        source_analysis_version=1,
        statement="Higher temperature is associated with greater tensile strength.",
        assertion_strength="associative",
        supporting_evidence_ids=("evidence-1",),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("Only one paper has direct Evidence.",),
        parent_finding_id=None,
        abstention_reason=None,
        created_by_user_id="user-researcher",
    )

    assert result.analysis.analysis_version == 2
    assert result.analysis.origin == "hybrid"
    assert result.analysis.source_analysis_version == 1
    assert result.finding is not None
    assert result.finding.analysis_version == 2
    assert result.finding.origin == "human_authored"
    assert result.finding.source_analysis_version == 1
    assert result.finding.created_by_user_id == "user-researcher"
    assert result.finding.supporting_evidence_ids == ("evidence-1",)

    objective = await repository.read_objective("col-gold", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == 2
    original = await repository.read_finding("col-gold", "obj-1", 1, "finding-1")
    assert original is not None
    assert original.statement == "Higher temperature was associated with greater strength."
    assert original.analysis_version == 1
    authored = await repository.read_finding(
        "col-gold", "obj-1", 2, result.finding.finding_id
    )
    assert authored == result.finding
    cloned_evidence, total = await repository.list_evidence(
        "col-gold", "obj-1", 2, finding_id=result.finding.finding_id
    )
    assert total == 1
    assert cloned_evidence[0].analysis_version == 2
    assert cloned_evidence[0].source_ref == "block-7"


async def test_derives_hybrid_finding_without_mutating_parent() -> None:
    repository = await _published_objective_repository()
    service = _service(repository)

    result = await service.create_version(
        collection_id="col-gold",
        objective_id="obj-1",
        source_analysis_version=1,
        statement="Within the reported tensile test, higher temperature accompanies greater strength.",
        assertion_strength="associative",
        supporting_evidence_ids=("evidence-1",),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("Applies only to the reported material and test condition.",),
        parent_finding_id="finding-1",
        abstention_reason=None,
        created_by_user_id="user-researcher",
    )

    assert result.finding is not None
    assert result.finding.origin == "hybrid"
    assert result.finding.parent_finding_id == "finding-1"
    parent = await repository.read_finding("col-gold", "obj-1", 1, "finding-1")
    assert parent is not None
    assert parent.statement == "Higher temperature was associated with greater strength."
    version_two, total = await repository.list_findings(
        "col-gold", "obj-1", 2, offset=0, limit=20
    )
    assert total == 2
    assert {item.origin for item in version_two} == {"system_generated", "hybrid"}


async def test_rejects_stale_or_unknown_evidence_without_writing_a_version() -> None:
    repository = await _published_objective_repository()
    service = _service(repository)

    with pytest.raises(ValueError, match="Evidence was not found"):
        await service.create_version(
            collection_id="col-gold",
            objective_id="obj-1",
            source_analysis_version=1,
            statement="Unsupported draft.",
            assertion_strength="associative",
            supporting_evidence_ids=("evidence-missing",),
            contradicting_evidence_ids=(),
            context_evidence_ids=(),
            condition_boundary_evidence_ids=(),
            limitations=(),
            parent_finding_id=None,
            abstention_reason=None,
            created_by_user_id="user-researcher",
        )

    objective = await repository.read_objective("col-gold", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == 1

    await service.create_version(
        collection_id="col-gold",
        objective_id="obj-1",
        source_analysis_version=1,
        statement="Supported draft.",
        assertion_strength="associative",
        supporting_evidence_ids=("evidence-1",),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=(),
        parent_finding_id=None,
        abstention_reason=None,
        created_by_user_id="user-researcher",
    )

    with pytest.raises(ValueError, match="source analysis version is stale"):
        await service.create_version(
            collection_id="col-gold",
            objective_id="obj-1",
            source_analysis_version=1,
            statement="Stale draft.",
            assertion_strength="associative",
            supporting_evidence_ids=("evidence-1",),
            contradicting_evidence_ids=(),
            context_evidence_ids=(),
            condition_boundary_evidence_ids=(),
            limitations=(),
            parent_finding_id=None,
            abstention_reason=None,
            created_by_user_id="user-researcher",
        )


async def test_records_abstention_without_creating_placeholder_finding() -> None:
    repository = await _published_objective_repository()
    service = _service(repository)

    result = await service.create_version(
        collection_id="col-gold",
        objective_id="obj-1",
        source_analysis_version=1,
        statement=None,
        assertion_strength=None,
        supporting_evidence_ids=(),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("The reported test conditions are not comparable.",),
        parent_finding_id=None,
        abstention_reason="no_comparable_evidence",
        created_by_user_id="user-researcher",
    )

    assert result.finding is None
    assert result.analysis.analysis_version == 2
    assert result.analysis.abstention_reason == "no_comparable_evidence"
    assert result.analysis.created_by_user_id == "user-researcher"
    previous, previous_total = await repository.list_findings(
        "col-gold", "obj-1", 1, offset=0, limit=20
    )
    current, current_total = await repository.list_findings(
        "col-gold", "obj-1", 2, offset=0, limit=20
    )
    assert previous_total == current_total == 1
    assert previous[0].statement == current[0].statement
    assert current[0].analysis_version == 2

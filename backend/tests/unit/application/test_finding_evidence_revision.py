"""A researcher corrects a paper fact, then reassesses the conclusion using it."""

from dataclasses import replace

import pytest

from application.core.objectives.analysis_service import ObjectiveAnalysisService
from tests.unit.application.test_evidence_authoring_service import _draft, _service
from tests.unit.application.test_finding_authoring_service import _service as finding_service


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_corrected_fact_requires_finding_review_and_current_evidence():
    author, repository, _ = await _service()
    reader = ObjectiveAnalysisService(
        objective_repository=repository,
        evidence_analysis_service=None,
        objective_input_service=None,
        document_profile_service=None,
    )
    original = await reader.get_finding("col-gold", "obj-1", "finding-1")
    revision = await author.create_version(**_draft(supersedes_evidence_id="evidence-1"))
    current_id = revision.evidence.evidence_id
    assert revision.affected_finding_ids == ("finding-1",)
    detail = await reader.get_finding("col-gold", "obj-1", "finding-1")
    assert detail["finding"]["statement"] == original["finding"]["statement"]
    assert detail["evidence_review"] == {
        "needs_review": True,
        "evidence_replacements": {"evidence-1": current_id},
    }
    listing = await reader.list_findings("col-gold", "obj-1", limit=1)
    assert listing["evidence_reviews"]["finding-1"] == detail["evidence_review"]
    historical = await repository.read_finding("col-gold", "obj-1", 1, "finding-1")
    assert historical.to_record() == original["finding"]
    assert not original["evidence_review"]["needs_review"]
    evidence = await reader.list_evidence("col-gold", "obj-1")
    assert {item["evidence_id"]: item["eligible_for_finding_authoring"] for item in evidence["items"]} == {
        "evidence-1": False, current_id: True,
    }

    command = dict(
        collection_id="col-gold", objective_id="obj-1", source_analysis_version=2,
        statement="Higher temperature was associated with greater tensile strength in this test.",
        assertion_strength="associative", supporting_evidence_ids=("evidence-1",),
        contradicting_evidence_ids=(), context_evidence_ids=(), condition_boundary_evidence_ids=(),
        limitations=("Only the reported material and test condition were compared.",),
        parent_finding_id="finding-1", abstention_reason=None,
        created_by_user_id="user-researcher",
    )
    with pytest.raises(ValueError, match="not eligible"):
        await finding_service(repository).create_version(**command)
    assert (await repository.read_objective("col-gold", "obj-1")).published_analysis_version == 2
    command["supporting_evidence_ids"] = (current_id,)
    result = await finding_service(repository).create_version(**command)
    assert result.finding.parent_finding_id == "finding-1"
    assert result.finding.supporting_evidence_ids == (current_id,)
    reopened = await reader.get_finding("col-gold", "obj-1", result.finding.finding_id)
    assert not reopened["evidence_review"]["needs_review"]
    with pytest.raises(ValueError, match="stale"):
        await finding_service(repository).create_version(**command)

    # A later fact correction affects both versions, including indirect lineage.
    latest = await author.create_version(**_draft(
        source_analysis_version=3, supersedes_evidence_id=current_id,
    ))
    assert set(latest.affected_finding_ids) == {"finding-1", result.finding.finding_id}
    reread = await reader.list_findings("col-gold", "obj-1")
    assert reread["evidence_reviews"]["finding-1"]["evidence_replacements"] == {
        "evidence-1": latest.evidence.evidence_id,
    }


async def test_review_tracks_context_and_contradictions_without_mutating_finding():
    _, repository, _ = await _service()
    finding = await repository.read_finding("col-gold", "obj-1", 1, "finding-1")
    evidence, _ = await repository.list_evidence("col-gold", "obj-1", 1)
    contribution = replace(
        finding.paper_contributions[0], contradicting_evidence_ids=("counter",),
        context_evidence_ids=("context",), condition_boundary_evidence_ids=("context",),
    )
    finding = replace(finding, paper_contributions=(contribution,))
    records = {item.evidence_id: item for item in (
        evidence[0],
        replace(evidence[0], evidence_id="counter", superseded_by_evidence_id="counter-new"),
        replace(evidence[0], evidence_id="counter-new"),
        replace(evidence[0], evidence_id="context", superseded_by_evidence_id="context-new"),
        replace(evidence[0], evidence_id="context-new"),
    )}
    before = finding.to_record()
    assert finding.evidence_replacements(records) == {
        "counter": "counter-new", "context": "context-new",
    }
    assert finding.to_record() == before
    records.pop("context-new")
    assert finding.evidence_replacements(records)["context"] is None
    records["counter-new"] = replace(records["counter-new"], superseded_by_evidence_id="counter")
    assert finding.evidence_replacements(records)["counter"] is None

from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

import pytest

from application.core.objectives.agent_analysis_service import (
    AgentObjectiveAnalysisService,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    ResearchObjective,
)
from domain.source import SourceBlock, SourceDocument
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
from infra.persistence.memory.source_artifact_repository import (
    MemorySourceArtifactRepository,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_SOURCE_TEXT = (
    "For Ti-6Al-4V, increasing laser power from 180 W to 220 W reduced "
    "porosity from 1.8% to 0.7%."
)


class _CollectionService:
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        if collection_id != "col-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SimpleNamespace:
        if collection_id != "col-1" or document_id != "doc-1":
            raise FileNotFoundError("document not found")
        return SimpleNamespace(
            document_id=document_id,
            status="ready",
            preparation_fingerprint="prepared-doc-1",
        )


async def _service(
    *,
    confirmation_status: str = "confirmed",
    objective_repository: MemoryObjectiveRepository | None = None,
) -> tuple[AgentObjectiveAnalysisService, MemoryObjectiveRepository]:
    objective_repository = objective_repository or MemoryObjectiveRepository()
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "question": "How does laser power affect porosity?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
            "seed_document_ids": ["doc-1"],
            "confidence": 0.9,
            "rank": 1,
            "confirmation_status": confirmation_status,
        }
    )
    await objective_repository.replace(
        "col-1",
        ObjectiveFactSet(
            research_objectives_ready=False,
            research_objectives=(objective,),
        ),
    )
    source_repository = MemorySourceArtifactRepository()
    await source_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Laser power and porosity",
            text=_SOURCE_TEXT,
            blocks=(
                SourceBlock(
                    block_id="block-results",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=_SOURCE_TEXT,
                    block_order=1,
                    page=8,
                    heading_path="Results > Porosity",
                ),
            ),
        ),
    )
    return (
        AgentObjectiveAnalysisService(
            collection_service=_CollectionService(),
            objective_repository=objective_repository,
            source_artifact_repository=source_repository,
        ),
        objective_repository,
    )


def _paper_summary() -> dict:
    return {
        "document_id": "doc-1",
        "relevance": "high",
        "paper_role": "primary_experiment",
        "contribution_summary": (
            "Reports a laser-power comparison with source-backed porosity values."
        ),
        "confidence": 0.9,
    }


def _evidence_draft(**overrides) -> dict:
    draft = {
        "draft_id": "porosity-result",
        "document_id": "doc-1",
        "source_kind": "text_window",
        "source_ref": "block-results",
        "source_excerpt": _SOURCE_TEXT,
        "source_digest": sha256(_SOURCE_TEXT.encode("utf-8")).hexdigest(),
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "laser power",
                "baseline_value": 180,
                "target_value": 220,
                "unit": "W",
            }
        ],
        "comparison": {
            "baseline_label": "180 W",
            "target_label": "220 W",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "porosity",
            "baseline_value": 1.8,
            "target_value": 0.7,
            "unit": "%",
            "direction": "decrease",
            "result_text": _SOURCE_TEXT,
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {
            "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
            "sample": [],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [{"name": "measurement", "value": "porosity"}],
        },
        "confidence": 0.88,
        "authoring_note": "Agent inspected the complete Results Source.",
    }
    draft.update(overrides)
    return draft


async def test_publishes_agent_authored_evidence_without_automatic_analysis() -> None:
    service, repository = await _service()

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-agent-analysis",
    )

    assert result.analysis.status == "succeeded"
    assert result.analysis.analysis_version == 1
    assert result.analysis.origin == "agent_authored"
    assert result.analysis.created_by_user_id == "user-1"
    assert result.analysis.created_by_tool_call_id == "call-agent-analysis"
    assert result.analysis.pipeline_version == "agent-objective-analysis.v1"
    assert result.analysis.prompt_versions == {
        "agent_objective_analysis": "research-agent-v13"
    }
    assert len(result.evidence_records) == 1
    evidence = result.evidence_records[0]
    assert evidence.origin == "agent_authored"
    assert evidence.source_analysis_version is None
    assert evidence.created_by_tool_call_id == "call-agent-analysis"
    assert evidence.page_numbers == (8,)
    assert evidence.supports_finding is True
    assert result.contributions[0].evidence_disposition == "comparable_evidence"
    assert result.findings == ()
    assert ObjectiveAnalysis.from_mapping(result.analysis.to_record()) == result.analysis
    assert ObjectiveEvidence.from_mapping(evidence.to_record()) == evidence

    objective = await repository.read_objective("col-1", "obj-1")
    assert objective is not None
    assert objective.confirmation_status == "confirmed"
    assert objective.published_analysis_version == 1
    persisted, total = await repository.list_evidence(
        "col-1", "obj-1", 1, offset=0, limit=20
    )
    assert total == 1
    assert persisted == result.evidence_records


async def test_approved_agent_analysis_can_publish_a_source_traceable_finding() -> None:
    analysis_service, repository = await _service(confirmation_status="candidate")

    analysis_result = await analysis_service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-agent-analysis",
    )
    evidence = analysis_result.evidence_records[0]

    finding_result = await FindingAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
    ).create_version(
        collection_id="col-1",
        objective_id="obj-1",
        source_analysis_version=analysis_result.analysis.analysis_version,
        statement=(
            "Within the reported Ti-6Al-4V LPBF conditions, increasing laser "
            "power from 180 W to 220 W was associated with lower porosity."
        ),
        assertion_strength="associative",
        supporting_evidence_ids=(evidence.evidence_id,),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("The conclusion is based on one reported experiment.",),
        parent_finding_id=None,
        abstention_reason=None,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-agent-finding",
    )

    objective = await repository.read_objective("col-1", "obj-1")
    assert objective is not None
    assert objective.confirmation_status == "confirmed"
    assert objective.published_analysis_version == 2
    assert finding_result.analysis.origin == "agent_authored"
    assert finding_result.analysis.source_analysis_version == 1
    assert finding_result.finding is not None
    assert finding_result.finding.origin == "agent_authored"
    assert finding_result.finding.created_by_tool_call_id == "call-agent-finding"
    assert finding_result.finding.source_analysis_version == 1
    assert (
        Finding.from_mapping(finding_result.finding.to_record())
        == finding_result.finding
    )
    assert finding_result.finding.paper_contributions[0].supporting_evidence_ids == (
        evidence.evidence_id,
    )

    persisted_evidence, total = await repository.list_evidence(
        "col-1", "obj-1", 2, offset=0, limit=20
    )
    assert total == 1
    assert persisted_evidence[0].evidence_id == evidence.evidence_id
    assert persisted_evidence[0].source_ref == "block-results"
    assert persisted_evidence[0].source_excerpt == _SOURCE_TEXT
    assert persisted_evidence[0].page_numbers == (8,)
    assert persisted_evidence[0].created_by_tool_call_id == "call-agent-analysis"


@pytest.mark.parametrize(
    ("draft_overrides", "expected_error"),
    (
        ({"source_digest": "0" * 64}, "digest"),
        (
            {"source_excerpt": "The paper reports an invented result."},
            "not contained",
        ),
    ),
)
async def test_rejects_unapproved_or_ungrounded_analysis_without_creating_version(
    draft_overrides: dict,
    expected_error: str,
) -> None:
    service, repository = await _service()

    with pytest.raises(ValueError, match=expected_error):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(_paper_summary(),),
            evidence_drafts=(_evidence_draft(**draft_overrides),),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-invalid",
        )

    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_requires_grounded_evidence_for_every_selected_paper() -> None:
    service, repository = await _service()

    with pytest.raises(ValueError, match="every selected document"):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(_paper_summary(),),
            evidence_drafts=(),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-empty",
        )

    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_rejects_unknown_scientific_contract_value_before_queueing() -> None:
    service, repository = await _service()

    with pytest.raises(ValueError, match="unsupported Evidence role"):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(_paper_summary(),),
            evidence_drafts=(_evidence_draft(evidence_role="asserted_result"),),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-invalid-contract",
        )

    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_marks_claimed_version_failed_when_publication_fails() -> None:
    class _FailingPublicationRepository(MemoryObjectiveRepository):
        async def publish_analysis(self, *args, **kwargs):
            raise RuntimeError("database unavailable during publication")

    repository = _FailingPublicationRepository()
    service, repository = await _service(objective_repository=repository)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(_paper_summary(),),
            evidence_drafts=(_evidence_draft(),),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-publication-failure",
        )

    failed = await repository.read_analysis("col-1", "obj-1", 1)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "agent_analysis_publish_failed"

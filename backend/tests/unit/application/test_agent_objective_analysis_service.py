from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.objectives.agent_analysis_service import (
    AgentObjectiveAnalysisService,
)
from application.chat.capabilities.agent_objective_analysis import (
    AgentPaperSummaryArguments,
    PublishAgentObjectiveAnalysisArguments,
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
from domain.source import SourceBlock, SourceDocument, SourceTable
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
from infra.persistence.memory.source_artifact_repository import (
    MemorySourceArtifactRepository,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_SOURCE_TEXT = (
    "For LPBF Ti-6Al-4V, increasing laser power from 180 W to 220 W reduced "
    "porosity from 1.8% to 0.7%."
)
_CONTEXT_ONLY_TEXT = (
    "Specimens were mounted and polished before optical inspection."
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
        if collection_id != "col-1" or document_id not in {"doc-1", "doc-2"}:
            raise FileNotFoundError("document not found")
        return SimpleNamespace(
            document_id=document_id,
            status="ready",
            preparation_fingerprint=f"prepared-{document_id}",
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
                    block_id="block-methods",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=_CONTEXT_ONLY_TEXT,
                    block_order=0,
                    page=4,
                    heading_path="Methods > Preparation",
                ),
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
            "test": [],
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


async def test_counts_one_source_once_when_multiple_evidence_records_share_it() -> None:
    service, repository = await _service()

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(
            _evidence_draft(),
            _evidence_draft(
                draft_id="porosity-result-by-condition",
                authoring_note=(
                    "The same complete Results Source also supports a second "
                    "condition-level record."
                ),
            ),
        ),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-shared-source",
    )

    contribution = result.contributions[0]
    assert result.analysis.status == "succeeded"
    assert len(result.evidence_records) == 2
    assert contribution.routed_source_count == 1
    assert contribution.extracted_source_count == 1
    assert contribution.comparable_evidence_count == 2
    assert await repository.read_analysis("col-1", "obj-1", 1) is not None


async def test_candidate_objective_rejects_agent_analysis_without_creating_version() -> None:
    analysis_service, repository = await _service(confirmation_status="candidate")

    with pytest.raises(ValueError, match="confirmed before Agent analysis"):
        await analysis_service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(_paper_summary(),),
            evidence_drafts=(_evidence_draft(),),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-unconfirmed-analysis",
        )

    objective = await repository.read_objective("col-1", "obj-1")
    assert objective is not None
    assert objective.confirmation_status == "candidate"
    assert objective.active_analysis_version is None
    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_approved_agent_analysis_can_publish_a_source_traceable_finding() -> None:
    analysis_service, repository = await _service()

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


@pytest.mark.parametrize(
    "evidence_overrides",
    [
        {
            "changed_variables": [
                {
                    "name": "beam diameter",
                    "baseline_value": 80,
                    "target_value": 120,
                    "unit": "um",
                }
            ],
            "comparison": {
                "baseline_label": "80 um",
                "target_label": "120 um",
                "axis_names": ["beam diameter"],
                "comparable": True,
                "incomparability_reasons": [],
            },
        },
        {
            "reported_result": {
                "outcome": "microhardness",
                "baseline_value": 410,
                "target_value": 470,
                "unit": "HV",
                "direction": "increase",
                "result_text": _SOURCE_TEXT,
            }
        },
        {
            "reported_result": {
                "outcome": "porosity",
                "baseline_value": 1.8,
                "target_value": 0.7,
                "unit": "%",
                "direction": "increase",
                "result_text": _SOURCE_TEXT,
            }
        },
        {
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
                "sample": [],
                "process": [{"name": "process", "value": "electron beam melting"}],
                "test": [],
            }
        },
    ],
)
async def test_persists_warnings_for_ungrounded_scientific_fields(
    evidence_overrides: dict,
) -> None:
    service, repository = await _service()

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(_evidence_draft(**evidence_overrides),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-ungrounded-fields",
    )

    assert result.analysis.status == "succeeded"
    assert result.evidence_records[0].warnings
    assert result.contributions[0].warnings
    assert await repository.read_analysis("col-1", "obj-1", 1) is not None


async def test_persists_warning_for_table_values_bound_to_wrong_rows() -> None:
    service, repository = await _service()
    table = SourceTable(
        table_id="table-results",
        document_id="doc-1",
        table_order=0,
        caption_text="Porosity by laser power",
        caption_block_id=None,
        page=9,
        heading_path="Results > Porosity",
        column_headers=("Laser power (W)", "Porosity (%)"),
        table_matrix=(("180", "1.8"), ("220", "0.7")),
        header_row_count=0,
    )
    table_markdown = table.to_record()["table_markdown"]
    await service.source_artifact_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Laser power and porosity",
            text="",
            tables=(table,),
        ),
    )

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(
            _evidence_draft(
                source_kind="table",
                source_ref=table.table_id,
                source_excerpt=table_markdown,
                source_digest=sha256(table_markdown.encode("utf-8")).hexdigest(),
                changed_variables=[
                    {
                        "name": "laser power",
                        "baseline_value": 180,
                        "target_value": 220,
                        "unit": "W",
                    }
                ],
                comparison={
                    "baseline_label": "180",
                    "target_label": "220",
                    "axis_names": ["laser power"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                reported_result={
                    "outcome": "porosity",
                    "value": 1.8,
                    "baseline_value": 0.7,
                    "target_value": 1.8,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "180 W: 0.7%; 220 W: 1.8%.",
                },
                scientific_context={
                    "material": [],
                    "sample": [],
                    "process": [],
                    "test": [],
                },
            ),
        ),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-cross-row",
    )

    assert result.analysis.status == "succeeded"
    assert any("table_rows" in warning for warning in result.evidence_records[0].warnings)


async def test_summary_source_reuses_the_verified_evidence_digest() -> None:
    service, repository = await _service()
    summary = {
        **_paper_summary(),
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-results",
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(summary,),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-summary-reuses-evidence-digest",
    )

    assert result.analysis.status == "succeeded"
    assert [
        item.to_record() for item in result.contributions[0].inspected_source_refs
    ] == [
        {
            "source_kind": "text_window",
            "source_ref": "block-results",
            "source_digest": sha256(_SOURCE_TEXT.encode("utf-8")).hexdigest(),
        }
    ]
    assert await repository.read_analysis("col-1", "obj-1", 1) is not None


async def test_summary_extra_source_still_requires_its_own_digest() -> None:
    service, repository = await _service()
    summary = {
        **_paper_summary(),
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-methods",
            }
        ],
    }

    with pytest.raises(ValueError, match="inspected Source digest"):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(summary,),
            evidence_drafts=(_evidence_draft(),),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-summary-extra-source-no-digest",
        )

    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_requires_grounded_evidence_for_every_selected_paper() -> None:
    service, repository = await _service()

    with pytest.raises(ValueError, match="explicit no-Evidence inspection outcome"):
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


async def test_methods_only_inspection_persists_incomplete_objective_coverage() -> None:
    service, repository = await _service()
    summary = {
        **_paper_summary(),
        "contribution_summary": (
            "The inspected Methods Source describes specimen preparation but does "
            "not report the Objective outcome."
        ),
        "inspection_outcome": "no_grounded_evidence",
        "inspection_outcome_reason": (
            "The inspected Source contains no porosity result for the Objective."
        ),
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-methods",
                "source_digest": sha256(
                    _CONTEXT_ONLY_TEXT.encode("utf-8")
                ).hexdigest(),
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(summary,),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-no-evidence",
    )

    assert result.analysis.status == "succeeded"
    assert result.analysis.abstention_reason == "insufficient_evidence"
    assert result.evidence_records == ()
    assert result.findings == ()
    assert result.contributions[0].analysis_status == "analyzed"
    assert result.contributions[0].evidence_disposition == "coverage_incomplete"
    assert result.contributions[0].routed_source_count == 2
    assert result.contributions[0].extracted_source_count == 0
    assert result.contributions[0].uninspected_source_count == 1
    assert [
        item.to_record() for item in result.contributions[0].inspected_source_refs
    ] == summary["inspected_source_refs"]
    assert result.contributions[0].evidence_disposition_reason == (
        "1 Objective-relevant Source remains uninspected."
    )
    assert result.contributions[0].warnings == (
        "1 Objective-relevant Source remains uninspected.",
    )

    persisted_contributions = await repository.list_contributions(
        "col-1", "obj-1", result.analysis.analysis_version
    )
    assert persisted_contributions == result.contributions
    assert [
        item.to_record()
        for item in persisted_contributions[0].inspected_source_refs
    ] == summary["inspected_source_refs"]

    persisted, total = await repository.list_evidence(
        "col-1", "obj-1", result.analysis.analysis_version, offset=0, limit=20
    )
    assert total == 0
    assert persisted == ()


async def test_complete_context_only_inspection_can_publish_no_grounded_evidence() -> None:
    service, repository = await _service()
    context_text = (
        "Laser power was held constant at 200 W during specimen preparation."
    )
    await service.source_artifact_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Laser process context without a porosity result",
            text=context_text,
            blocks=(
                SourceBlock(
                    block_id="block-methods",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=context_text,
                    block_order=0,
                    page=4,
                    heading_path="Methods > Processing",
                ),
            ),
        ),
    )
    reason = "The inspected Source reports no porosity outcome."
    summary = {
        **_paper_summary(),
        "inspection_outcome": "no_grounded_evidence",
        "inspection_outcome_reason": reason,
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-methods",
                "source_digest": sha256(context_text.encode("utf-8")).hexdigest(),
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(summary,),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-complete-no-evidence",
    )

    assert result.analysis.status == "succeeded"
    assert result.analysis.abstention_reason == "no_grounded_evidence"
    contribution = result.contributions[0]
    assert contribution.evidence_disposition == "no_grounded_evidence"
    assert contribution.routed_source_count == 1
    assert contribution.uninspected_source_count == 0
    assert contribution.evidence_disposition_reason == reason
    assert contribution.warnings == ()

    persisted = await repository.list_contributions(
        "col-1", "obj-1", result.analysis.analysis_version
    )
    assert persisted == result.contributions


async def test_grounded_evidence_survives_incomplete_relevant_source_coverage() -> None:
    service, repository = await _service()
    uninspected_result_text = (
        "Additional porosity measurements were reported for a second build condition."
    )
    await service.source_artifact_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Laser power and porosity",
            text=f"{_SOURCE_TEXT} {uninspected_result_text}",
            blocks=(
                SourceBlock(
                    block_id="block-methods",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=_CONTEXT_ONLY_TEXT,
                    block_order=0,
                    page=4,
                    heading_path="Methods > Preparation",
                ),
                SourceBlock(
                    block_id="block-results",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=_SOURCE_TEXT,
                    block_order=1,
                    page=8,
                    heading_path="Results > Porosity",
                ),
                SourceBlock(
                    block_id="block-additional-results",
                    document_id="doc-1",
                    block_type="paragraph",
                    text=uninspected_result_text,
                    block_order=2,
                    page=9,
                    heading_path="Results > Porosity",
                ),
            ),
        ),
    )

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-partial-evidence",
    )

    assert result.analysis.status == "succeeded"
    assert result.analysis.abstention_reason is None
    assert len(result.evidence_records) == 1
    contribution = result.contributions[0]
    assert contribution.evidence_disposition == "coverage_incomplete"
    assert contribution.routed_source_count == 2
    assert contribution.extracted_source_count == 1
    assert contribution.comparable_evidence_count == 1
    assert contribution.uninspected_source_count == 1

    persisted, total = await repository.list_evidence(
        "col-1", "obj-1", result.analysis.analysis_version, offset=0, limit=20
    )
    assert total == 1
    assert persisted == result.evidence_records


async def test_objective_relevant_source_coverage_is_bounded_per_paper() -> None:
    service, _repository = await _service()
    blocks = tuple(
        SourceBlock(
            block_id=f"block-result-{position}",
            document_id="doc-1",
            block_type="paragraph",
            text=(
                f"Result {position}: laser power was evaluated against porosity."
            ),
            block_order=position,
            page=position + 1,
            heading_path="Results > Porosity",
        )
        for position in range(12)
    )
    await service.source_artifact_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Extended laser power and porosity results",
            text=" ".join(block.text for block in blocks),
            blocks=blocks,
        ),
    )
    first_text = blocks[0].text
    summary = {
        **_paper_summary(),
        "inspection_outcome": "no_grounded_evidence",
        "inspection_outcome_reason": (
            "The first inspected Source did not contain a usable result value."
        ),
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": blocks[0].block_id,
                "source_digest": sha256(first_text.encode("utf-8")).hexdigest(),
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(summary,),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-bounded-coverage",
    )

    contribution = result.contributions[0]
    assert contribution.evidence_disposition == "coverage_incomplete"
    assert contribution.routed_source_count == 8
    assert contribution.uninspected_source_count == 7


async def test_publishes_technical_extraction_failure_at_paper_level() -> None:
    service, repository = await _service()
    await service.source_artifact_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-2",
            document_order=1,
            title="Context-only paper",
            text=_CONTEXT_ONLY_TEXT,
            blocks=(
                SourceBlock(
                    block_id="block-methods-2",
                    document_id="doc-2",
                    block_type="paragraph",
                    text=_CONTEXT_ONLY_TEXT,
                    block_order=0,
                    page=2,
                    heading_path="Methods",
                ),
            ),
        ),
    )
    failure_reason = (
        "The inspected Results Source could not be extracted after the provider "
        "returned malformed structured output."
    )
    summary = {
        **_paper_summary(),
        "contribution_summary": (
            "The target Results Source was selected, but technical extraction did "
            "not produce a usable Evidence record."
        ),
        "inspection_outcome": "extraction_failed",
        "inspection_outcome_reason": failure_reason,
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-results",
                "source_digest": sha256(_SOURCE_TEXT.encode("utf-8")).hexdigest(),
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1", "doc-2"),
        paper_summaries=(
            summary,
            {
                "document_id": "doc-2",
                "relevance": "medium",
                "paper_role": "supporting_background",
                "contribution_summary": (
                    "The inspected Source contains context but no target result."
                ),
                "confidence": 0.8,
                "inspection_outcome": "no_grounded_evidence",
                "inspection_outcome_reason": (
                    "The inspected Source contains no porosity result."
                ),
                "inspected_source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "block-methods-2",
                        "source_digest": sha256(
                            _CONTEXT_ONLY_TEXT.encode("utf-8")
                        ).hexdigest(),
                    }
                ],
            },
        ),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-extraction-failure",
    )

    contribution = next(
        item for item in result.contributions if item.document_id == "doc-1"
    )
    assert contribution.analysis_status == "failed"
    assert contribution.evidence_disposition == "extraction_failed"
    assert contribution.routed_source_count == 1
    assert contribution.extracted_source_count == 0
    assert contribution.comparable_evidence_count == 0
    assert contribution.failed_source_count == 1
    assert contribution.evidence_disposition_reason == failure_reason
    assert contribution.warnings == (
        "Source extraction failed before Evidence could be recorded.",
    )
    assert [
        item.to_record() for item in contribution.inspected_source_refs
    ] == summary["inspected_source_refs"]

    persisted = await repository.list_contributions(
        "col-1", "obj-1", result.analysis.analysis_version
    )
    assert persisted == result.contributions


async def test_technical_failure_may_omit_digest_but_keeps_source_identity() -> None:
    service, repository = await _service()
    summary = {
        **_paper_summary(),
        "inspection_outcome": "extraction_failed",
        "inspection_outcome_reason": (
            "The provider failed before a complete Source digest was returned."
        ),
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-results",
            }
        ],
    }

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(summary,),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-missing-digest",
    )

    assert result.analysis.status == "failed"
    assert result.contributions[0].evidence_disposition == "extraction_failed"
    assert result.contributions[0].inspected_source_refs[0].source_digest is None
    assert await repository.read_analysis("col-1", "obj-1", 1) is not None


async def test_all_technical_extraction_failures_fail_the_agent_analysis_run() -> None:
    service, repository = await _service()

    first = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(_paper_summary(),),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-initial-success",
    )
    assert first.analysis.status == "succeeded"
    assert first.analysis.analysis_version == 1

    failure_reason = "The selected Source could not be extracted after retries."
    failed = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1",),
        paper_summaries=(
            {
                **_paper_summary(),
                "inspection_outcome": "extraction_failed",
                "inspection_outcome_reason": failure_reason,
                "inspected_source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "block-results",
                        "source_digest": sha256(
                            _SOURCE_TEXT.encode("utf-8")
                        ).hexdigest(),
                    }
                ],
            },
        ),
        evidence_drafts=(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-all-extraction-failed",
    )

    assert failed.analysis.analysis_version == 2
    assert failed.analysis.status == "failed"
    assert failed.analysis.error_code == "agent_analysis_extraction_failed"
    assert failed.analysis.error_message == (
        "Agent analysis failed to extract every relevant paper."
    )
    objective = await repository.read_objective("col-1", "obj-1")
    assert objective is not None
    assert objective.published_analysis_version == 1
    assert objective.active_analysis_version == 2
    persisted_failed = await repository.read_analysis("col-1", "obj-1", 2)
    assert persisted_failed == failed.analysis
    persisted_contributions = await repository.list_contributions("col-1", "obj-1", 2)
    assert persisted_contributions == failed.contributions
    assert persisted_contributions[0].analysis_status == "failed"
    assert persisted_contributions[0].evidence_disposition == "extraction_failed"
    assert persisted_contributions[0].evidence_disposition_reason == failure_reason


def test_publish_contract_allows_an_all_no_evidence_scope_and_irrelevant_paper() -> None:
    summary = AgentPaperSummaryArguments.model_validate(
        {
            "document_id": "doc-1",
            "relevance": "irrelevant",
            "paper_role": "irrelevant",
            "contribution_summary": "The inspected paper is outside the question scope.",
            "confidence": 0.9,
            "inspection_outcome": "excluded_after_review",
            "inspection_outcome_reason": "The paper does not study the target outcome.",
            "inspected_source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-methods",
                    "source_digest": sha256(
                        _CONTEXT_ONLY_TEXT.encode("utf-8")
                    ).hexdigest(),
                }
            ],
        }
    )
    payload = PublishAgentObjectiveAnalysisArguments.model_validate(
        {
            "objective_id": "obj-1",
            "document_ids": ["doc-1"],
            "paper_summaries": [summary.model_dump()],
            "evidence_drafts": [],
        }
    )

    assert payload.evidence_drafts == []
    assert payload.paper_summaries[0].relevance == "irrelevant"


def test_publish_contract_explains_that_comparison_axes_are_changed_variables() -> None:
    schema = PublishAgentObjectiveAnalysisArguments.model_json_schema()
    description = schema["$defs"]["EvidenceComparisonArguments"]["properties"][
        "axis_names"
    ]["description"]

    assert "changed_variables[].name" in description
    assert "not the measured outcome" in description


def test_publish_contract_accepts_a_technical_extraction_failure_outcome() -> None:
    summary = AgentPaperSummaryArguments.model_validate(
        {
            **_paper_summary(),
            "inspection_outcome": "extraction_failed",
            "inspection_outcome_reason": (
                "The selected Source could not be parsed into Evidence."
            ),
            "inspected_source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-results",
                    "source_digest": "0" * 64,
                }
            ],
        }
    )

    assert summary.inspection_outcome == "extraction_failed"
    assert summary.inspection_outcome_reason is not None


def test_publish_contract_rejects_evidence_with_a_no_evidence_disposition() -> None:
    with pytest.raises(ValidationError, match="explicit no-Evidence inspection outcome"):
        PublishAgentObjectiveAnalysisArguments.model_validate(
            {
                "objective_id": "obj-1",
                "document_ids": ["doc-1"],
                "paper_summaries": [
                    {
                        **_paper_summary(),
                        "inspection_outcome": "no_grounded_evidence",
                        "inspection_outcome_reason": "The inspected Source has no result.",
                        "inspected_source_refs": [
                            {
                                "source_kind": "text_window",
                                "source_ref": "block-methods",
                                "source_digest": sha256(
                                    _CONTEXT_ONLY_TEXT.encode("utf-8")
                                ).hexdigest(),
                            }
                        ],
                    }
                ],
                "evidence_drafts": [_evidence_draft()],
            }
        )


async def test_invalid_no_evidence_source_digest_does_not_create_analysis_version() -> None:
    service, repository = await _service()
    summary = {
        **_paper_summary(),
        "inspection_outcome": "no_grounded_evidence",
        "inspection_outcome_reason": "The inspected Source has no porosity result.",
        "inspected_source_refs": [
            {
                "source_kind": "text_window",
                "source_ref": "block-methods",
                "source_digest": "0" * 64,
            }
        ],
    }

    with pytest.raises(ValueError, match="inspected Source digest"):
        await service.publish(
            collection_id="col-1",
            objective_id="obj-1",
            document_ids=("doc-1",),
            paper_summaries=(summary,),
            evidence_drafts=(),
            model_name="zai-org/glm-5.2",
            prompt_version="research-agent-v13",
            created_by_user_id="user-1",
            created_by_tool_call_id="call-invalid-no-evidence-digest",
        )

    assert await repository.read_analysis("col-1", "obj-1", 1) is None


async def test_agent_analysis_supports_mixed_evidence_and_excluded_scope() -> None:
    service, repository = await _service()
    source_repository = service.source_artifact_repository
    await source_repository.replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-2",
            document_order=1,
            title="Out-of-scope paper",
            text=_CONTEXT_ONLY_TEXT,
            blocks=(
                SourceBlock(
                    block_id="block-methods-2",
                    document_id="doc-2",
                    block_type="paragraph",
                    text=_CONTEXT_ONLY_TEXT,
                    block_order=0,
                    page=2,
                    heading_path="Methods",
                ),
            ),
        ),
    )

    result = await service.publish(
        collection_id="col-1",
        objective_id="obj-1",
        document_ids=("doc-1", "doc-2"),
        paper_summaries=(
            _paper_summary(),
            {
                "document_id": "doc-2",
                "relevance": "irrelevant",
                "paper_role": "irrelevant",
                "contribution_summary": "The paper was inspected and excluded.",
                "confidence": 0.95,
                "inspection_outcome": "excluded_after_review",
                "inspection_outcome_reason": (
                    "The paper does not report the target porosity outcome."
                ),
                "inspected_source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "block-methods-2",
                        "source_digest": sha256(
                            _CONTEXT_ONLY_TEXT.encode("utf-8")
                        ).hexdigest(),
                    }
                ],
            },
        ),
        evidence_drafts=(_evidence_draft(),),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-mixed-scope",
    )

    assert [item.document_id for item in result.contributions] == ["doc-1", "doc-2"]
    assert result.contributions[0].evidence_disposition == "comparable_evidence"
    assert result.contributions[1].analysis_status == "excluded"
    assert result.contributions[1].evidence_disposition == "excluded"


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

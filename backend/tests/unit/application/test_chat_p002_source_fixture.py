from __future__ import annotations

import json
from collections import deque
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.chat import (
    AgentContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
)
from application.chat.capabilities import (
    CreateEvidenceDraftArguments,
    CreateEvidenceDraftCapability,
    CreateEvidenceVersionCapability,
    CreateFindingDraftArguments,
    CreateFindingDraftCapability,
    InspectDocumentSourcesCapability,
    InspectTableCapability,
    ProposeResearchPlanArguments,
    ProposeResearchPlanCapability,
)
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.core.objectives.agent_analysis_service import AgentObjectiveAnalysisService
from application.core.objectives.finding_authoring_service import FindingAuthoringService
from domain.core import ObjectiveFactSet, ResearchObjective
from domain.source import SourceDocument
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "agent_p002" / "source_document.json"
)


def _p002_document() -> SourceDocument:
    return SourceDocument.from_record(
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    )


class _P002CollectionService:
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        assert (collection_id, user_id) == ("collection-p002", "researcher-1")
        return {
            "collection_id": collection_id,
            "owner_user_id": user_id,
            "name": "P002 preheating study",
        }

    async def get_document(self, collection_id: str, document_id: str) -> SimpleNamespace:
        assert collection_id == "collection-p002"
        if document_id != "doc_ef59d1f3a006":
            raise FileNotFoundError("document not found")
        return SimpleNamespace(
            document_id=document_id,
            status="ready",
            preparation_fingerprint="p002-prepared-fingerprint",
        )


class _P002SourceRepository:
    def __init__(self) -> None:
        self.document = _p002_document()

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        assert collection_id == "collection-p002"
        return self.document if document_id == self.document.document_id else None


class _P002FindingFeedbackService:
    async def export_dataset(
        self,
        *,
        collection_id: str,
        objective_id: str,
    ) -> dict:
        assert (collection_id, objective_id) == (
            "collection-p002",
            "objective-p002-elongation",
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "items": [
                {
                    "finding_id": "finding-p002-elongation",
                    "analysis_version": 1,
                    "label_status": "gold",
                    "finding_fingerprint": "finding.p002:v1",
                    "evidence_fingerprint": "evidence.p002:v1",
                    "training_target": {
                        "statement": (
                            "Build-platform preheating increased elongation from "
                            "72% for NP to 82% for P150."
                        )
                    },
                    "evidence": [
                        {
                            "evidence_id": "evidence-p002-method",
                            "document_id": "doc_ef59d1f3a006",
                            "source_kind": "text_window",
                            "source_ref": "blk_doc_ef59d1f3a006_23",
                            "source_excerpt": (
                                "specimens fabricated without preheating the build "
                                "platform, and the ones fabricated with preheating "
                                "the build platform to 150 °C are designated by NP "
                                "and P150, respectively."
                            ),
                            "evidence_status": "descriptive",
                        },
                        {
                            "evidence_id": "evidence-p002-table",
                            "document_id": "doc_ef59d1f3a006",
                            "source_kind": "table",
                            "source_ref": "tbl_doc_ef59d1f3a006_2_table_2",
                            "source_excerpt": (
                                "| Non-preheated | 448 | 617 | 72 |\n"
                                "| Preheated | 465 | 618 | 82 |"
                            ),
                            "evidence_status": "comparable",
                        },
                    ],
                }
            ],
        }


def _context(tool_call_id: str) -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        session_id="session-p002",
        user_id="researcher-1",
        collection_id="collection-p002",
        tool_call_id=tool_call_id,
    )


async def test_p002_agent_reads_real_conditions_table_and_preserves_direction() -> None:
    collection_service = _P002CollectionService()
    source_repository = _P002SourceRepository()
    inspect_sources = InspectDocumentSourcesCapability(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
    )
    inspect_table = InspectTableCapability(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
    )

    methods = await inspect_sources.execute(
        _context("call-p002-methods"),
        inspect_sources.spec.input_model(
            document_id="doc_ef59d1f3a006",
            query="NP P150",
            source_types=["text"],
        ),
    )
    assert methods.status.value == "succeeded"
    assert methods.data["match_total"] == 1
    methods_source = methods.data["sources"][0]
    assert methods_source["source_ref"] == "blk_doc_ef59d1f3a006_23"
    assert "without preheating" in methods_source["content"]
    assert "designated by NP and P150" in methods_source["content"]
    assert methods.data["document"]["document_id"] == "doc_ef59d1f3a006"

    table = await inspect_table.execute(
        _context("call-p002-table"),
        inspect_table.spec.input_model(
            document_id="doc_ef59d1f3a006",
            table_ref="tbl_doc_ef59d1f3a006_2_table_2",
        ),
    )
    assert table.status.value == "succeeded"
    assert table.data["complete_table"] is True
    assert table.data["source_digest"]
    table_markdown = table.data["table_markdown"]
    assert "| Non-preheated | 448 | 617 | 72 |" in table_markdown
    assert "| Preheated | 465 | 618 | 82 |" in table_markdown
    assert table.data["document_id"] == "doc_ef59d1f3a006"

    evidence_draft = CreateEvidenceDraftCapability(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
    )
    method_arguments = CreateEvidenceDraftArguments.model_validate(
        {
            "draft_id": "draft-p002-method",
            "objective_id": "objective-p002-elongation",
            "source_analysis_version": 1,
            "document_id": "doc_ef59d1f3a006",
            "source_kind": "text_window",
            "source_ref": "blk_doc_ef59d1f3a006_23",
            "source_excerpt": methods_source["content"],
            "source_digest": methods_source["source_digest"],
            "evidence_role": "condition_context",
            "attribution_scope": "descriptive_only",
        }
    )
    table_arguments = CreateEvidenceDraftArguments.model_validate(
        {
            "draft_id": "draft-p002-table",
            "objective_id": "objective-p002-elongation",
            "source_analysis_version": 1,
            "document_id": "doc_ef59d1f3a006",
            "source_kind": "table",
            "source_ref": "tbl_doc_ef59d1f3a006_2_table_2",
            "source_excerpt": (
                "| Non-preheated | 448 | 617 | 72 |\n"
                "| Preheated | 465 | 618 | 82 |"
            ),
            "source_digest": table.data["source_digest"],
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "build-platform preheating",
                    "baseline_value": "NP (not preheated)",
                    "target_value": "P150 (150 °C)",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["build-platform preheating"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "elongation",
                "baseline_value": 72,
                "target_value": 82,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation increased from 72% for NP to 82% for P150.",
            },
            "attribution_scope": "isolated_effect",
        }
    )
    method_result = await evidence_draft.execute(
        _context("call-p002-method-draft"), method_arguments
    )
    table_result = await evidence_draft.execute(
        _context("call-p002-table-draft"), table_arguments
    )
    assert method_result.status.value == "succeeded"
    assert table_result.status.value == "succeeded"
    assert method_result.data["published"] is False
    assert table_result.data["draft"]["reported_result"]["direction"] == "increase"
    assert table_result.data["draft"]["reported_result"]["baseline_value"] == 72
    assert table_result.data["draft"]["reported_result"]["target_value"] == 82
    assert {ref.resource_id.split(":")[0] for ref in table_result.resource_refs} == {
        "doc_ef59d1f3a006"
    }

    finding_draft = CreateFindingDraftCapability()
    finding_result = await finding_draft.execute(
        _context("call-p002-finding-draft"),
        CreateFindingDraftArguments.model_validate(
            {
                "draft_id": "draft-p002-finding",
                "objective_id": "objective-p002-elongation",
                "source_analysis_version": 1,
                "statement": (
                    "Build-platform preheating increased elongation from 72% "
                    "for NP to 82% for P150."
                ),
                "assertion_strength": "descriptive",
                "supporting_evidence_ids": ["evidence-p002-table"],
                "limitations": ["This fixture contains one paper and two conditions."],
            }
        ),
    )
    assert finding_result.status.value == "succeeded"
    assert "increased elongation from 72% for NP to 82% for P150" in (
        finding_result.data["draft"]["statement"]
    )
    assert finding_result.data["requires_user_approval"] is True

    plan_result = await ProposeResearchPlanCapability(
        collection_service=collection_service,
        finding_feedback_service=_P002FindingFeedbackService(),
    ).execute(
        _context("call-p002-plan"),
        ProposeResearchPlanArguments.model_validate(
            {
                "objective_id": "objective-p002-elongation",
                "title": "Validate the preheating-related elongation increase",
                "hypothesis": (
                    "Preheating the build platform increases elongation under the "
                    "reported LPBF conditions."
                ),
                "variables": [
                    {
                        "name": "build-platform preheating",
                        "role": "independent",
                        "planned_values": ["NP", "P150"],
                        "basis": "literature_derived",
                        "basis_evidence_ids": ["evidence-p002-table"],
                    },
                    {
                        "name": "elongation",
                        "role": "response",
                        "planned_values": ["measured percentage"],
                        "basis": "literature_derived",
                        "basis_evidence_ids": ["evidence-p002-table"],
                    },
                ],
                "controls": ["Use NP as the baseline condition."],
                "fixed_conditions": ["Keep the reported LPBF process parameters fixed."],
                "measurements": ["Measure elongation to failure."],
                "replication": "Use independent specimens in both conditions.",
                "analysis_method": "Compare P150 with NP while preserving uncertainty.",
                "acceptance_criteria": ["The direction remains an increase in replicated tests."],
                "feasibility_checks": ["Confirm stable build-platform temperature control."],
                "safety_considerations": ["Follow powder and hot-surface procedures."],
                "limitations": ["The literature fixture represents one P002 study."],
                "finding_ids": ["finding-p002-elongation"],
                "evidence_ids": ["evidence-p002-method", "evidence-p002-table"],
            }
        ),
    )
    assert plan_result.status.value == "succeeded"
    assert "increases elongation" in plan_result.data["content"]
    assert "72% for NP to 82% for P150" in plan_result.data["content"]
    assert {ref.resource_type for ref in plan_result.resource_refs} >= {
        "finding",
        "evidence",
        "source",
    }


class _WriteModel:
    def __init__(self, arguments: dict) -> None:
        self.turns = deque(
            (
                ModelTurn(
                    content="I prepared the source-grounded Evidence for approval.",
                    tool_calls=(ModelToolCall(
                        name="create_evidence_version",
                        arguments=arguments,
                    ),),
                ),
                ModelTurn(content="The approved Evidence draft was saved."),
            )
        )

    def respond(self, *, context: tuple, tool_specs: tuple) -> ModelTurn:
        messages = context.messages
        assert messages
        assert {item.name for item in tool_specs} == (
            {"create_evidence_version"} if len(self.turns) == 2 else set()
        )
        return self.turns.popleft()


async def test_p002_evidence_write_stays_approval_gated() -> None:
    calls: list[dict] = []

    class _EvidenceAuthoringService:
        async def create_version(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                analysis=SimpleNamespace(
                    analysis_version=2,
                    to_record=lambda: {"analysis_version": 2, "status": "succeeded"},
                ),
                evidence=SimpleNamespace(
                    evidence_id="evidence-p002-authored",
                    page_numbers=(8,),
                    supports_finding=True,
                    warnings=(),
                    to_record=lambda: {
                        "evidence_id": "evidence-p002-authored",
                        "source_ref": "tbl_doc_ef59d1f3a006_2_table_2",
                    },
                ),
            )

    document = _p002_document()
    table_markdown = document.tables[0].to_record()["table_markdown"]
    arguments = {
        "objective_id": "objective-p002-elongation",
        "source_analysis_version": 1,
        "document_id": document.document_id,
        "source_kind": "table",
        "source_ref": document.tables[0].table_id,
        "source_excerpt": "| Non-preheated | 448 | 617 | 72 |",
        "source_digest": sha256(table_markdown.encode("utf-8")).hexdigest(),
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "build-platform preheating",
                "baseline_value": "NP",
                "target_value": "P150",
            }
        ],
        "comparison": {
            "baseline_label": "NP",
            "target_label": "P150",
            "comparable": True,
        },
        "reported_result": {
            "outcome": "elongation",
            "baseline_value": 72,
            "target_value": 82,
            "unit": "%",
            "direction": "increase",
            "result_text": "Elongation increased from 72% to 82%.",
        },
        "attribution_scope": "isolated_effect",
    }
    capability = CreateEvidenceVersionCapability(
        evidence_authoring_service=_EvidenceAuthoringService()
    )
    runner = ResearchAgentRunner(
        model=_WriteModel(arguments),
        capabilities=CapabilityRegistry((capability,)),
    )
    context = AgentContext("session-p002", "researcher-1", "collection-p002")
    pending = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message="Save the reviewed P002 elongation Evidence.",
    )
    assert pending.status.value == "approval_required"
    assert calls == []
    approved = pending.pending_approval.approve(
        user_id="researcher-1",
        arguments_digest=pending.pending_approval.arguments_digest,
        decided_at="2026-09-06T00:00:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=pending.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )
    assert completed.status.value == "completed"
    assert completed.tool_results[0].status.value == "succeeded"
    assert len(calls) == 1
    assert calls[0]["document_id"] == "doc_ef59d1f3a006"
    assert calls[0]["reported_result"]["direction"] == "increase"


async def test_p002_agent_analysis_and_finding_reuse_published_source_contract() -> None:
    collection_service = _P002CollectionService()
    source_repository = _P002SourceRepository()
    objective_repository = MemoryObjectiveRepository()
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "collection-p002",
            "objective_id": "objective-p002-elongation",
            "question": "How does build-platform preheating affect elongation?",
            "material_scope": ["316L stainless steel"],
            "variables": ["build-platform preheating"],
            "outcomes": ["elongation"],
            "seed_document_ids": ["doc_ef59d1f3a006"],
            "confirmation_status": "confirmed",
        }
    )
    await objective_repository.replace(
        "collection-p002",
        ObjectiveFactSet(research_objectives=(objective,)),
    )
    service = AgentObjectiveAnalysisService(
        collection_service=collection_service,
        objective_repository=objective_repository,
        source_artifact_repository=source_repository,
    )
    table = _p002_document().tables[0]
    table_markdown = table.to_record()["table_markdown"]
    result = await service.publish(
        collection_id="collection-p002",
        objective_id="objective-p002-elongation",
        document_ids=("doc_ef59d1f3a006",),
        paper_summaries=(
            {
                "document_id": "doc_ef59d1f3a006",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "contribution_summary": (
                    "Reports NP and P150 tensile results with a source-linked table."
                ),
                "confidence": 0.95,
            },
        ),
        evidence_drafts=(
            {
                "draft_id": "draft-p002-agent-table",
                "document_id": "doc_ef59d1f3a006",
                "source_kind": "table",
                "source_ref": table.table_id,
                "source_excerpt": table_markdown,
                "source_digest": sha256(table_markdown.encode("utf-8")).hexdigest(),
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "build-platform preheating",
                        "baseline_value": "NP",
                        "target_value": "P150",
                    }
                ],
                "comparison": {
                    "baseline_label": "NP",
                    "target_label": "P150",
                    "axis_names": ["build-platform preheating"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "elongation",
                    "baseline_value": 72,
                    "target_value": 82,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Elongation increased from 72% for NP to 82% for P150.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "material": [
                        {"name": "alloy", "value": "316L stainless steel"}
                    ],
                    "sample": [],
                    "process": [{"name": "process", "value": "LPBF"}],
                    "test": [{"name": "measurement", "value": "elongation"}],
                },
                "confidence": 0.95,
                "authoring_note": "Agent inspected the complete P002 Table 2 Source.",
            },
        ),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13.4",
        created_by_user_id="researcher-1",
        created_by_tool_call_id="call-p002-agent-analysis",
    )

    assert result.analysis.status == "succeeded"
    assert result.evidence_records[0].reported_result.target_value == 82
    assert result.evidence_records[0].reported_result.baseline_value == 72
    assert result.evidence_records[0].reported_result.direction == "increase"

    finding = await FindingAuthoringService(
        collection_service=collection_service,
        objective_repository=objective_repository,
    ).create_version(
        collection_id="collection-p002",
        objective_id="objective-p002-elongation",
        source_analysis_version=result.analysis.analysis_version,
        statement="Build-platform preheating increased elongation from 72% to 82%.",
        assertion_strength="descriptive",
        supporting_evidence_ids=(result.evidence_records[0].evidence_id,),
        contradicting_evidence_ids=(),
        context_evidence_ids=(),
        condition_boundary_evidence_ids=(),
        limitations=("The fixture represents one paper and two conditions.",),
        parent_finding_id=None,
        abstention_reason=None,
        created_by_user_id="researcher-1",
        created_by_tool_call_id="call-p002-agent-finding",
    )

    assert finding.finding is not None
    assert finding.finding.source_analysis_version == result.analysis.analysis_version
    assert finding.finding.paper_contributions[0].supporting_evidence_ids == (
        result.evidence_records[0].evidence_id,
    )

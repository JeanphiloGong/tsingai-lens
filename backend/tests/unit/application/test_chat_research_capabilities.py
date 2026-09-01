from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.chat import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
)
from application.chat.capabilities import (
    CreateObjectiveCandidateArguments,
    CreateObjectiveCandidateCapability,
    CurateFindingCapability,
    GetCollectionContextCapability,
    InspectDocumentSourcesCapability,
    InspectObjectiveAnalysisCapability,
    InspectPublishedFindingCapability,
    InspectResearchProcessCapability,
    PreviewResearchScopeCapability,
    ProposeObjectiveDraftsArguments,
    ProposeObjectiveDraftsCapability,
    QueryPublishedFindingsCapability,
    RecordFindingFeedbackCapability,
    StartObjectiveAnalysisArguments,
    StartObjectiveAnalysisCapability,
    StartResearchProcessArguments,
    StartResearchProcessCapability,
)
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisDispatchError
from domain.core import (
    ObjectiveFactSet,
    PaperResearchMap,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.source import SourceBlock, SourceDocument, SourceFigure, SourceTable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _objective(
    objective_id: str,
    *,
    outcome: str = "elongation",
    published_version: int | None = None,
) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": objective_id,
            "question": f"How does energy input affect {outcome}?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["energy input"],
            "outcomes": [outcome],
            "seed_document_ids": ["paper-1", "paper-2"],
            "confidence": 0.8,
            "confirmation_status": "confirmed" if published_version else "candidate",
            "active_analysis_version": published_version,
            "published_analysis_version": published_version,
        }
    )


def _skim() -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-1",
                    "document_id": "paper-1",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["Ti-6Al-4V"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-1",
                            "varied_factors": ["laser power", "scan speed"],
                            "outcome": "elongation",
                            "source_refs": [
                                {"source_kind": "table", "source_ref": "table-2"}
                            ],
                            "confidence": 0.86,
                        }
                    ],
                    "confidence": 0.84,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.84,
            "warnings": [],
        }
    )


class _CollectionService:
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        if collection_id != "col-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {
            "collection_id": "col-1",
            "owner_user_id": "user-1",
            "name": "LPBF Ti-6Al-4V",
            "description": "Processing, microstructure, and tensile behavior.",
            "status": "ready",
            "paper_count": 10,
            "documents": [
                {
                    "document_id": "paper-1",
                    "status": "stored",
                },
                {
                    "document_id": "paper-2",
                    "status": "stored",
                },
            ],
        }

    async def get_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SimpleNamespace:
        if collection_id != "col-1" or document_id not in {"paper-1", "paper-2"}:
            raise FileNotFoundError("document not found")
        return SimpleNamespace(
            document_id=document_id,
            status="ready",
            preparation_fingerprint=f"fingerprint-{document_id}",
        )


class _EmptyCollectionService(_CollectionService):
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        return {
            **await super().get_collection_for_user(collection_id, user_id),
            "paper_count": 0,
            "documents": [],
        }


class _ObjectiveRepository:
    def __init__(self, objectives: tuple[ResearchObjective, ...]) -> None:
        self.objectives = objectives
        self.facts = ObjectiveFactSet(
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),)
        )

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        assert collection_id == "col-1"
        return self.objectives

    async def read(self, collection_id: str) -> ObjectiveFactSet:
        assert collection_id == "col-1"
        return self.facts


class _TaskService:
    def __init__(self, tasks: list[dict]) -> None:
        self.tasks = tasks
        self.calls: list[dict] = []

    async def list_tasks(self, **kwargs) -> list[dict]:
        self.calls.append(kwargs)
        return self.tasks


class _DocumentPreparationService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def queue_document(
        self, collection_id: str, document_id: str, **kwargs
    ) -> dict:
        self.calls.append(
            {"collection_id": collection_id, "document_id": document_id, **kwargs}
        )
        return {
            "task_id": f"task-{document_id}",
            "collection_id": collection_id,
            "document_id": document_id,
            "status": "queued",
            "mode": kwargs.get("mode", "standard"),
        }


class _PaperMapRepository:
    def __init__(self, paper_maps: tuple[PaperResearchMap, ...] = (_skim(),)) -> None:
        self.paper_maps = paper_maps

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        assert collection_id == "col-1"
        selected = set(document_ids) if document_ids is not None else None
        return tuple(
            item
            for item in self.paper_maps
            if selected is None or item.document_id in selected
        )


class _SourceArtifactRepository:
    def __init__(self) -> None:
        self.document = SourceDocument(
            document_id="paper-1",
            document_order=0,
            title="Energy input and tensile response",
            text="",
            blocks=(
                SourceBlock(
                    block_id="block-introduction",
                    document_id="paper-1",
                    block_type="paragraph",
                    text="Laser power and scan speed define the energy input.",
                    block_order=1,
                    page=1,
                    heading_path="Introduction",
                ),
                SourceBlock(
                    block_id="block-result",
                    document_id="paper-1",
                    block_type="paragraph",
                    text="Elongation decreased as the combined energy input increased.",
                    block_order=2,
                    page=5,
                    heading_path="Results / Tensile properties",
                ),
            ),
            tables=(
                SourceTable(
                    table_id="table-2",
                    document_id="paper-1",
                    table_order=1,
                    caption_text="Elongation under the tested process conditions",
                    caption_block_id=None,
                    page=5,
                    heading_path="Results / Tensile properties",
                    column_headers=("Condition", "Elongation (%)"),
                    table_matrix=(("Low energy", "10.1"), ("High energy", "7.8")),
                ),
            ),
            figures=(
                SourceFigure(
                    figure_id="figure-3",
                    document_id="paper-1",
                    figure_order=1,
                    figure_label="Figure 3",
                    caption_text="Elongation response for all samples.",
                    caption_block_id=None,
                    page=6,
                    heading_path="Results / Tensile properties",
                    image_path=None,
                    image_mime_type=None,
                    image_width=None,
                    image_height=None,
                    asset_sha256=None,
                ),
            ),
        )

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        assert collection_id == "col-1"
        return self.document if document_id == self.document.document_id else None


def _canonical_finding_record() -> dict:
    return {
        "collection_id": "col-1",
        "objective_id": "objective-published",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "statement": "Higher energy input was associated with lower elongation.",
        "factors": ["energy input"],
        "outcome": "elongation",
        "direction": "decrease",
        "assertion_strength": "associative",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.78,
        "display_rank": 1,
        "mechanisms": [],
        "scientific_context": {
            "material": [],
            "sample": [],
            "process": [],
            "test": [],
        },
        "limitations": ["Only one paper reported a directly comparable result."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": [],
                "condition_boundary_evidence_ids": [],
            }
        ],
    }


class _RecordedReview:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_record(self) -> dict:
        return dict(self.payload)


class _FindingFeedbackService:
    def __init__(self) -> None:
        self.feedback_calls: list[dict] = []
        self.curation_calls: list[dict] = []

    async def record_feedback(self, **kwargs) -> _RecordedReview:
        self.feedback_calls.append(kwargs)
        return _RecordedReview(
            {
                "feedback_id": "feedback-1",
                **kwargs,
                "created_at": "2026-08-31T08:00:00+00:00",
            }
        )

    async def record_curation(self, **kwargs) -> _RecordedReview:
        self.curation_calls.append(kwargs)
        return _RecordedReview(
            {
                "curation_id": "curation-1",
                **kwargs,
                "updated_at": "2026-08-31T08:00:00+00:00",
            }
        )


class _StartResearchProcessModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        assert messages
        assert {item.name for item in tool_specs} == {"start_research_process"}
        return self.turns.popleft()


class _ObjectiveAuthoringRepository(_ObjectiveRepository):
    def __init__(self) -> None:
        objective = ResearchObjective.from_mapping(
            {
                "collection_id": "col-1",
                "objective_id": "objective-existing",
                "question": "How do laser power and scan speed affect elongation?",
                "material_scope": ["Ti-6Al-4V"],
                "variables": ["laser power", "scan speed"],
                "outcomes": ["elongation"],
                "seed_document_ids": ["paper-1"],
                "source_relationship_ids": ["relationship-1"],
                "rank": 1,
                "confidence": 0.86,
            }
        )
        super().__init__((objective,))
        self.facts = ObjectiveFactSet(
            research_objectives_ready=True,
            document_inputs=(PreparedDocumentInput("paper-1", "fingerprint-1"),),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "paper-1",
                        "study_id": "study-1",
                        "relationship_id": "relationship-1",
                        "status": "promoted",
                        "objective_id": objective.objective_id,
                    }
                ),
            ),
        )
        self.created: list[dict] = []

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective:
        self.created.append(
            {
                "objective": objective,
                "created_by_user_id": created_by_user_id,
                "created_by_tool_call_id": created_by_tool_call_id,
            }
        )
        return ResearchObjective.from_mapping(
            {
                **objective.to_record(),
                "rank": 2,
                "origin": "chat_assisted",
                "created_by_user_id": created_by_user_id,
                "created_by_tool_call_id": created_by_tool_call_id,
            }
        )


class _ObjectiveAuthoringService:
    def __init__(self, objective: ResearchObjective) -> None:
        self.objective = objective
        self.calls: list[dict] = []

    async def create_chat_assisted_candidate(self, **kwargs) -> ResearchObjective:
        self.calls.append(kwargs)
        return self.objective


class _AnalysisService:
    def __init__(self) -> None:
        self.finding_calls: list[str] = []
        self.evidence_calls: list[str] = []

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        **_kwargs,
    ) -> dict:
        self.finding_calls.append(objective_id)
        return {
            "analysis_version": 2,
            "total": 1,
            "items": [
                {
                    "finding_id": "finding-1",
                    "statement": "Higher energy input was associated with lower elongation.",
                    "factors": ["energy input"],
                    "outcome": "elongation",
                    "direction": "decrease",
                    "assertion_strength": "associative",
                    "synthesis_status": "supported",
                    "certainty": 0.78,
                    "paper_contributions": [
                        {
                            "document_id": "paper-1",
                            "supporting_evidence_ids": ["evidence-1"],
                        }
                    ],
                }
            ],
        }

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        **_kwargs,
    ) -> dict:
        self.evidence_calls.append(objective_id)
        return {
            "analysis_version": 2,
            "total": 1,
            "items": [
                {
                    "evidence_id": "evidence-1",
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-2",
                    "source_excerpt": "Elongation decreased from 10.1% to 7.8%.",
                    "evidence_role": "direct_result",
                    "reported_result": {
                        "outcome": "elongation",
                        "direction": "decrease",
                        "result_text": "Elongation decreased.",
                    },
                    "attribution_scope": "joint_effect",
                    "resolution_status": "resolved",
                    "confidence": 0.82,
                }
            ],
        }

    async def get_finding(
        self,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        **_kwargs,
    ) -> dict:
        assert collection_id == "col-1"
        assert objective_id == "objective-published"
        assert finding_id == "finding-1"
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 2,
            "finding": _canonical_finding_record(),
        }


class _Model:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)
        self.contexts: list[tuple] = []

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        self.contexts.append(messages)
        assert {item.name for item in tool_specs} == {
            "get_collection_context",
            "query_published_findings",
            "propose_objective_drafts",
        }
        return self.turns.popleft()


def _context(tool_call_id: str = "call-1") -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
        tool_call_id=tool_call_id,
    )


async def test_collection_context_is_bounded_and_uses_canonical_resource_refs() -> None:
    objectives = tuple(_objective(f"objective-{index}") for index in range(15))
    capability = GetCollectionContextCapability(
        collection_service=_CollectionService(),
        objective_repository=_ObjectiveRepository(objectives),
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    assert result.status.value == "succeeded"
    assert result.data["objective_count"] == 15
    assert len(result.data["objectives"]) == 12
    assert result.resource_refs[0].resource_type == "collection"
    assert result.resource_refs[0].resource_id == "col-1"
    assert result.warnings == ("3 additional Objectives were omitted from this bounded result.",)


async def test_document_source_inspection_returns_bounded_traceable_matches() -> None:
    capability = InspectDocumentSourcesCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context(),
        capability.spec.input_model(
            document_id="paper-1",
            query="elongation",
            offset=1,
            limit=2,
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["document"] == {
        "document_id": "paper-1",
        "title": "Energy input and tensile response",
    }
    assert result.data["match_total"] == 3
    assert result.data["offset"] == 1
    assert result.data["limit"] == 2
    assert result.data["next_offset"] is None
    assert result.data["support_is_evidence"] is False
    assert [item["source_ref"] for item in result.data["sources"]] == [
        "table-2",
        "figure-3",
    ]
    assert result.data["sources"][0]["content"].startswith(
        "| Condition | Elongation (%) |"
    )
    assert [ref.resource_type for ref in result.resource_refs] == [
        "document",
        "source",
        "source",
    ]
    assert "source_ref=table-2" in (result.resource_refs[1].href or "")


async def test_agent_records_finding_feedback_only_after_exact_approval() -> None:
    feedback_service = _FindingFeedbackService()
    capability = RecordFindingFeedbackCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
    )

    class FeedbackModel:
        def __init__(self) -> None:
            self.turns = deque(
                (
                    ModelTurn(
                        content="I prepared a partial-correctness review for approval.",
                        tool_call=ModelToolCall(
                            name="record_finding_feedback",
                            arguments={
                                "objective_id": "objective-published",
                                "analysis_version": 2,
                                "finding_id": "finding-1",
                                "review_status": "partial",
                                "issue_type": "overclaim",
                                "note": "The direction is supported, but the wording is too broad.",
                            },
                        ),
                    ),
                    ModelTurn(content="The approved review has been recorded."),
                )
            )

        def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
            assert messages
            assert {item.name for item in tool_specs} == {"record_finding_feedback"}
            return self.turns.popleft()

    runner = ResearchAgentRunner(
        model=FeedbackModel(),
        capabilities=CapabilityRegistry((capability,)),
    )
    context = AgentContext("chat-1", "user-1", "col-1")

    proposed = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message="Mark this conclusion as partly correct because it overclaims.",
    )

    assert proposed.status.value == "approval_required"
    assert feedback_service.feedback_calls == []
    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-08-31T08:00:00+00:00",
    )
    completed = await runner.resume_approved_call(
        context=context,
        previous_messages=proposed.messages,
        approved_call=approved,
    )

    assert feedback_service.feedback_calls == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-published",
            "analysis_version": 2,
            "finding_id": "finding-1",
            "review_status": "partial",
            "issue_type": "overclaim",
            "note": "The direction is supported, but the wording is too broad.",
            "reviewer": "user-1",
        }
    ]
    assert completed.tool_results[0].data["feedback_id"] == "feedback-1"


async def test_agent_curation_reuses_complete_existing_finding_contract() -> None:
    feedback_service = _FindingFeedbackService()
    capability = CurateFindingCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
    )
    curated_finding = _canonical_finding_record()
    curated_finding["statement"] = (
        "For the reported conditions, higher energy input was associated with "
        "lower elongation."
    )

    result = await capability.execute(
        _context("call-curate-finding"),
        capability.spec.input_model(
            objective_id="objective-published",
            analysis_version=2,
            finding_id="finding-1",
            curated_status="limited",
            curated_finding=curated_finding,
            note="Narrowed the statement to the reported conditions.",
        ),
    )

    assert capability.spec.risk.value == "write"
    assert feedback_service.curation_calls == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-published",
            "analysis_version": 2,
            "finding_id": "finding-1",
            "curated_status": "limited",
            "curated_finding": curated_finding,
            "note": "Narrowed the statement to the reported conditions.",
            "reviewer": "user-1",
        }
    ]
    assert result.data["curation_id"] == "curation-1"
    assert result.resource_refs[0].resource_type == "finding"


async def test_research_process_projects_canonical_task_without_retry_internals() -> None:
    task_service = _TaskService(
        [
            {
                "task_id": "task-1",
                "document_id": "paper-1",
                "status": "running",
                "current_stage": "paper_map",
                "progress_percent": 72,
                "progress_detail": {"phase": "paper_map"},
                "warnings": ["One paper could not be parsed."],
                "errors": [],
            }
        ]
    )
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        task_service=task_service,
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    assert result.status.value == "succeeded"
    assert result.data["process"]["status"] == "processing"
    assert result.data["process"]["counts"] == {
        "stored": 1,
        "processing": 1,
        "ready": 0,
        "failed": 0,
    }
    assert result.data["process"]["documents"][0]["stage"] == "paper_map"
    assert result.data["process"]["documents"][0]["progress_percent"] == 72
    assert result.warnings == ("One paper could not be parsed.",)
    assert task_service.calls == [
        {"collection_id": "col-1", "limit": 200, "offset": 0}
    ]
    assert result.resource_refs[0].href == "/collections/col-1"


async def test_research_process_reports_not_started_without_faking_progress() -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        task_service=_TaskService([]),
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    assert result.status.value == "succeeded"
    assert result.data["process"] == {
        "status": "not_started",
        "document_count": 2,
        "counts": {"stored": 2, "processing": 0, "ready": 0, "failed": 0},
        "documents": [
            {
                "document_id": "paper-1",
                "filename": "",
                "status": "stored",
                "task_id": None,
                "stage": None,
                "progress_percent": 0,
            },
            {
                "document_id": "paper-2",
                "filename": "",
                "status": "stored",
                "task_id": None,
                "stage": None,
                "progress_percent": 0,
            },
        ],
        "objective_discovery_started": False,
        "objective_analysis_started": False,
        "failures": [],
    }


async def test_research_process_treats_interrupted_preparation_as_not_started() -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        task_service=_TaskService(
            [
                {
                    "task_id": "task-interrupted",
                    "document_id": "paper-1",
                    "status": "failed",
                    "current_stage": "interrupted",
                    "progress_percent": 68,
                    "warnings": [],
                    "errors": [
                        "Document preparation was interrupted by a backend restart."
                    ],
                }
            ]
        ),
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    process = result.data["process"]
    assert process["status"] == "not_started"
    assert process["counts"] == {
        "stored": 2,
        "processing": 0,
        "ready": 0,
        "failed": 0,
    }
    assert [document["status"] for document in process["documents"]] == [
        "stored",
        "stored",
    ]
    assert process["failures"] == []


async def test_agent_starts_research_process_only_after_exact_user_approval() -> None:
    preparation_service = _DocumentPreparationService()
    capability = StartResearchProcessCapability(
        collection_service=_CollectionService(),
        document_preparation_service=preparation_service,
    )
    model = _StartResearchProcessModel(
        ModelTurn(
            content="I need your approval before I start reviewing the papers.",
            tool_call=ModelToolCall(name="start_research_process", arguments={}),
        ),
        ModelTurn(
            content=(
                "The literature review has started. I can check its progress while "
                "it prepares the Paper Map and candidate research questions."
            )
        ),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((capability,)),
    )

    proposed = await runner.run_turn(
        context=AgentContext(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
        ),
        previous_messages=(),
        user_message="Start understanding these papers and form research questions.",
    )

    assert proposed.status.value == "approval_required"
    assert preparation_service.calls == []
    assert proposed.pending_approval is not None
    approved_call = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-08-25T08:00:00+00:00",
    )

    completed = await runner.resume_approved_call(
        context=AgentContext(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
        ),
        previous_messages=proposed.messages,
        approved_call=approved_call,
    )

    assert completed.status.value == "completed"
    assert preparation_service.calls == [
        {
            "collection_id": "col-1",
            "document_id": "paper-1",
            "mode": "standard",
        },
        {
            "collection_id": "col-1",
            "document_id": "paper-2",
            "mode": "standard",
        }
    ]
    assert completed.tool_results[0].status.value == "queued"
    assert completed.tool_results[0].data == {
        "collection_id": "col-1",
        "document_ids": ["paper-1", "paper-2"],
        "tasks": (
            {
                "task_id": "task-paper-1",
                "collection_id": "col-1",
                "document_id": "paper-1",
                "status": "queued",
                "mode": "standard",
            },
            {
                "task_id": "task-paper-2",
                "collection_id": "col-1",
                "document_id": "paper-2",
                "status": "queued",
                "mode": "standard",
            },
        ),
        "mode": "standard",
        "research_scope": "document_preparation",
        "objective_discovery_started": False,
        "objective_analysis_started": False,
    }
    assert completed.tool_results[0].resource_refs[0].resource_type == (
        "document_preparation_task"
    )
    assert completed.tool_results[0].resource_refs[0].href == "/collections/col-1"


async def test_start_research_process_reports_missing_papers_as_a_precondition() -> None:
    preparation_service = _DocumentPreparationService()
    capability = StartResearchProcessCapability(
        collection_service=_EmptyCollectionService(),
        document_preparation_service=preparation_service,
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    assert result.status.value == "failed"
    assert result.error_code == "collection_has_no_papers"
    assert result.error_message == (
        "Upload at least one paper before starting literature analysis."
    )
    assert preparation_service.calls == []


def test_agent_write_contracts_accept_complete_scopes_beyond_one_hundred_documents() -> None:
    document_ids = [f"paper-{index}" for index in range(1, 132)]

    research_process = StartResearchProcessArguments(document_ids=document_ids)
    objective_analysis = StartObjectiveAnalysisArguments(
        objective_id="objective-agent",
        document_ids=document_ids,
    )

    assert research_process.document_ids == document_ids
    assert objective_analysis.document_ids == document_ids


@pytest.mark.parametrize(
    ("task_status", "expected_process_status", "expected_document_status"),
    (
        (
            "completed",
            "partial_ready",
            "ready",
        ),
        (
            "partial_success",
            "partial_ready",
            "ready",
        ),
        (
            "failed",
            "attention_required",
            "failed",
        ),
    ),
)
async def test_research_process_keeps_terminal_runtime_outcomes_distinct(
    task_status: str,
    expected_process_status: str,
    expected_document_status: str,
) -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        task_service=_TaskService(
            [
                {
                    "task_id": "task-terminal",
                    "document_id": "paper-1",
                    "status": task_status,
                    "progress_percent": 100,
                    "progress_detail": {"message": "Build artifacts are ready."},
                    "warnings": [],
                    "errors": (
                        ["Source processing stopped."]
                        if task_status == "failed"
                        else []
                    ),
                }
            ]
        ),
    )

    result = await capability.execute(_context(), capability.spec.input_model())

    assert result.status.value == "succeeded"
    assert result.data["process"]["status"] == expected_process_status
    assert result.data["process"]["documents"][0]["status"] == (
        expected_document_status
    )
    assert result.data["process"]["failures"] == (
        ["Source processing stopped."] if task_status == "failed" else []
    )


class _ResearchProcessModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)
        self.contexts: list[tuple] = []

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        self.contexts.append(messages)
        assert {item.name for item in tool_specs} == {"inspect_research_process"}
        return self.turns.popleft()


async def test_agent_continues_from_observable_research_process_result() -> None:
    model = _ResearchProcessModel(
        ModelTurn(
            tool_call=ModelToolCall(name="inspect_research_process", arguments={})
        ),
        ModelTurn(
            content=(
                "The collection is screening research scope in paper 3 of 10; "
                "Objective formation has not started yet."
            )
        ),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                InspectResearchProcessCapability(
                    collection_service=_CollectionService(),
                    task_service=_TaskService(
                        [
                            {
                                "task_id": "task-1",
                                "document_id": "paper-1",
                                "status": "running",
                                "progress_percent": 72,
                                "progress_detail": {
                                    "phase": "paper_research_map_started",
                                    "current": 3,
                                    "total": 10,
                                },
                                "warnings": [],
                                "errors": [],
                            }
                        ]
                    ),
                ),
            )
        ),
    )

    result = await runner.run_turn(
        context=AgentContext(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
        ),
        previous_messages=(),
        user_message="How far has the collection analysis progressed?",
    )

    assert result.status.value == "completed"
    assert result.tool_results[0].data["process"]["status"] == "processing"
    assert result.messages[-1].content.startswith("The collection is screening")
    assert [message.role.value for message in model.contexts[-1][-2:]] == [
        "assistant",
        "tool",
    ]


async def test_published_findings_reads_only_published_objective_versions() -> None:
    published = _objective("objective-published", published_version=2)
    candidate = _objective("objective-candidate")
    repository = _ObjectiveRepository((published, candidate))
    analysis_service = _AnalysisService()
    capability = QueryPublishedFindingsCapability(
        collection_service=_CollectionService(),
        objective_repository=repository,
        objective_analysis_service=analysis_service,
    )

    arguments = capability.spec.input_model(objective_ids=[])
    result = await capability.execute(_context(), arguments)

    assert result.status.value == "succeeded"
    assert result.data["finding_count"] == 1
    assert result.data["evidence_count"] == 1
    assert result.data["scientific_absence"] is False
    assert analysis_service.finding_calls == ["objective-published"]
    assert analysis_service.evidence_calls == ["objective-published"]
    assert {ref.resource_type for ref in result.resource_refs} == {
        "research_objective",
        "finding",
        "evidence",
    }
    refs_by_type = {ref.resource_type: ref for ref in result.resource_refs}
    assert refs_by_type["finding"].href == (
        "/collections/col-1/objectives/objective-published?finding_id=finding-1"
    )
    assert refs_by_type["evidence"].href == (
        "/collections/col-1/documents/paper-1?evidence_id=evidence-1"
    )


async def test_agent_reads_one_complete_published_finding_before_curation() -> None:
    analysis_service = _AnalysisService()
    capability = InspectPublishedFindingCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=analysis_service,
    )

    result = await capability.execute(
        _context("call-inspect-finding"),
        capability.spec.input_model(
            objective_id="objective-published",
            analysis_version=2,
            finding_id="finding-1",
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["finding"] == _canonical_finding_record()
    assert result.data["evidence_total"] == 1
    assert result.data["evidence"][0]["evidence_id"] == "evidence-1"
    assert result.data["evidence"][0]["source_ref"] == "table-2"
    assert result.data["finding_is_published"] is True
    assert [ref.resource_type for ref in result.resource_refs] == [
        "finding",
        "evidence",
    ]


async def test_missing_published_results_is_a_successful_scientific_absence() -> None:
    candidate = _objective("objective-candidate")
    analysis_service = _AnalysisService()
    capability = QueryPublishedFindingsCapability(
        collection_service=_CollectionService(),
        objective_repository=_ObjectiveRepository((candidate,)),
        objective_analysis_service=analysis_service,
    )

    result = await capability.execute(
        _context(),
        capability.spec.input_model(objective_ids=["objective-candidate"]),
    )

    assert result.status.value == "succeeded"
    assert result.data["scientific_absence"] is True
    assert result.data["finding_count"] == 0
    assert analysis_service.finding_calls == []
    assert "No selected Objective has a published analysis." in result.warnings


async def test_objective_drafts_are_transient_and_paper_map_is_not_evidence() -> None:
    capability = ProposeObjectiveDraftsCapability(
        collection_service=_CollectionService(),
        objective_repository=_ObjectiveRepository((_objective("objective-existing"),)),
        paper_map_repository=_PaperMapRepository(),
    )
    arguments = ProposeObjectiveDraftsArguments.model_validate(
        {
            "drafts": [
                {
                    "question": "How do laser power and scan speed affect elongation?",
                    "material_scope": ["Ti-6Al-4V"],
                    "variables": ["laser power", "scan speed"],
                    "outcomes": ["elongation"],
                    "constraints": ["as-built"],
                },
                {
                    "question": "How does hatch spacing affect fatigue strength?",
                    "material_scope": ["Ti-6Al-4V"],
                    "variables": ["hatch spacing"],
                    "outcomes": ["fatigue strength"],
                },
            ]
        }
    )

    result = await capability.execute(_context("call-drafts"), arguments)

    assert result.status.value == "succeeded"
    assert result.data["draft_count"] == 2
    assert result.data["drafts"][0]["support_status"] == "paper_map_context"
    assert result.data["drafts"][0]["supporting_document_ids"] == ["paper-1"]
    assert result.data["drafts"][1]["support_status"] == "unsupported"
    assert {ref.resource_type for ref in result.resource_refs} == {"objective_draft"}
    assert all("evidence" not in ref.resource_type for ref in result.resource_refs)


async def test_objective_draft_contract_rejects_compound_outcomes() -> None:
    with pytest.raises(ValidationError):
        ProposeObjectiveDraftsArguments.model_validate(
            {
                "drafts": [
                    {
                        "question": "How does energy input affect performance?",
                        "variables": ["energy input"],
                        "outcomes": ["strength", "elongation"],
                    }
                ]
            }
        )


async def test_create_objective_candidate_returns_only_an_unconfirmed_core_candidate() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "objective-chat",
            "question": "How do laser power and scan speed affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power", "scan speed"],
            "outcomes": ["elongation"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.86,
            "origin": "chat_assisted",
            "created_by_user_id": "user-1",
            "created_by_tool_call_id": "call-create",
        }
    )
    service = _ObjectiveAuthoringService(objective)
    capability = CreateObjectiveCandidateCapability(
        research_objective_service=service,
    )
    arguments = CreateObjectiveCandidateArguments.model_validate(
        {
            "question": "How do laser power and scan speed affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power", "scan speed"],
            "outcomes": ["elongation"],
            "seed_document_ids": ["paper-1"],
        }
    )

    result = await capability.execute(_context("call-create"), arguments)

    assert result.status.value == "succeeded"
    assert result.data == {
        "objective_id": "objective-chat",
        "confirmation_status": "candidate",
        "origin": "chat_assisted",
        "analysis_started": False,
        "research_status": "untested",
    }
    assert result.resource_refs[0].resource_type == "research_objective"
    assert result.resource_refs[0].resource_id == "objective-chat"
    assert service.calls == [
        {
            "collection_id": "col-1",
            "user_id": "user-1",
            "tool_call_id": "call-create",
            **arguments.model_dump(),
        }
    ]


async def test_scope_preview_keeps_an_insufficient_map_in_human_review_scope() -> None:
    relevant = PaperResearchMap.from_mapping(
        {**_skim().to_record(), "map_status": "sufficient"}
    )
    insufficient = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-2",
            "doc_role": "experimental",
            "studies": [],
            "map_status": "insufficient_map",
            "map_limitations": ["The outcome was not visible in high-level Sources."],
        }
    )
    unrelated = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-3",
            "doc_role": "experimental",
            "map_status": "sufficient",
            "studies": [
                {
                    "study_id": "study-3",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["316L"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-3",
                            "varied_factors": ["solution treatment temperature"],
                            "outcome": "corrosion potential",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-3"}
                            ],
                            "confidence": 0.88,
                        }
                    ],
                }
            ],
        }
    )
    capability = PreviewResearchScopeCapability(
        collection_service=_CollectionService(),
        paper_map_repository=_PaperMapRepository(
            (relevant, insufficient, unrelated)
        ),
    )

    result = await capability.execute(
        _context("call-scope"),
        capability.spec.input_model(
            question="How do laser power and scan speed affect ductility?",
            material_scope=["Ti-6Al-4V"],
            variables=["laser power", "scan speed"],
            outcomes=["ductility"],
        ),
    )

    assert [item["document_id"] for item in result.data["likely_relevant"]] == [
        "paper-1"
    ]
    assert [item["document_id"] for item in result.data["needs_inspection"]] == [
        "paper-2"
    ]
    assert result.data["needs_inspection"][0]["map_status"] == "insufficient_map"
    assert [
        item["document_id"] for item in result.data["confidently_out_of_scope"]
    ] == ["paper-3"]
    assert result.data["suggested_scope"] == {
        "seed_document_ids": ["paper-1"],
        "review_document_ids": ["paper-2"],
        "excluded_document_ids": ["paper-3"],
    }
    assert result.data["support_is_evidence"] is False


async def test_scope_preview_maps_energy_input_to_precise_laser_interventions() -> None:
    capability = PreviewResearchScopeCapability(
        collection_service=_CollectionService(),
        paper_map_repository=_PaperMapRepository(),
    )

    result = await capability.execute(
        _context("call-energy-input-scope"),
        capability.spec.input_model(
            question="How does energy input affect ductility?",
            material_scope=["Ti-6Al-4V"],
            variables=["energy input (laser power, scan speed, energy density)"],
            outcomes=["ductility"],
        ),
    )

    assert [item["document_id"] for item in result.data["likely_relevant"]] == [
        "paper-1"
    ]
    assert result.data["needs_inspection"] == []
    assert result.data["confidently_out_of_scope"] == []
    assert result.data["suggested_scope"] == {
        "seed_document_ids": ["paper-1"],
        "review_document_ids": [],
        "excluded_document_ids": [],
    }


async def test_scope_preview_does_not_exclude_a_same_material_paper_for_an_umbrella_variable_miss() -> None:
    same_material_unmatched = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-unmatched",
            "doc_role": "experimental",
            "map_status": "sufficient",
            "studies": [
                {
                    "study_id": "study-unmatched",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["metal additively manufactured material"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-unmatched",
                            "varied_factors": ["solution treatment temperature"],
                            "outcome": "corrosion potential",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-unmatched",
                                }
                            ],
                            "confidence": 0.88,
                        }
                    ],
                }
            ],
        }
    )
    capability = PreviewResearchScopeCapability(
        collection_service=_CollectionService(),
        paper_map_repository=_PaperMapRepository((same_material_unmatched,)),
    )

    result = await capability.execute(
        _context("call-umbrella-miss"),
        capability.spec.input_model(
            question="How does energy input affect ductility?",
            material_scope=["Ti-6Al-4V"],
            variables=["energy input (laser power, scan speed, energy density)"],
            outcomes=["ductility"],
        ),
    )

    assert result.data["likely_relevant"] == []
    assert result.data["confidently_out_of_scope"] == []
    assert result.data["needs_inspection"][0]["document_id"] == "paper-unmatched"
    assert result.data["needs_inspection"][0]["reason"] == (
        "umbrella_scope_not_established"
    )
    assert result.data["suggested_scope"] == {
        "seed_document_ids": [],
        "review_document_ids": ["paper-unmatched"],
        "excluded_document_ids": [],
    }


async def test_scope_preview_does_not_promote_a_review_citation_lead_to_evidence() -> None:
    review = PaperResearchMap.from_mapping(
        {
            "document_id": "review-1",
            "doc_role": "review",
            "map_status": "sufficient",
            "review_synthesis": {
                "citation_leads": [
                    {
                        "content": "Smith et al. studied laser power and elongation.",
                        "material_scope": ["Ti-6Al-4V"],
                        "variables": ["laser power"],
                        "outcomes": ["elongation"],
                        "source_refs": [
                            {"source_kind": "block", "source_ref": "review-block-1"}
                        ],
                        "confidence": 0.9,
                    }
                ]
            },
        }
    )
    capability = PreviewResearchScopeCapability(
        collection_service=_CollectionService(),
        paper_map_repository=_PaperMapRepository((review,)),
    )

    result = await capability.execute(
        _context("call-review-scope"),
        capability.spec.input_model(
            question="How does laser power affect elongation?",
            material_scope=["Ti-6Al-4V"],
            variables=["laser power"],
            outcomes=["elongation"],
        ),
    )

    assert result.data["likely_relevant"] == []
    assert result.data["needs_inspection"][0]["document_id"] == "review-1"
    assert result.data["needs_inspection"][0]["reason"] == "citation_lead_only"


async def test_core_authoring_without_discovery_persists_a_seedless_question_as_untested() -> None:
    repository = _ObjectiveAuthoringRepository()
    repository.facts = ObjectiveFactSet()
    service = ResearchObjectiveService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        paper_map_repository=SimpleNamespace(),
        objective_repository=repository,
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
        paper_map_service=SimpleNamespace(),
    )

    created = await service.create_chat_assisted_candidate(
        collection_id="col-1",
        user_id="user-1",
        tool_call_id="call-untested",
        question="How does oxygen content affect elongation?",
        material_scope=["Ti-6Al-4V"],
        variables=["oxygen content"],
        outcomes=["elongation"],
        mechanisms=[],
        constraints=[],
        requested_comparator=None,
        seed_document_ids=[],
        excluded_document_ids=[],
    )

    assert created.seed_document_ids == ()
    assert created.confidence == 0
    assert created.reason == (
        "User-approved untested research question; no question-source paper was "
        "recorded and analysis has not tested Evidence support."
    )


async def test_core_authoring_rejects_a_seed_document_outside_the_collection() -> None:
    repository = _ObjectiveAuthoringRepository()
    service = ResearchObjectiveService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        paper_map_repository=SimpleNamespace(),
        objective_repository=repository,
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
        paper_map_service=SimpleNamespace(),
    )

    with pytest.raises(FileNotFoundError, match="document not found"):
        await service.create_chat_assisted_candidate(
            collection_id="col-1",
            user_id="user-1",
            tool_call_id="call-unknown-seed",
            question="How does oxygen content affect elongation?",
            material_scope=["Ti-6Al-4V"],
            variables=["oxygen content"],
            outcomes=["elongation"],
            mechanisms=[],
            constraints=[],
            requested_comparator=None,
            seed_document_ids=["paper-outside-collection"],
            excluded_document_ids=[],
        )


class _ObjectiveAnalysisCapabilityService:
    def __init__(self) -> None:
        self.start_calls: list[tuple[str, str, tuple[str, ...]]] = []
        self.read_calls: list[tuple[str, str]] = []
        self.dispatch_error: ObjectiveAnalysisDispatchError | None = None
        self.analysis_status = "queued"
        self.inspection_status = "running"

    async def start_analysis(
        self,
        collection_id: str,
        objective_id: str,
        document_ids: tuple[str, ...],
    ) -> dict:
        self.start_calls.append((collection_id, objective_id, document_ids))
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return self._payload(status=self.analysis_status)

    async def get_analysis_state(self, collection_id: str, objective_id: str) -> dict:
        self.read_calls.append((collection_id, objective_id))
        return self._payload(status=self.inspection_status)

    @staticmethod
    def _payload(*, status: str) -> dict:
        objective = _objective("objective-agent")
        analysis = SimpleNamespace(
            analysis_version=1,
            status=status,
            phase="paper_framing" if status == "running" else "queued",
            processed_document_count=2 if status == "running" else 0,
            total_document_count=10,
            current_document_id="paper-2" if status == "running" else None,
            progress_message="Inspecting paper scope." if status == "running" else None,
            error_code=("analysis_dispatch_failed" if status == "failed" else None),
            error_message=(
                "Objective analysis could not be scheduled. Retry the analysis."
                if status == "failed"
                else None
            ),
        )
        return {
            "collection_id": "col-1",
            "objective": objective,
            "analysis": analysis,
            "published_analysis": None,
            "warnings": [],
        }


class _ObjectiveAnalysisModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        assert messages
        assert {item.name for item in tool_specs} == {"start_objective_analysis"}
        return self.turns.popleft()


async def test_agent_starts_objective_analysis_only_after_exact_approval() -> None:
    analysis_service = _ObjectiveAnalysisCapabilityService()
    capability = StartObjectiveAnalysisCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=analysis_service,
    )
    model = _ObjectiveAnalysisModel(
        ModelTurn(
            content="This question is ready for your approval.",
            tool_call=ModelToolCall(
                name="start_objective_analysis",
                arguments={
                    "objective_id": "objective-agent",
                    "document_ids": ["paper-1"],
                },
            ),
        ),
        ModelTurn(content="The question is queued for evidence analysis."),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((capability,)),
    )

    proposed = await runner.run_turn(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=(),
        user_message="Analyze this research question.",
    )

    assert proposed.status.value == "approval_required"
    assert analysis_service.start_calls == []
    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-08-25T08:00:00+00:00",
    )
    completed = await runner.resume_approved_call(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=proposed.messages,
        approved_call=approved,
    )

    assert analysis_service.start_calls == [
        ("col-1", "objective-agent", ("paper-1",))
    ]
    assert completed.tool_results[0].status.value == "queued"
    assert completed.tool_results[0].data["analysis"]["status"] == "queued"


async def test_agent_reports_persisted_state_when_analysis_dispatch_fails() -> None:
    analysis_service = _ObjectiveAnalysisCapabilityService()
    analysis_service.dispatch_error = ObjectiveAnalysisDispatchError(
        "col-1",
        "objective-agent",
        1,
    )
    analysis_service.inspection_status = "failed"
    capability = StartObjectiveAnalysisCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=analysis_service,
    )

    result = await capability.execute(
        _context("call-analysis-dispatch-failed"),
        capability.spec.input_model(
            objective_id="objective-agent",
            document_ids=["paper-1"],
        ),
    )

    assert result.status.value == "failed"
    assert result.error_code == "analysis_dispatch_failed"
    assert result.data["analysis"]["status"] == "failed"
    assert analysis_service.read_calls == [("col-1", "objective-agent")]


async def test_agent_inspects_the_canonical_objective_analysis_state_read_only() -> None:
    analysis_service = _ObjectiveAnalysisCapabilityService()
    capability = InspectObjectiveAnalysisCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=analysis_service,
    )

    result = await capability.execute(
        _context("call-inspect-analysis"),
        capability.spec.input_model(objective_id="objective-agent"),
    )

    assert capability.spec.risk.value == "read"
    assert analysis_service.read_calls == [("col-1", "objective-agent")]
    assert result.data["analysis"] == {
        "analysis_version": 1,
        "status": "running",
        "phase": "paper_framing",
        "document_progress": {"current": 2, "total": 10},
        "current_document_id": "paper-2",
        "progress_message": "Inspecting paper scope.",
        "error_code": None,
        "error_message": None,
    }


async def test_researcher_question_follows_scope_two_approvals_and_canonical_analysis() -> None:
    insufficient = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-2",
            "doc_role": "experimental",
            "studies": [],
            "map_status": "insufficient_map",
            "map_limitations": ["missing_outcome"],
        }
    )
    paper_map_repository = _PaperMapRepository(
        (
            PaperResearchMap.from_mapping(
                {**_skim().to_record(), "map_status": "sufficient"}
            ),
            insufficient,
        )
    )
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "objective-agent",
            "question": "How do laser power and scan speed affect ductility?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power", "scan speed"],
            "outcomes": ["ductility"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0,
            "origin": "chat_assisted",
            "created_by_user_id": "user-1",
            "created_by_tool_call_id": "call-create",
        }
    )
    authoring_service = _ObjectiveAuthoringService(objective)
    analysis_service = _ObjectiveAnalysisCapabilityService()

    class ScenarioModel:
        def __init__(self) -> None:
            self.turns = deque(
                (
                    ModelTurn(
                        tool_call=ModelToolCall(
                            name="preview_research_scope",
                            arguments={
                                "question": objective.question,
                                "material_scope": ["Ti-6Al-4V"],
                                "variables": ["laser power", "scan speed"],
                                "outcomes": ["ductility"],
                            },
                        )
                    ),
                    ModelTurn(
                        tool_call=ModelToolCall(
                            name="create_objective_candidate",
                            arguments={
                                "question": objective.question,
                                "material_scope": ["Ti-6Al-4V"],
                                "variables": ["laser power", "scan speed"],
                                "outcomes": ["ductility"],
                                "seed_document_ids": ["paper-1"],
                            },
                        )
                    ),
                    ModelTurn(
                        tool_call=ModelToolCall(
                            name="start_objective_analysis",
                            arguments={
                                "objective_id": "objective-agent",
                                "document_ids": ["paper-1"],
                            },
                        )
                    ),
                    ModelTurn(
                        tool_call=ModelToolCall(
                            name="inspect_objective_analysis",
                            arguments={"objective_id": "objective-agent"},
                        )
                    ),
                    ModelTurn(content="Evidence analysis is running for the approved question."),
                )
            )

        def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
            assert messages
            assert {item.name for item in tool_specs} == {
                "preview_research_scope",
                "create_objective_candidate",
                "start_objective_analysis",
                "inspect_objective_analysis",
            }
            return self.turns.popleft()

    runner = ResearchAgentRunner(
        model=ScenarioModel(),
        capabilities=CapabilityRegistry(
            (
                PreviewResearchScopeCapability(
                    collection_service=_CollectionService(),
                    paper_map_repository=paper_map_repository,
                ),
                CreateObjectiveCandidateCapability(
                    research_objective_service=authoring_service,
                ),
                StartObjectiveAnalysisCapability(
                    collection_service=_CollectionService(),
                    objective_analysis_service=analysis_service,
                ),
                InspectObjectiveAnalysisCapability(
                    collection_service=_CollectionService(),
                    objective_analysis_service=analysis_service,
                ),
            )
        ),
    )
    context = AgentContext("chat-1", "user-1", "col-1")

    objective_proposal = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message=objective.question,
    )

    scope = objective_proposal.tool_results[0]
    assert scope.data["support_is_evidence"] is False
    assert scope.data["suggested_scope"]["review_document_ids"] == ["paper-2"]
    assert objective_proposal.pending_approval.name == "create_objective_candidate"

    approved_objective = objective_proposal.pending_approval.approve(
        user_id="user-1",
        arguments_digest=objective_proposal.pending_approval.arguments_digest,
        decided_at="2026-08-25T08:00:00+00:00",
    )
    analysis_proposal = await runner.resume_approved_call(
        context=context,
        previous_messages=objective_proposal.messages,
        approved_call=approved_objective,
    )

    assert analysis_proposal.tool_results[0].data["research_status"] == "untested"
    assert analysis_service.start_calls == []
    assert analysis_proposal.pending_approval.name == "start_objective_analysis"

    approved_analysis = analysis_proposal.pending_approval.approve(
        user_id="user-1",
        arguments_digest=analysis_proposal.pending_approval.arguments_digest,
        decided_at="2026-08-25T08:01:00+00:00",
    )
    completed = await runner.resume_approved_call(
        context=context,
        previous_messages=analysis_proposal.messages,
        approved_call=approved_analysis,
    )

    assert analysis_service.start_calls == [
        ("col-1", "objective-agent", ("paper-1",))
    ]
    assert analysis_service.read_calls == [("col-1", "objective-agent")]
    assert [result.status.value for result in completed.tool_results] == [
        "queued",
        "succeeded",
    ]
    assert completed.tool_results[-1].data["analysis"]["status"] == "running"
    assert completed.messages[-1].content.startswith("Evidence analysis is running")


async def test_core_authoring_keeps_seed_documents_as_question_provenance() -> None:
    repository = _ObjectiveAuthoringRepository()
    service = ResearchObjectiveService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        paper_map_repository=SimpleNamespace(),
        objective_repository=repository,
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
        paper_map_service=SimpleNamespace(),
    )

    created = await service.create_chat_assisted_candidate(
        collection_id="col-1",
        user_id="user-1",
        tool_call_id="call-create",
        question="How do laser power and scan speed affect elongation?",
        material_scope=["Ti-6Al-4V"],
        variables=["laser power", "scan speed"],
        outcomes=["elongation"],
        mechanisms=[],
        constraints=[],
        requested_comparator=None,
        seed_document_ids=["paper-1"],
        excluded_document_ids=[],
    )

    assert created.origin == "chat_assisted"
    assert created.confidence == 0
    assert created.confirmation_status == "candidate"
    assert repository.created[0]["objective"].source_relationship_ids == ()
    assert created.reason == (
        "User-approved untested research question with 1 question-source paper(s); "
        "question provenance is not Evidence and analysis has not tested support."
    )

    unsupported = await service.create_chat_assisted_candidate(
        collection_id="col-1",
        user_id="user-1",
        tool_call_id="call-unsupported",
        question="How does oxygen content affect elongation?",
        material_scope=["Ti-6Al-4V"],
        variables=["oxygen content"],
        outcomes=["elongation"],
        mechanisms=[],
        constraints=[],
        requested_comparator=None,
        seed_document_ids=["paper-1"],
        excluded_document_ids=[],
    )

    assert unsupported.confidence == 0


async def test_agent_uses_collection_context_then_records_drafts_before_final_answer() -> None:
    repository = _ObjectiveRepository((_objective("objective-existing"),))
    collection_service = _CollectionService()
    model = _Model(
        ModelTurn(
            tool_call=ModelToolCall(
                name="get_collection_context",
                arguments={},
            )
        ),
        ModelTurn(
            tool_call=ModelToolCall(
                name="propose_objective_drafts",
                arguments={
                    "drafts": [
                        {
                            "question": "How do laser power and scan speed affect elongation?",
                            "material_scope": ["Ti-6Al-4V"],
                            "variables": ["laser power", "scan speed"],
                            "outcomes": ["elongation"],
                        }
                    ]
                },
            )
        ),
        ModelTurn(content="I prepared one focused Objective draft for your review."),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                GetCollectionContextCapability(
                    collection_service=collection_service,
                    objective_repository=repository,
                ),
                QueryPublishedFindingsCapability(
                    collection_service=collection_service,
                    objective_repository=repository,
                    objective_analysis_service=_AnalysisService(),
                ),
                ProposeObjectiveDraftsCapability(
                    collection_service=collection_service,
                    objective_repository=repository,
                    paper_map_repository=_PaperMapRepository(),
                ),
            )
        ),
    )

    result = await runner.run_turn(
        context=AgentContext(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
        ),
        previous_messages=(),
        user_message="Propose a focused question about process parameters and ductility.",
    )

    assert result.status.value == "completed"
    assert [call.status.value for call in result.tool_calls] == [
        "succeeded",
        "succeeded",
    ]
    assert result.tool_results[1].data["persistence"] == "transient_chat_result"
    assert result.messages[-1].content.startswith("I prepared")
    assert [message.role.value for message in model.contexts[-1][-2:]] == [
        "assistant",
        "tool",
    ]

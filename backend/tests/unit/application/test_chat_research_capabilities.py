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
    GetCollectionContextCapability,
    InspectResearchProcessCapability,
    ProposeObjectiveDraftsArguments,
    ProposeObjectiveDraftsCapability,
    QueryPublishedFindingsCapability,
)
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from domain.core import (
    ObjectiveFactSet,
    PaperSkim,
    PaperStudyDisposition,
    ResearchObjective,
)

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


def _skim() -> PaperSkim:
    return PaperSkim.from_mapping(
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
        }


class _ObjectiveRepository:
    def __init__(self, objectives: tuple[ResearchObjective, ...]) -> None:
        self.objectives = objectives
        self.facts = ObjectiveFactSet(paper_skims=(_skim(),))

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
            paper_skims=(_skim(),),
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
                "source_build_id": "build-1",
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


async def test_research_process_projects_canonical_task_without_retry_internals() -> None:
    task_service = _TaskService(
        [
            {
                "task_id": "task-1",
                "status": "running",
                "current_stage": "objective_paper_skim_started",
                "progress_percent": 72,
                "progress_detail": {
                    "phase": "objective_paper_skim_started",
                    "message": "Screening paper Sources for research themes.",
                    "current": 3,
                    "total": 10,
                    "active_document_id": "paper-3",
                    "active_document_title": "LPBF process review",
                    "active_window_position": 41,
                    "active_window_count": 96,
                    "retry_attempt": 7,
                },
                "pipeline_nodes": {
                    "source_artifacts": {"status": "succeeded"},
                    "document_profiles": {"status": "succeeded"},
                    "objective_candidates": {"status": "running"},
                },
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
    assert result.data["process"]["status"] == "running"
    assert result.data["process"]["current_step"] == "research_scope_screening"
    assert result.data["process"]["document_progress"] == {"current": 3, "total": 10}
    assert result.data["process"]["active_document"] == {
        "document_id": "paper-3",
        "title": "LPBF process review",
    }
    assert [step["status"] for step in result.data["process"]["steps"]] == [
        "completed",
        "completed",
        "running",
        "queued",
    ]
    assert "active_window_position" not in str(result.data)
    assert "retry_attempt" not in str(result.data)
    assert result.warnings == ("One paper could not be parsed.",)
    assert task_service.calls == [
        {"collection_id": "col-1", "limit": 1, "offset": 0}
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
        "current_step": None,
        "summary": "Literature analysis has not started.",
        "progress_percent": 0,
        "document_progress": None,
        "active_document": None,
        "steps": [
            {"step_id": "source_understanding", "status": "queued"},
            {"step_id": "paper_classification", "status": "queued"},
            {"step_id": "research_scope_screening", "status": "queued"},
            {"step_id": "objective_formation", "status": "queued"},
        ],
        "failures": [],
    }


@pytest.mark.parametrize(
    ("task_status", "node_status", "expected_summary", "expected_step_status"),
    (
        (
            "completed",
            "succeeded",
            "Paper preparation and candidate research-question synthesis "
            "are complete.",
            "completed",
        ),
        (
            "partial_success",
            "succeeded",
            "Literature analysis is complete, but some content still needs review.",
            "completed",
        ),
        (
            "failed",
            "failed",
            "Literature analysis stopped before all stages were complete.",
            "failed",
        ),
    ),
)
async def test_research_process_keeps_terminal_runtime_outcomes_distinct(
    task_status: str,
    node_status: str,
    expected_summary: str,
    expected_step_status: str,
) -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        task_service=_TaskService(
            [
                {
                    "task_id": "task-terminal",
                    "status": task_status,
                    "progress_percent": 100,
                    "progress_detail": {"message": "Build artifacts are ready."},
                    "pipeline_nodes": {
                        "source_artifacts": {"status": node_status},
                        "document_profiles": {"status": node_status},
                        "objective_candidates": {"status": node_status},
                    },
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
    assert result.data["process"]["status"] == task_status
    assert result.data["process"]["summary"] == expected_summary
    assert result.data["process"]["steps"][-1]["status"] == expected_step_status
    assert result.data["process"]["current_step"] == (
        "source_understanding" if task_status == "failed" else None
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
                                "status": "running",
                                "progress_percent": 72,
                                "progress_detail": {
                                    "phase": "objective_paper_skim_started",
                                    "current": 3,
                                    "total": 10,
                                },
                                "pipeline_nodes": {
                                    "source_artifacts": {"status": "succeeded"},
                                    "document_profiles": {"status": "succeeded"},
                                    "objective_candidates": {"status": "running"},
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
    assert result.tool_results[0].data["process"]["current_step"] == (
        "research_scope_screening"
    )
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


async def test_objective_drafts_are_transient_and_paper_skim_is_not_evidence() -> None:
    capability = ProposeObjectiveDraftsCapability(
        collection_service=_CollectionService(),
        objective_repository=_ObjectiveRepository((_objective("objective-existing"),)),
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
    assert result.data["drafts"][0]["support_status"] == "paper_skim_context"
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
            "source_build_id": "build-1",
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
        "source_build_id": "build-1",
        "analysis_started": False,
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


async def test_core_authoring_requires_seed_relationship_support_and_derives_confidence() -> None:
    repository = _ObjectiveAuthoringRepository()
    service = ResearchObjectiveService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        paper_fact_repository=SimpleNamespace(),
        objective_repository=repository,
        document_profile_service=SimpleNamespace(),
        finding_synthesis_service=SimpleNamespace(),
        paper_skim_service=SimpleNamespace(),
        objective_candidate_service=SimpleNamespace(),
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
    assert created.confidence == pytest.approx(0.86)
    assert created.confirmation_status == "candidate"
    assert repository.created[0]["objective"].source_relationship_ids == ()

    with pytest.raises(ValueError, match="seed PaperSkim context"):
        await service.create_chat_assisted_candidate(
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

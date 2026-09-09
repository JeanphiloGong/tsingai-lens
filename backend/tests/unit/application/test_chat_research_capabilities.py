from __future__ import annotations

from collections import deque
from dataclasses import replace
from hashlib import sha256
import json
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
    AssessObjectiveQualityCapability,
    BrowseCollectionPapersCapability,
    CreateEvidenceDraftCapability,
    CreateEvidenceDraftArguments,
    PublishAgentObjectiveAnalysisCapability,
    CreateEvidenceVersionArguments,
    CreateEvidenceVersionCapability,
    CreateFindingVersionArguments,
    CreateFindingVersionCapability,
    CreateFindingDraftArguments,
    CreateFindingDraftCapability,
    CreateObjectiveCandidateArguments,
    CreateObjectiveCandidateCapability,
    ConfirmObjectiveCapability,
    CurateFindingCapability,
    DeriveObjectiveCapability,
    GetCollectionContextCapability,
    InspectDocumentSourcesCapability,
    InspectTableArguments,
    InspectTableCapability,
    ReadSourceCapability,
    InspectObjectiveAnalysisCapability,
    InspectPublishedFindingCapability,
    InspectResearchProcessCapability,
    PreviewResearchScopeCapability,
    ProposeObjectiveDraftsArguments,
    ProposeObjectiveDraftsCapability,
    QueryPublishedFindingsCapability,
    RecordFindingFeedbackCapability,
    SearchSourcesCapability,
    StartObjectiveAnalysisArguments,
    StartObjectiveAnalysisCapability,
    StartResearchProcessArguments,
    StartResearchProcessCapability,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from application.core.objectives.objective_authoring_service import (
    ObjectiveAuthoringService,
)
from application.core.objectives.objective_analysis_service import (
    ObjectiveEvidenceAnalysisService,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisDispatchError
from domain.core import (
    DocumentProfile,
    ObjectiveFactSet,
    PaperResearchMap,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.source import SourceBlock, SourceDocument, SourceFigure, SourceTable
from tests.unit.services.test_evaluation_services import (
    _published_objective_repository,
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
                    "original_filename": "energy-input-tensile.pdf",
                },
                {
                    "document_id": "paper-2",
                    "status": "stored",
                    "original_filename": "residual-stress-review.pdf",
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


class _GoldCollectionService:
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        if collection_id != "col-gold" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}


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

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        assert collection_id == "col-1"
        return next(
            (item for item in self.objectives if item.objective_id == objective_id),
            None,
        )


class _PipelineRunService:
    def __init__(self, runs: list[dict]) -> None:
        self.runs = runs
        self.calls: list[dict] = []

    async def list_runs(self, **kwargs) -> list[dict]:
        self.calls.append(kwargs)
        return self.runs


class _DocumentPreparationService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def queue_document_preparation(
        self, collection_id: str, document_id: str, **kwargs
    ) -> dict:
        self.calls.append(
            {"collection_id": collection_id, "document_id": document_id, **kwargs}
        )
        return {
            "run_id": f"run-{document_id}",
            "collection_id": collection_id,
            "pipeline_name": "document_preparation",
            "scope_type": "document",
            "scope_id": document_id,
            "status": "queued",
            "mode": "standard",
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


class _DocumentProfileRepository:
    def __init__(self) -> None:
        self.profiles = (
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "title": "Energy input and tensile response",
                    "doc_type": "experimental",
                    "profile_warnings": [],
                    "confidence": 0.94,
                }
            ),
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-2",
                    "title": "Residual stress in additive manufacturing",
                    "doc_type": "review",
                    "profile_warnings": ["Abstract heading was not preserved."],
                    "confidence": 0.72,
                }
            ),
        )

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        assert collection_id == "col-1"
        selected = set(document_ids) if document_ids is not None else None
        return tuple(
            item
            for item in self.profiles
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
                    header_row_count=0,
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

    async def read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[SourceDocument, ...]:
        assert collection_id == "col-1"
        return tuple(
            self.document
            for document_id in document_ids
            if document_id == self.document.document_id
        )


class _AbstractSourceArtifactRepository(_SourceArtifactRepository):
    def __init__(self) -> None:
        super().__init__()
        abstract = SourceBlock(
            block_id="block-abstract",
            document_id="paper-1",
            block_type="paragraph",
            text=(
                "This study evaluates laser energy input and the tensile "
                "response of additively manufactured Ti-6Al-4V."
            ),
            block_order=0,
            page=1,
            heading_path="Abstract",
        )
        self.document = replace(
            self.document,
            blocks=(abstract, *self.document.blocks),
        )

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
        "origin": "system_generated",
        "source_analysis_version": None,
        "parent_finding_id": None,
        "created_by_user_id": None,
        "created_by_tool_call_id": None,
        "created_at": None,
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

    async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
        messages = context.messages
        assert messages
        if self.turns[0].tool_calls != ():
            assert {item.name for item in tool_specs} == {"start_research_process"}
        else:
            assert tool_specs == ()
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


class _ObjectiveConfirmationService:
    def __init__(self, objective: ResearchObjective) -> None:
        self.objective = objective
        self.calls: list[dict] = []

    async def confirm_objective(self, **kwargs) -> ResearchObjective:
        self.calls.append(kwargs)
        return replace(self.objective, confirmation_status="confirmed")


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
                    "supports_finding": True,
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

    async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
        messages = context.messages
        self.contexts.append(messages)
        assert {item.name for item in tool_specs} == {
            "get_collection_context",
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


async def test_collection_paper_browser_joins_screening_context_without_calling_it_evidence() -> None:
    capability = BrowseCollectionPapersCapability(
        collection_service=_CollectionService(),
        document_profile_repository=_DocumentProfileRepository(),
        paper_map_repository=_PaperMapRepository(),
        source_artifact_repository=_AbstractSourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-paper-browser"),
        capability.spec.input_model(offset=0, limit=2),
    )

    assert result.status.value == "succeeded"
    assert result.data["paper_total"] == 2
    assert result.data["returned_paper_count"] == 2
    assert result.data["next_offset"] is None
    assert result.data["support_is_evidence"] is False
    first, second = result.data["papers"]
    assert first["document_id"] == "paper-1"
    assert first["filename"] == "energy-input-tensile.pdf"
    assert first["title"] == "Energy input and tensile response"
    assert first["document_type"] == "experimental"
    assert first["paper_role"] == "experimental"
    assert first["materials"] == ["Ti-6Al-4V"]
    assert first["processes"] == []
    assert first["variables"] == ["laser power", "scan speed"]
    assert first["outcomes"] == ["elongation"]
    assert first["abstract_excerpt"].startswith("This study evaluates")
    assert first["screening_only"] is True
    assert second["document_id"] == "paper-2"
    assert second["map_status"] == "not_available"
    assert second["abstract_excerpt"] is None
    assert second["screening_limitations"]
    assert {ref.resource_type for ref in result.resource_refs} == {
        "collection",
        "document",
    }


async def test_collection_paper_browser_filters_by_visible_identity_and_paginates() -> None:
    capability = BrowseCollectionPapersCapability(
        collection_service=_CollectionService(),
        document_profile_repository=_DocumentProfileRepository(),
        paper_map_repository=_PaperMapRepository(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-paper-filter"),
        capability.spec.input_model(query="residual-stress", limit=1),
    )

    assert result.data["paper_total"] == 1
    assert result.data["papers"][0]["document_id"] == "paper-2"
    assert result.data["papers"][0]["filename"] == "residual-stress-review.pdf"
    assert result.data["papers"][0]["abstract_status"] == "source_not_ready"
    assert result.warnings


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
    assert "bounded table Markdown" in InspectDocumentSourcesCapability.spec.description
    assert "complete table Markdown" not in InspectDocumentSourcesCapability.spec.description
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
    assert result.data["sources"][0]["source_kind"] == "table"
    assert len(result.data["sources"][0]["source_digest"]) == 64
    assert result.data["sources"][1]["source_kind"] == "figure"
    assert [ref.resource_type for ref in result.resource_refs] == [
        "document",
        "source",
        "source",
    ]
    assert "source_ref=table-2" in (result.resource_refs[1].href or "")


async def test_source_search_locates_candidates_without_calling_them_evidence() -> None:
    capability = SearchSourcesCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-search"),
        capability.spec.input_model(
            document_ids=["paper-1"],
            query="elongation",
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["match_total"] == 3
    assert result.data["support_is_evidence"] is False
    assert {item["source_type"] for item in result.data["matches"]} == {
        "text",
        "table",
        "figure",
    }
    assert all(len(item["source_digest"]) == 64 for item in result.data["matches"])
    assert {ref.resource_type for ref in result.resource_refs} == {"source"}


async def test_table_inspection_returns_complete_markdown_before_row_windows() -> None:
    capability = InspectTableCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-table"),
        capability.spec.input_model(
            document_id="paper-1",
            table_ref="table-2",
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["complete_table"] is True
    assert result.data["next_row_offset"] is None
    assert "Low energy" in result.data["table_markdown"]
    assert "High energy" in result.data["table_markdown"]
    assert result.data["support_is_evidence"] is False
    assert len(result.data["source_digest"]) == 64


async def test_table_inspection_does_not_skip_rows_after_an_oversized_row() -> None:
    repository = _SourceArtifactRepository()
    oversized_row = "x" * 13_000
    repository.document = replace(
        repository.document,
        tables=(
            SourceTable(
                table_id="table-large",
                document_id="paper-1",
                table_order=1,
                caption_text="A table containing one oversized row",
                caption_block_id=None,
                page=5,
                heading_path="Results",
                column_headers=("Condition", "Result"),
                table_matrix=(
                    ("first-row", "1"),
                    ("oversized-row", oversized_row),
                    ("after-oversized-row", "3"),
                ),
                header_row_count=0,
            ),
        ),
    )
    capability = InspectTableCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=repository,
    )

    first_window = await capability.execute(
        _context("call-large-table-1"),
        capability.spec.input_model(
            document_id="paper-1",
            table_ref="table-large",
            row_limit=3,
        ),
    )
    blocked_window = await capability.execute(
        _context("call-large-table-2"),
        capability.spec.input_model(
            document_id="paper-1",
            table_ref="table-large",
            row_offset=first_window.data["next_row_offset"],
            row_limit=3,
        ),
    )

    assert first_window.status.value == "succeeded"
    assert "first-row" in first_window.data["table_markdown"]
    assert first_window.data["returned_row_count"] == 1
    assert first_window.data["oversized_row_offset"] == 1
    assert first_window.data["next_row_offset"] == 1
    assert first_window.data["content_truncated"] is True
    assert blocked_window.status.value == "succeeded"
    assert blocked_window.data["returned_row_count"] == 0
    assert blocked_window.data["oversized_row_offset"] == 1
    assert blocked_window.data["next_row_offset"] == 1
    assert "after-oversized-row" not in blocked_window.data["table_markdown"]
    assert blocked_window.warnings


async def test_table_inspection_uses_utf8_bytes_for_the_response_bound() -> None:
    repository = _SourceArtifactRepository()
    repository.document = replace(
        repository.document,
        tables=(
            SourceTable(
                table_id="table-unicode-large",
                document_id="paper-1",
                table_order=1,
                caption_text="A table whose Unicode row exceeds the byte bound",
                caption_block_id=None,
                page=5,
                heading_path="Results",
                column_headers=("Condition", "Result"),
                table_matrix=(("条件", "中" * 5_000),),
                header_row_count=0,
            ),
        ),
    )
    result = await InspectTableCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=repository,
    ).execute(
        _context("call-unicode-large-table"),
        InspectTableArguments(
            document_id="paper-1",
            table_ref="table-unicode-large",
            row_limit=1,
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["complete_table"] is False
    assert result.data["returned_row_count"] == 0
    assert result.data["oversized_row_offset"] == 0
    assert len(result.data["table_markdown"].encode("utf-8")) <= 12_000
    assert result.data["next_row_offset"] == 0


async def test_table_inspection_rejects_a_row_offset_past_the_data_rows() -> None:
    capability = InspectTableCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-table-invalid-offset"),
        InspectTableArguments(
            document_id="paper-1",
            table_ref="table-2",
            row_offset=2,
        ),
    )

    assert result.status.value == "failed"
    assert result.error_code == "table_row_offset_out_of_range"
    assert result.data["row_offset"] == 2
    assert result.data["data_row_count"] == 2
    assert len(result.data["source_digest"]) == 64


async def test_read_source_returns_complete_text_with_stable_digest() -> None:
    capability = ReadSourceCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )

    result = await capability.execute(
        _context("call-read-source"),
        capability.spec.input_model(
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-result",
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["source_kind"] == "text_window"
    assert result.data["source_ref"] == "block-result"
    assert result.data["content"] == (
        "Elongation decreased as the combined energy input increased."
    )
    assert result.data["complete_source"] is True
    assert result.data["content_truncated"] is False
    assert result.data["next_offset"] is None
    assert result.data["source_digest"] == sha256(
        result.data["content"].encode("utf-8")
    ).hexdigest()
    assert result.data["support_is_evidence"] is False
    assert result.resource_refs[0].resource_type == "source"


async def test_read_source_paginates_long_text_without_changing_digest() -> None:
    repository = _SourceArtifactRepository()
    long_text = "A" * 40 + " explicit result context " + "B" * 40
    repository.document = replace(
        repository.document,
        blocks=(
            *repository.document.blocks,
            SourceBlock(
                block_id="block-long",
                document_id="paper-1",
                block_type="paragraph",
                text=long_text,
                block_order=3,
                page=7,
                heading_path="Results",
            ),
        ),
    )
    capability = ReadSourceCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=repository,
    )

    first_page = await capability.execute(
        _context("call-read-source-page"),
        capability.spec.input_model(
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-long",
            limit=40,
        ),
    )

    second_page = await capability.execute(
        _context("call-read-source-page-2"),
        capability.spec.input_model(
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-long",
            offset=first_page.data["next_offset"],
            limit=40,
        ),
    )

    assert first_page.status.value == "succeeded"
    assert first_page.data["content"] == long_text[:40]
    assert first_page.data["content_truncated"] is True
    assert first_page.data["complete_source"] is False
    assert first_page.data["next_offset"] == 40
    assert first_page.data["canonical_length"] == len(long_text)
    assert second_page.status.value == "succeeded"
    assert second_page.data["content"] == long_text[40:80]
    assert second_page.data["content_offset"] == 40
    assert second_page.data["source_digest"] == first_page.data["source_digest"]
    assert first_page.data["source_digest"] == sha256(
        long_text.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("offset_delta", [0, 17])
async def test_read_source_rejects_an_offset_outside_nonempty_canonical_content(
    offset_delta: int,
) -> None:
    repository = _SourceArtifactRepository()
    canonical = repository.document.blocks[1].text
    capability = ReadSourceCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=repository,
    )

    requested_offset = len(canonical) + offset_delta
    result = await capability.execute(
        _context("call-read-source-invalid-offset"),
        capability.spec.input_model(
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-result",
            offset=requested_offset,
        ),
    )

    assert result.status.value == "failed"
    assert result.error_code == "source_offset_out_of_range"
    assert result.data["requested_offset"] == requested_offset
    assert result.data["canonical_length"] == len(canonical)
    assert result.data["source_digest"] == sha256(canonical.encode("utf-8")).hexdigest()


async def test_source_readers_share_the_complete_canonical_table_digest() -> None:
    repository = _SourceArtifactRepository()
    collection_service = _CollectionService()
    expected_digest = sha256(
        repository.document.tables[0].to_record()["table_markdown"].encode("utf-8")
    ).hexdigest()

    source_list = await InspectDocumentSourcesCapability(
        collection_service=collection_service,
        source_artifact_repository=repository,
    ).execute(
        _context("call-list-table-source"),
        InspectDocumentSourcesCapability.spec.input_model(
            document_id="paper-1",
            source_ref="table-2",
        ),
    )
    search_result = await SearchSourcesCapability(
        collection_service=collection_service,
        source_artifact_repository=repository,
    ).execute(
        _context("call-search-table-source"),
        SearchSourcesCapability.spec.input_model(
            document_ids=["paper-1"],
            query="Low energy",
            source_types=["table"],
        ),
    )
    table_result = await InspectTableCapability(
        collection_service=collection_service,
        source_artifact_repository=repository,
    ).execute(
        _context("call-inspect-table-source"),
        InspectTableCapability.spec.input_model(
            document_id="paper-1",
            table_ref="table-2",
        ),
    )
    exact_source = await ReadSourceCapability(
        collection_service=collection_service,
        source_artifact_repository=repository,
    ).execute(
        _context("call-read-table-source"),
        ReadSourceCapability.spec.input_model(
            document_id="paper-1",
            source_kind="table",
            source_ref="table-2",
        ),
    )

    assert source_list.data["sources"][0]["source_digest"] == expected_digest
    assert search_result.data["matches"][0]["source_digest"] == expected_digest
    assert table_result.data["source_digest"] == expected_digest
    assert exact_source.data["source_digest"] == expected_digest

    evidence_draft = await CreateEvidenceDraftCapability(
        collection_service=collection_service,
        source_artifact_repository=repository,
    ).execute(
        _context("call-draft-from-table-source"),
        CreateEvidenceDraftArguments.model_validate(
            {
                "draft_id": "draft-from-table-source",
                "objective_id": "objective-published",
                "source_analysis_version": 2,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-2",
                "source_excerpt": "Low energy",
                "source_digest": exact_source.data["source_digest"],
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "elongation",
                    "direction": "unknown",
                    "result_text": "Low-energy elongation was reported in the table.",
                },
                "attribution_scope": "descriptive_only",
            }
        ),
    )

    assert evidence_draft.status.value == "succeeded"


async def test_document_source_inspection_handles_an_empty_parser_table() -> None:
    repository = _SourceArtifactRepository()
    repository.document = replace(
        repository.document,
        tables=(
            SourceTable(
                table_id="table-empty",
                document_id="paper-1",
                table_order=1,
                caption_text="A table with no parsed rows",
                caption_block_id=None,
                page=2,
                heading_path="Results",
                column_headers=(),
                table_matrix=(),
                header_row_count=1,
            ),
        ),
    )
    capability = InspectDocumentSourcesCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=repository,
    )

    result = await capability.execute(
        _context("call-empty-table"),
        capability.spec.input_model(
            document_id="paper-1",
            source_types=["table"],
        ),
    )

    assert result.status.value == "succeeded"
    assert result.data["sources"][0]["content"] == ""
    assert result.data["sources"][0]["content_truncated"] is False
    assert result.data["sources"][0]["source_digest"] == sha256(
        b""
    ).hexdigest()


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
                        tool_calls=(ModelToolCall(
                            name="record_finding_feedback",
                            arguments={
                                "objective_id": "objective-published",
                                "analysis_version": 2,
                                "finding_id": "finding-1",
                                "review_status": "partial",
                                "issue_type": "overclaim",
                                "note": "The direction is supported, but the wording is too broad.",
                            },
                        ),),
                    ),
                    ModelTurn(content="The approved review has been recorded."),
                )
            )

        async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
            messages = context.messages
            assert messages
            if self.turns[0].tool_calls != ():
                assert {item.name for item in tool_specs} == {
                    "record_finding_feedback"
                }
            else:
                assert tool_specs == ()
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
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
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


def test_finding_authoring_arguments_separate_finding_and_abstention() -> None:
    authored = CreateFindingVersionArguments(
        objective_id="obj-1",
        source_analysis_version=1,
        statement="Higher temperature is associated with greater strength.",
        assertion_strength="associative",
        supporting_evidence_ids=["evidence-1"],
        limitations=["Only one paper directly supports this conclusion."],
    )
    assert authored.supporting_evidence_ids == ["evidence-1"]
    assert authored.abstention_reason is None

    abstained = CreateFindingVersionArguments(
        objective_id="obj-1",
        source_analysis_version=1,
        abstention_reason="no_comparable_evidence",
        limitations=["The reported test conditions are not comparable."],
    )
    assert abstained.statement is None
    assert abstained.abstention_reason == "no_comparable_evidence"

    with pytest.raises(ValidationError, match="requires supporting Evidence"):
        CreateFindingVersionArguments(
            objective_id="obj-1",
            source_analysis_version=1,
            statement="An unsupported conclusion.",
            assertion_strength="associative",
        )


def test_evidence_authoring_arguments_require_complete_source_and_result_shape() -> None:
    draft = CreateEvidenceVersionArguments(
        objective_id="obj-1",
        source_analysis_version=1,
        document_id="paper-1",
        source_kind="text_window",
        source_ref="block-result",
        source_excerpt="Elongation decreased as the combined energy input increased.",
        source_digest="a" * 64,
        evidence_role="direct_result",
        changed_variables=[{"name": "energy input"}],
        comparison=None,
        reported_result={
            "outcome": "elongation",
            "direction": "decrease",
            "result_text": "Elongation decreased.",
        },
        attribution_scope="association_only",
    )
    assert draft.source_digest == "a" * 64

    with pytest.raises(ValidationError, match="String should match pattern"):
        CreateEvidenceVersionArguments(
            objective_id="obj-1",
            source_analysis_version=1,
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-result",
            source_excerpt="Elongation decreased.",
            source_digest="z" * 64,
            evidence_role="direct_result",
            attribution_scope="association_only",
        )

    with pytest.raises(ValidationError, match="requires a reported result"):
        CreateEvidenceVersionArguments(
            objective_id="obj-1",
            source_analysis_version=1,
            document_id="paper-1",
            source_kind="text_window",
            source_ref="block-result",
            source_excerpt="Elongation decreased.",
            source_digest="a" * 64,
            evidence_role="direct_result",
            attribution_scope="association_only",
        )


async def test_agent_evidence_write_waits_for_approval_and_reuses_service() -> None:
    class _EvidenceService:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def create_version(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                analysis=SimpleNamespace(
                    analysis_version=2,
                    to_record=lambda: {"analysis_version": 2, "status": "succeeded"},
                ),
                evidence=SimpleNamespace(
                    evidence_id="evidence-manual-1",
                    page_numbers=(5,),
                    warnings=("reported_result.unit is not grounded in Source",),
                    to_record=lambda: {
                        "evidence_id": "evidence-manual-1",
                        "analysis_version": 2,
                        "source_ref": "block-result",
                        "warnings": [
                            "reported_result.unit is not grounded in Source"
                        ],
                    },
                    supports_finding=True,
                ),
            )

    evidence_service = _EvidenceService()
    capability = CreateEvidenceVersionCapability(
        evidence_authoring_service=evidence_service,
    )
    arguments = capability.spec.input_model(
        objective_id="obj-1",
        source_analysis_version=1,
        document_id="paper-1",
        source_kind="text_window",
        source_ref="block-result",
        source_excerpt="Elongation decreased as the combined energy input increased.",
        source_digest="a" * 64,
        evidence_role="direct_result",
        changed_variables=[{"name": "energy input"}],
        reported_result={
            "outcome": "elongation",
            "direction": "decrease",
            "result_text": "Elongation decreased.",
        },
        attribution_scope="association_only",
    )
    result = await capability.execute(_context("call-evidence"), arguments)
    assert capability.spec.risk.value == "write"
    assert result.data["evidence"]["evidence_id"] == "evidence-manual-1"
    assert result.resource_refs[0].resource_type == "objective_analysis"
    assert result.resource_refs[1].resource_type == "evidence"
    assert evidence_service.calls[0]["created_by_user_id"] == "user-1"
    assert evidence_service.calls[0]["created_by_tool_call_id"] == "call-evidence"
    assert evidence_service.calls[0]["source_digest"] == "a" * 64
    assert result.warnings == (
        "reported_result.unit is not grounded in Source",
    )


async def test_evidence_draft_is_source_checked_and_not_persisted() -> None:
    source_repository = _SourceArtifactRepository()
    canonical = source_repository.document.blocks[1].text
    capability = CreateEvidenceDraftCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=source_repository,
    )
    arguments = CreateEvidenceDraftArguments.model_validate(
        {
            "draft_id": "draft-evidence-1",
            "objective_id": "objective-published",
            "source_analysis_version": 2,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-result",
            "source_excerpt": "Elongation decreased as the combined energy input increased.",
            "source_digest": sha256(canonical.encode("utf-8")).hexdigest(),
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "elongation",
                "direction": "decrease",
                "result_text": "Elongation decreased.",
            },
            "attribution_scope": "association_only",
        }
    )

    result = await capability.execute(_context("call-evidence-draft"), arguments)

    assert result.status.value == "succeeded"
    assert result.data["persistence"] == "transient_chat_result"
    assert result.data["published"] is False
    assert result.data["requires_user_approval"] is True
    assert result.data["support_is_evidence"] is False
    assert result.data["draft"]["draft_id"] == "draft-evidence-1"
    assert [ref.resource_type for ref in result.resource_refs] == ["source"]


async def test_evidence_draft_rejects_excerpt_not_in_canonical_source() -> None:
    capability = CreateEvidenceDraftCapability(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
    )
    arguments = CreateEvidenceDraftArguments.model_validate(
        {
            "draft_id": "draft-evidence-invalid",
            "objective_id": "objective-published",
            "source_analysis_version": 2,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-result",
            "source_excerpt": "The paper proves a causal increase.",
            "source_digest": sha256(
                _SourceArtifactRepository().document.blocks[1].text.encode("utf-8")
            ).hexdigest(),
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "elongation",
                "direction": "increase",
                "result_text": "The paper proves a causal increase.",
            },
            "attribution_scope": "association_only",
        }
    )

    result = await capability.execute(_context("call-evidence-invalid"), arguments)

    assert result.status.value == "failed"
    assert result.error_code == "source_excerpt_not_grounded"


async def test_finding_draft_is_transient_and_requires_published_evidence_validation() -> None:
    arguments = CreateFindingDraftArguments.model_validate(
        {
            "draft_id": "draft-finding-1",
            "objective_id": "objective-published",
            "source_analysis_version": 2,
            "statement": "Higher energy input was associated with lower elongation.",
            "assertion_strength": "associative",
            "supporting_evidence_ids": ["evidence-1"],
            "limitations": ["Only one paper is currently available."],
        }
    )
    capability = CreateFindingDraftCapability()

    result = await capability.execute(_context("call-finding-draft"), arguments)

    assert result.status.value == "succeeded"
    assert result.data["persistence"] == "transient_chat_result"
    assert result.data["published"] is False
    assert result.data["requires_user_approval"] is True
    assert result.data["requires_evidence_validation"] is True
    assert result.data["draft"]["draft_id"] == "draft-finding-1"
    assert result.resource_refs[0].resource_type == "research_objective"
    with pytest.raises(ValidationError, match="abstention cannot contain"):
        CreateFindingVersionArguments(
            objective_id="obj-1",
            source_analysis_version=1,
            statement="A conclusion must not accompany abstention.",
            assertion_strength="associative",
            supporting_evidence_ids=["evidence-1"],
            abstention_reason="insufficient_evidence",
            limitations=["Evidence is insufficient."],
        )


async def test_agent_objective_analysis_uses_approved_grounded_payload() -> None:
    class _AgentAnalysisService:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def publish(self, **kwargs):
            self.calls.append(kwargs)
            analysis = SimpleNamespace(
                analysis_version=1,
                to_record=lambda: {
                    "analysis_version": 1,
                    "status": "succeeded",
                    "origin": "agent_authored",
                },
            )
            contribution = SimpleNamespace(
                to_record=lambda: {"document_id": "paper-1"}
            )
            evidence = SimpleNamespace(
                evidence_id="evidence-agent-1",
                document_id="paper-1",
                source_ref="block-result",
                warnings=("reported_result.direction needs scientific review",),
                to_record=lambda: {
                    "evidence_id": "evidence-agent-1",
                    "document_id": "paper-1",
                    "origin": "agent_authored",
                    "warnings": [
                        "reported_result.direction needs scientific review"
                    ],
                },
            )
            return SimpleNamespace(
                analysis=analysis,
                contributions=(contribution,),
                evidence_records=(evidence,),
            )

    service = _AgentAnalysisService()
    capability = PublishAgentObjectiveAnalysisCapability(
        agent_analysis_service=service,
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
    )
    arguments = capability.spec.input_model(
        objective_id="obj-1",
        document_ids=["paper-1"],
        paper_summaries=[
            {
                "document_id": "paper-1",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "contribution_summary": "Reports one source-backed result.",
                "confidence": 0.9,
            }
        ],
        evidence_drafts=[
            {
                "draft_id": "draft-1",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "block-result",
                "source_excerpt": "Porosity decreased from 1.8% to 0.7%.",
                "source_digest": "a" * 64,
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
                    "result_text": "Porosity decreased from 1.8% to 0.7%.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "material": [{"name": "alloy", "value": "Ti-6Al-4V"}]
                },
                "confidence": 0.9,
            }
        ],
    )

    result = await capability.execute(_context("call-agent-analysis"), arguments)

    assert capability.spec.risk.value == "write"
    assert result.data["analysis"]["origin"] == "agent_authored"
    assert result.data["evidence_count"] == 1
    assert result.data["finding_count"] == 0
    assert result.warnings == (
        "evidence-agent-1: reported_result.direction needs scientific review",
    )
    assert service.calls == [
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "document_ids": ("paper-1",),
            "paper_summaries": tuple(
                item.model_dump() for item in arguments.paper_summaries
            ),
            "evidence_drafts": tuple(
                item.model_dump() for item in arguments.evidence_drafts
            ),
            "model_name": "zai-org/glm-5.2",
            "prompt_version": "research-agent-v13",
            "created_by_user_id": "user-1",
            "created_by_tool_call_id": "call-agent-analysis",
        }
    ]


async def test_agent_objective_analysis_reports_all_source_extraction_failure() -> None:
    class _FailedAgentAnalysisService:
        async def publish(self, **kwargs):
            analysis = SimpleNamespace(
                analysis_version=2,
                status="failed",
                error_code="agent_analysis_extraction_failed",
                error_message=(
                    "Agent analysis failed to extract every relevant paper."
                ),
                to_record=lambda: {
                    "analysis_version": 2,
                    "status": "failed",
                    "error_code": "agent_analysis_extraction_failed",
                    "error_message": (
                        "Agent analysis failed to extract every relevant paper."
                    ),
                },
            )
            contribution = SimpleNamespace(
                to_record=lambda: {
                    "document_id": "paper-1",
                    "analysis_status": "failed",
                    "evidence_disposition": "extraction_failed",
                }
            )
            return SimpleNamespace(
                analysis=analysis,
                contributions=(contribution,),
                evidence_records=(),
            )

    capability = PublishAgentObjectiveAnalysisCapability(
        agent_analysis_service=_FailedAgentAnalysisService(),
        model_name="zai-org/glm-5.2",
        prompt_version="research-agent-v13",
    )
    arguments = capability.spec.input_model(
        objective_id="obj-1",
        document_ids=["paper-1"],
        paper_summaries=[
            {
                "document_id": "paper-1",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "contribution_summary": "The selected Source could not be extracted.",
                "confidence": 0.5,
                "inspection_outcome": "extraction_failed",
                "inspection_outcome_reason": "Provider returned malformed output.",
                "inspected_source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "block-result",
                    }
                ],
            }
        ],
        evidence_drafts=[],
    )

    result = await capability.execute(_context("call-agent-analysis-failed"), arguments)

    assert result.status.value == "failed"
    assert result.error_code == "agent_analysis_extraction_failed"
    assert result.error_message == (
        "Agent analysis failed to extract every relevant paper."
    )
    assert result.data["analysis"]["status"] == "failed"
    assert result.data["paper_contributions"][0]["evidence_disposition"] == (
        "extraction_failed"
    )
    assert result.warnings == (
        "The Agent analysis failed during technical Source extraction; the previous "
        "published result, if any, remains unchanged.",
    )


async def test_agent_publishes_authored_finding_only_after_exact_approval() -> None:
    repository = await _published_objective_repository()
    capability = CreateFindingVersionCapability(
        finding_authoring_service=FindingAuthoringService(
            collection_service=_GoldCollectionService(),
            objective_repository=repository,
        )
    )

    class FindingAuthoringModel:
        def __init__(self) -> None:
            self.turns = deque(
                (
                    ModelTurn(
                        content="I prepared an evidence-backed conclusion for approval.",
                        tool_calls=(ModelToolCall(
                            name="create_finding_version",
                            arguments={
                                "objective_id": "obj-1",
                                "source_analysis_version": 1,
                                "statement": (
                                    "Higher temperature is associated with 999 MPa strength."
                                ),
                                "assertion_strength": "associative",
                                "supporting_evidence_ids": ["evidence-1"],
                                "contradicting_evidence_ids": [],
                                "context_evidence_ids": [],
                                "condition_boundary_evidence_ids": [],
                                "limitations": [
                                    "Only one paper directly supports this conclusion."
                                ],
                                "parent_finding_id": None,
                                "abstention_reason": None,
                            },
                        ),),
                    ),
                    ModelTurn(content="The approved conclusion is now published as a new version."),
                )
            )

        async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
            messages = context.messages
            assert messages
            if self.turns[0].tool_calls != ():
                assert {item.name for item in tool_specs} == {
                    "create_finding_version"
                }
            else:
                assert tool_specs == ()
            return self.turns.popleft()

    runner = ResearchAgentRunner(
        model=FindingAuthoringModel(),
        capabilities=CapabilityRegistry((capability,)),
    )
    context = AgentContext("chat-1", "user-1", "col-gold")

    proposed = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message="Create a narrower conclusion from the reviewed Evidence.",
    )

    objective_before = await repository.read_objective("col-gold", "obj-1")
    assert proposed.status.value == "approval_required"
    assert proposed.pending_approval is not None
    assert objective_before is not None
    assert objective_before.published_analysis_version == 1
    assert await repository.read_analysis("col-gold", "obj-1", 2) is None

    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-09-01T08:00:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )

    objective_after = await repository.read_objective("col-gold", "obj-1")
    original = await repository.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    result = completed.tool_results[0]
    assert completed.status.value == "completed"
    assert objective_after is not None
    assert objective_after.published_analysis_version == 2
    assert original is not None
    assert original.statement == (
        "Higher temperature was associated with greater strength."
    )
    assert result.data["analysis"]["analysis_version"] == 2
    assert result.data["finding"]["origin"] == "agent_authored"
    assert result.data["finding"]["source_analysis_version"] == 1
    assert result.data["finding"]["created_by_user_id"] == "user-1"
    assert result.data["finding"]["created_by_tool_call_id"] == (
        proposed.pending_approval.tool_call_id
    )
    assert result.warnings
    assert any("999" in warning for warning in result.warnings)
    assert {ref.resource_type for ref in result.resource_refs} == {
        "objective_analysis",
        "finding",
    }


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


async def test_research_process_projects_canonical_run_without_retry_internals() -> None:
    pipeline_run_service = _PipelineRunService(
        [
            {
                "run_id": "run-1",
                "scope_type": "document",
                "scope_id": "paper-1",
                "status": "running",
                "current_node": "paper_map",
                "progress_percent": 72,
                "progress_detail": {"phase": "paper_map"},
                "warnings": ["One paper could not be parsed."],
                "errors": [],
            }
        ]
    )
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        pipeline_run_service=pipeline_run_service,
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
    assert pipeline_run_service.calls == [
        {"collection_id": "col-1", "limit": 200, "offset": 0}
    ]
    assert result.resource_refs[0].href == "/collections/col-1"


async def test_research_process_reports_not_started_without_faking_progress() -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        pipeline_run_service=_PipelineRunService([]),
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
                    "filename": "energy-input-tensile.pdf",
                "status": "stored",
                "run_id": None,
                "stage": None,
                "progress_percent": 0,
            },
                {
                    "document_id": "paper-2",
                    "filename": "residual-stress-review.pdf",
                "status": "stored",
                "run_id": None,
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
        pipeline_run_service=_PipelineRunService(
            [
                {
                    "run_id": "run-interrupted",
                    "scope_type": "document",
                    "scope_id": "paper-1",
                    "status": "failed",
                    "current_node": "interrupted",
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
            tool_calls=(ModelToolCall(name="start_research_process", arguments={}),),
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

    completed = await runner.resume_claimed_call(
        context=AgentContext(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
        ),
        previous_messages=proposed.messages,
        claimed_call=approved_call.start("2026-08-19T00:01:01+00:00"),
    )

    assert completed.status.value == "completed"
    assert preparation_service.calls == [
        {
            "collection_id": "col-1",
            "document_id": "paper-1",
        },
        {
            "collection_id": "col-1",
            "document_id": "paper-2",
        }
    ]
    assert completed.tool_results[0].status.value == "queued"
    assert completed.tool_results[0].data == {
        "collection_id": "col-1",
        "document_ids": ["paper-1", "paper-2"],
        "runs": (
            {
                "run_id": "run-paper-1",
                "collection_id": "col-1",
                "pipeline_name": "document_preparation",
                "scope_type": "document",
                "scope_id": "paper-1",
                "status": "queued",
                "mode": "standard",
            },
            {
                "run_id": "run-paper-2",
                "collection_id": "col-1",
                "pipeline_name": "document_preparation",
                "scope_type": "document",
                "scope_id": "paper-2",
                "status": "queued",
                "mode": "standard",
            },
        ),
        "research_scope": "document_preparation",
        "objective_discovery_started": False,
        "objective_analysis_started": False,
    }
    assert completed.tool_results[0].warnings == (
        "No document scope was supplied; all 2 paper(s) in the collection were queued for preparation.",
    )
    assert completed.tool_results[0].resource_refs[0].resource_type == (
        "pipeline_run"
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
    ("run_status", "expected_process_status", "expected_document_status"),
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
    run_status: str,
    expected_process_status: str,
    expected_document_status: str,
) -> None:
    capability = InspectResearchProcessCapability(
        collection_service=_CollectionService(),
        pipeline_run_service=_PipelineRunService(
            [
                {
                    "run_id": "run-terminal",
                    "scope_type": "document",
                    "scope_id": "paper-1",
                    "status": run_status,
                    "progress_percent": 100,
                    "progress_detail": {"message": "Build artifacts are ready."},
                    "warnings": [],
                    "errors": (
                        ["Source processing stopped."]
                        if run_status == "failed"
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
        ["Source processing stopped."] if run_status == "failed" else []
    )


class _ResearchProcessModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)
        self.contexts: list[tuple] = []

    async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
        messages = context.messages
        self.contexts.append(messages)
        assert {item.name for item in tool_specs} == {"inspect_research_process"}
        return self.turns.popleft()


async def test_agent_continues_from_observable_research_process_result() -> None:
    model = _ResearchProcessModel(
        ModelTurn(
            tool_calls=(ModelToolCall(name="inspect_research_process", arguments={}),)
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
                    pipeline_run_service=_PipelineRunService(
                        [
                            {
                                "run_id": "run-1",
                                "scope_type": "document",
                                "scope_id": "paper-1",
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
    assert result.data["objectives"][0]["evidence"][0]["supports_finding"] is True
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


def test_published_finding_reads_keep_model_observations_bounded() -> None:
    query_model = QueryPublishedFindingsCapability.spec.input_model
    inspect_model = InspectPublishedFindingCapability.spec.input_model

    assert query_model().evidence_limit_per_objective == 8
    assert inspect_model(
        objective_id="objective-1",
        finding_id="finding-1",
    ).evidence_limit == 12
    with pytest.raises(ValidationError):
        query_model(evidence_limit_per_objective=13)
    with pytest.raises(ValidationError):
        inspect_model(
            objective_id="objective-1",
            finding_id="finding-1",
            evidence_limit=21,
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
    assert result.data["evidence"][0]["supports_finding"] is True
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
        objective_authoring_service=service,
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


async def test_agent_confirms_objective_without_starting_analysis() -> None:
    objective = _objective("objective-agent")
    service = _ObjectiveConfirmationService(objective)
    capability = ConfirmObjectiveCapability(objective_authoring_service=service)

    result = await capability.execute(
        _context("call-confirm-objective"),
        capability.spec.input_model(objective_id="objective-agent"),
    )

    assert capability.spec.risk.value == "write"
    assert result.status.value == "succeeded"
    assert result.data == {
        "objective_id": "objective-agent",
        "confirmation_status": "confirmed",
        "analysis_started": False,
    }
    assert service.calls == [
        {
            "collection_id": "col-1",
            "user_id": "user-1",
            "objective_id": "objective-agent",
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
        "recommended_document_ids": ["paper-1"],
        "review_document_ids": ["paper-2"],
        "excluded_document_ids": ["paper-3"],
    }
    assert result.data["scope_complete"] is True
    assert result.data["returned_record_count"] == 3
    assert result.data["omitted_record_count"] == 0
    assert result.data["support_is_evidence"] is False


async def test_scope_preview_keeps_complete_scope_ids_when_details_are_bounded() -> None:
    relevant_maps = tuple(
        PaperResearchMap.from_mapping(
            {
                "document_id": f"paper-relevant-{index:02d}",
                "doc_role": "experimental",
                "map_status": "sufficient",
                "studies": [
                    {
                        "study_id": f"study-relevant-{index:02d}",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "relationships": [
                            {
                                "relationship_id": f"relationship-relevant-{index:02d}",
                                "varied_factors": ["laser power"],
                                "outcome": "elongation",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": f"block-relevant-{index:02d}",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            }
        )
        for index in range(30)
    )
    review_maps = tuple(
        PaperResearchMap.from_mapping(
            {
                "document_id": f"paper-review-{index:02d}",
                "doc_role": "experimental",
                "map_status": "insufficient_map",
                "map_limitations": ["The result was not visible in mapped Sources."],
                "studies": [],
            }
        )
        for index in range(4)
    )
    excluded_maps = tuple(
        PaperResearchMap.from_mapping(
            {
                "document_id": f"paper-excluded-{index:02d}",
                "doc_role": "experimental",
                "map_status": "sufficient",
                "studies": [
                    {
                        "study_id": f"study-excluded-{index:02d}",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["316L"],
                        "relationships": [
                            {
                                "relationship_id": f"relationship-excluded-{index:02d}",
                                "varied_factors": ["solution treatment temperature"],
                                "outcome": "corrosion potential",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": f"block-excluded-{index:02d}",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            }
        )
        for index in range(2)
    )
    capability = PreviewResearchScopeCapability(
        collection_service=_CollectionService(),
        paper_map_repository=_PaperMapRepository(
            (*relevant_maps, *review_maps, *excluded_maps)
        ),
    )

    result = await capability.execute(
        _context("call-large-scope"),
        capability.spec.input_model(
            question="How does laser power affect elongation?",
            material_scope=["Ti-6Al-4V"],
            variables=["laser power"],
            outcomes=["elongation"],
        ),
    )

    assert len(result.data["likely_relevant"]) == 24
    assert len(result.data["needs_inspection"]) == 4
    assert len(result.data["confidently_out_of_scope"]) == 2
    assert result.data["scope_counts"] == {
        "likely_relevant": 30,
        "needs_inspection": 4,
        "confidently_out_of_scope": 2,
    }
    assert result.data["returned_record_count"] == 30
    assert result.data["omitted_record_count"] == 6
    assert result.data["scope_complete"] is True
    assert result.data["suggested_scope"] == {
        "recommended_document_ids": [
            f"paper-relevant-{index:02d}" for index in range(30)
        ],
        "review_document_ids": [
            f"paper-review-{index:02d}" for index in range(4)
        ],
        "excluded_document_ids": [
            f"paper-excluded-{index:02d}" for index in range(2)
        ],
    }
    assert "seed_document_ids" not in result.data["suggested_scope"]
    assert any("suggested scope remains complete" in item for item in result.warnings)


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
        "recommended_document_ids": ["paper-1"],
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
        "recommended_document_ids": [],
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
    service = ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
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
    service = ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
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

    async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
        messages = context.messages
        assert messages
        if self.turns[0].tool_calls != ():
            assert {item.name for item in tool_specs} == {
                "start_objective_analysis"
            }
        else:
            assert tool_specs == ()
        return self.turns.popleft()


async def test_agent_starts_objective_analysis_only_after_exact_approval() -> None:
    analysis_service = _ObjectiveAnalysisCapabilityService()
    objective_repository = _ObjectiveRepository(
        (replace(_objective("objective-agent"), confirmation_status="confirmed"),)
    )
    capability = StartObjectiveAnalysisCapability(
        collection_service=_CollectionService(),
        objective_repository=objective_repository,
        objective_analysis_service=analysis_service,
    )
    model = _ObjectiveAnalysisModel(
        ModelTurn(
            content="This question is ready for your approval.",
            tool_calls=(ModelToolCall(
                name="start_objective_analysis",
                arguments={
                    "objective_id": "objective-agent",
                    "document_ids": ["paper-1"],
                },
            ),),
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
    completed = await runner.resume_claimed_call(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )

    assert analysis_service.start_calls == [
        ("col-1", "objective-agent", ("paper-1",))
    ]
    assert completed.tool_results[0].status.value == "queued"
    assert completed.tool_results[0].data["analysis"]["status"] == "queued"


async def test_agent_cannot_start_analysis_for_an_unconfirmed_candidate() -> None:
    analysis_service = _ObjectiveAnalysisCapabilityService()
    capability = StartObjectiveAnalysisCapability(
        collection_service=_CollectionService(),
        objective_repository=_ObjectiveRepository((_objective("objective-agent"),)),
        objective_analysis_service=analysis_service,
    )

    with pytest.raises(ValueError, match="confirm the research objective"):
        await capability.execute(
            _context("call-analysis-unconfirmed"),
            capability.spec.input_model(
                objective_id="objective-agent",
                document_ids=["paper-1"],
            ),
        )

    assert analysis_service.start_calls == []


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
        objective_repository=_ObjectiveRepository(
            (replace(_objective("objective-agent"), confirmation_status="confirmed"),)
        ),
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


async def test_quality_assessment_separates_technical_failure_from_scientific_gap() -> None:
    class QualityAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-published")
            return {
                "objective": _objective(
                    "objective-published",
                    published_version=2,
                ),
                "analysis": None,
                "published_analysis": SimpleNamespace(
                    analysis_version=2,
                    status="succeeded",
                    abstention_reason="insufficient_evidence",
                    abstention_note="One result still needs same-paper context.",
                ),
                "findings": (),
                "paper_contributions": (
                    SimpleNamespace(
                        document_id="paper-1",
                        evidence_disposition="no_comparable_evidence",
                        evidence_disposition_reason="The group labels need context.",
                    ),
                    SimpleNamespace(
                        document_id="paper-2",
                        evidence_disposition="extraction_failed",
                        evidence_disposition_reason="Structured extraction failed.",
                    ),
                ),
                "evidence_review": {
                    "total_evidence_count": 2,
                    "result_count": 1,
                    "comparable_evidence_count": 0,
                    "gap_count": 2,
                    "omitted_gap_count": 0,
                    "status_counts": {
                        "needs_context": 1,
                        "extraction_failed": 1,
                    },
                    "gaps": [
                        {
                            "evidence_id": "evidence-context",
                            "document_id": "paper-1",
                            "source_kind": "text_window",
                            "source_ref": "block-result",
                            "page_numbers": [5],
                            "evidence_status": "needs_context",
                            "reason": "NP and P150 need their Methods definition.",
                            "outcome": "elongation",
                            "source_excerpt": "P150 showed lower elongation than NP.",
                        },
                        {
                            "evidence_id": "evidence-failed",
                            "document_id": "paper-2",
                            "source_kind": "table",
                            "source_ref": "table-4",
                            "page_numbers": [8],
                            "evidence_status": "extraction_failed",
                            "reason": "The structured extraction did not complete.",
                            "outcome": None,
                            "source_excerpt": "",
                        },
                    ],
                },
                "warnings": [
                    "paper-2: Evidence extraction failed for one Source."
                ],
            }

    capability = AssessObjectiveQualityCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=QualityAnalysisService(),
    )

    result = await capability.execute(
        _context("call-quality"),
        capability.spec.input_model(objective_id="objective-published"),
    )

    assert result.status.value == "succeeded"
    assert result.data["quality_status"] == "scientific_abstention"
    assert result.data["technical_failure_count"] == 1
    assert result.data["scientific_gap_count"] == 1
    assert result.data["finding_count"] == 0
    assert result.data["support_is_evidence"] is False
    assert result.data["next_inspections"][0]["document_id"] == "paper-1"
    assert {ref.resource_type for ref in result.resource_refs} == {
        "objective_analysis",
        "source",
    }


async def test_quality_assessment_bounds_source_candidates_for_agent_context() -> None:
    class LargeQualityAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-published")
            gaps = [
                {
                    "evidence_id": f"evidence-{index}",
                    "document_id": f"paper-{index}",
                    "source_kind": "text_window",
                    "source_ref": f"block-{index}",
                    "page_numbers": [index + 1],
                    "evidence_status": "needs_context",
                    "reason": "r" * 2_000,
                    "outcome": "elongation",
                    "source_excerpt": "s" * 4_000,
                    "unbounded_internal_payload": "x" * 10_000,
                }
                for index in range(20)
            ]
            return {
                "objective": _objective(
                    "objective-published",
                    published_version=2,
                ),
                "analysis": None,
                "published_analysis": SimpleNamespace(
                    analysis_version=2,
                    status="succeeded",
                    abstention_reason=None,
                    abstention_note=None,
                ),
                "findings": ({"finding_id": "finding-1"},),
                "paper_contributions": (),
                "evidence_review": {
                    "total_evidence_count": 20,
                    "comparable_evidence_count": 0,
                    "omitted_gap_count": 0,
                    "status_counts": {"needs_context": 20},
                    "gaps": gaps,
                },
                "warnings": (),
            }

    capability = AssessObjectiveQualityCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=LargeQualityAnalysisService(),
    )

    result = await capability.execute(
        _context("call-quality-bounded"),
        capability.spec.input_model(objective_id="objective-published"),
    )

    encoded = json.dumps(result.to_record(), ensure_ascii=True, separators=(",", ":"))
    assert len(result.data["next_inspections"]) == 12
    assert result.data["omitted_inspection_count"] == 8
    assert len(result.data["next_inspections"][0]["reason"]) == 500
    assert len(result.data["next_inspections"][0]["source_excerpt"]) == 500
    assert "unbounded_internal_payload" not in result.data["next_inspections"][0]
    assert len(encoded) < 20_000


async def test_quality_assessment_accepts_serialized_analysis_records() -> None:
    class SerializedQualityAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-published")
            return {
                "objective": _objective(
                    "objective-published",
                    published_version=3,
                ),
                "analysis": None,
                "published_analysis": {
                    "analysis_version": 3,
                    "status": "succeeded",
                    "abstention_reason": None,
                    "abstention_note": None,
                },
                "findings": ({"finding_id": "finding-1"},),
                "paper_contributions": (
                    {
                        "document_id": "paper-1",
                        "evidence_disposition": "comparable_evidence",
                        "evidence_disposition_reason": None,
                    },
                    {
                        "document_id": "paper-2",
                        "evidence_disposition": "extraction_failed",
                        "evidence_disposition_reason": "Provider timed out.",
                    },
                ),
                "evidence_review": {
                    "total_evidence_count": 1,
                    "comparable_evidence_count": 1,
                    "status_counts": {"comparable": 1},
                    "gaps": [],
                },
                "warnings": ["paper-2: Evidence extraction failed."],
            }

    capability = AssessObjectiveQualityCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=SerializedQualityAnalysisService(),
    )

    result = await capability.execute(
        _context("call-quality-serialized"),
        capability.spec.input_model(objective_id="objective-published"),
    )

    assert result.data["published_analysis_version"] == 3
    assert result.data["quality_status"] == "finding_available_with_gaps"
    assert result.data["failed_paper_count"] == 1
    assert result.data["paper_contributions"][1] == {
        "document_id": "paper-2",
        "evidence_disposition": "extraction_failed",
        "reason": "Provider timed out.",
    }
    assert result.data["abstention_reason"] is None


async def test_quality_assessment_exposes_newer_runtime_failure_without_erasing_published_result() -> None:
    class FailedCurrentAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            return {
                "objective": _objective(
                    "objective-published",
                    published_version=3,
                ),
                "analysis": {
                    "analysis_version": 4,
                    "status": "failed",
                    "error_code": "paper_source_unavailable",
                    "error_message": "One selected paper could not be opened.",
                },
                "published_analysis": {
                    "analysis_version": 3,
                    "status": "succeeded",
                    "abstention_reason": None,
                    "abstention_note": None,
                },
                "findings": ({"finding_id": "finding-1"},),
                "paper_contributions": (),
                "evidence_review": {
                    "total_evidence_count": 1,
                    "comparable_evidence_count": 1,
                    "status_counts": {"comparable": 1},
                    "gaps": [],
                },
                "warnings": [],
            }

    capability = AssessObjectiveQualityCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=FailedCurrentAnalysisService(),
    )

    result = await capability.execute(
        _context("call-quality-runtime-failure"),
        capability.spec.input_model(objective_id="objective-published"),
    )

    assert result.data["quality_status"] == "finding_available"
    assert result.data["runtime_state"] == "previous_published_result_available"
    assert result.data["active_analysis_version"] == 4
    assert result.data["active_analysis_error_code"] == "paper_source_unavailable"
    assert result.data["requires_researcher_review"] is True
    assert any("newer analysis failed" in warning for warning in result.warnings)


async def test_agent_derives_objective_draft_from_published_scientific_gaps() -> None:
    class DerivationAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-parent")
            return {
                "objective": _objective("objective-parent", published_version=3),
                "published_analysis": SimpleNamespace(analysis_version=3),
                "findings": (
                    SimpleNamespace(
                        finding_id="finding-1",
                        statement="Preheating changes elongation under the tested conditions.",
                    ),
                ),
                "paper_contributions": (),
                "evidence_review": {
                    "gaps": [
                        {
                            "evidence_id": "evidence-gap",
                            "document_id": "paper-1",
                            "source_kind": "text_window",
                            "source_ref": "methods-4",
                            "evidence_status": "needs_context",
                            "reason": "The effect at intermediate temperatures is unresolved.",
                        }
                    ],
                    "omitted_gap_count": 0,
                },
                "warnings": [],
            }

    capability = DeriveObjectiveCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=DerivationAnalysisService(),
    )

    result = await capability.execute(
        _context("call-derive-objective"),
        capability.spec.input_model(
            objective_id="objective-parent",
            drafts=[
                {
                    "question": (
                        "How does intermediate build-plate preheating affect fatigue life?"
                    ),
                    "material_scope": ["Ti-6Al-4V"],
                    "variables": ["build-plate preheating"],
                    "outcomes": ["fatigue life"],
                    "constraints": ["intermediate preheating temperatures"],
                    "derivation_basis": [
                        {
                            "kind": "finding",
                            "reference_id": "finding-1",
                            "rationale": "The current Finding establishes a temperature-sensitive effect.",
                        },
                        {
                            "kind": "evidence_gap",
                            "reference_id": "evidence-gap",
                            "rationale": "The current Evidence leaves intermediate temperatures unresolved.",
                        },
                    ],
                }
            ],
        ),
    )

    assert capability.spec.risk.value == "draft"
    assert result.data["derivation_status"] == "proposed"
    assert result.data["published_analysis_version"] == 3
    assert result.data["draft_count"] == 1
    assert result.data["drafts"][0]["parent_objective_id"] == "objective-parent"
    assert result.data["drafts"][0]["outcomes"] == ["fatigue life"]
    assert result.data["drafts"][0]["support_is_evidence"] is False
    assert result.data["rejected_drafts"] == []
    assert result.data["persistence"] == "transient_chat_result"
    assert {ref.resource_type for ref in result.resource_refs} == {
        "objective_analysis",
        "finding",
        "source",
        "objective_draft",
    }


async def test_agent_does_not_turn_technical_failure_into_derived_objective() -> None:
    class FailedExtractionAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-parent")
            return {
                "objective": _objective("objective-parent", published_version=2),
                "published_analysis": {"analysis_version": 2},
                "findings": (),
                "paper_contributions": (),
                "evidence_review": {
                    "gaps": [
                        {
                            "evidence_id": "evidence-failed",
                            "document_id": "paper-2",
                            "source_kind": "table",
                            "source_ref": "table-4",
                            "evidence_status": "extraction_failed",
                            "reason": "The model response was invalid.",
                        }
                    ]
                },
                "warnings": [],
            }

    capability = DeriveObjectiveCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=FailedExtractionAnalysisService(),
    )

    result = await capability.execute(
        _context("call-derive-from-failure"),
        capability.spec.input_model(
            objective_id="objective-parent",
            drafts=[
                {
                    "question": "How does laser power affect porosity?",
                    "variables": ["laser power"],
                    "outcomes": ["porosity"],
                    "derivation_basis": [
                        {
                            "kind": "evidence_gap",
                            "reference_id": "evidence-failed",
                            "rationale": "The extraction failed for this table.",
                        }
                    ],
                }
            ],
        ),
    )

    assert result.data["derivation_status"] == "abstained"
    assert result.data["drafts"] == []
    assert result.data["abstention_reason"] == "no_valid_scientific_basis"
    assert result.data["rejected_drafts"][0]["reasons"] == [
        "technical_failure_is_not_scientific_basis:evidence-failed"
    ]


async def test_agent_abstains_from_derivation_before_parent_analysis_is_published() -> None:
    class UnpublishedAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-parent")
            return {
                "objective": _objective("objective-parent"),
                "published_analysis": None,
                "findings": (),
                "paper_contributions": (),
                "evidence_review": {},
                "warnings": [],
            }

    capability = DeriveObjectiveCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=UnpublishedAnalysisService(),
    )

    result = await capability.execute(
        _context("call-derive-unpublished"),
        capability.spec.input_model(
            objective_id="objective-parent",
            drafts=[
                {
                    "question": "How does laser power affect porosity?",
                    "variables": ["laser power"],
                    "outcomes": ["porosity"],
                    "derivation_basis": [
                        {
                            "kind": "finding",
                            "reference_id": "finding-missing",
                            "rationale": "Follow the unresolved result.",
                        }
                    ],
                }
            ],
        ),
    )

    assert result.data["derivation_status"] == "abstained"
    assert result.data["abstention_reason"] == "parent_analysis_not_published"
    assert result.data["drafts"] == []


async def test_agent_distinguishes_a_missing_finding_from_a_bounded_analysis_view() -> None:
    class BoundedAnalysisService:
        async def get_analysis_state(
            self,
            collection_id: str,
            objective_id: str,
        ) -> dict:
            assert (collection_id, objective_id) == ("col-1", "objective-parent")
            return {
                "objective": _objective("objective-parent", published_version=3),
                "published_analysis": SimpleNamespace(analysis_version=3),
                "findings": (),
                "finding_total": 51,
                "omitted_finding_count": 1,
                "paper_contributions": (),
                "evidence_review": {},
                "warnings": [],
            }

    capability = DeriveObjectiveCapability(
        collection_service=_CollectionService(),
        objective_analysis_service=BoundedAnalysisService(),
    )

    result = await capability.execute(
        _context("call-derive-bounded"),
        capability.spec.input_model(
            objective_id="objective-parent",
            drafts=[
                {
                    "question": "How does laser power affect porosity?",
                    "variables": ["laser power"],
                    "outcomes": ["porosity"],
                    "derivation_basis": [
                        {
                            "kind": "finding",
                            "reference_id": "finding-outside-view",
                            "rationale": "Use the published finding as the next question basis.",
                        }
                    ],
                }
            ],
        ),
    )

    assert result.data["derivation_status"] == "abstained"
    assert result.data["rejected_drafts"][0]["reasons"] == [
        "finding_not_in_bounded_analysis_view:finding-outside-view"
    ]
    assert result.data["omitted_finding_count"] == 1
    assert result.warnings


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
                        tool_calls=(ModelToolCall(
                            name="preview_research_scope",
                            arguments={
                                "question": objective.question,
                                "material_scope": ["Ti-6Al-4V"],
                                "variables": ["laser power", "scan speed"],
                                "outcomes": ["ductility"],
                            },
                        ),)
                    ),
                    ModelTurn(
                        tool_calls=(ModelToolCall(
                            name="create_objective_candidate",
                            arguments={
                                "question": objective.question,
                                "material_scope": ["Ti-6Al-4V"],
                                "variables": ["laser power", "scan speed"],
                                "outcomes": ["ductility"],
                                "seed_document_ids": ["paper-1"],
                            },
                        ),)
                    ),
                    ModelTurn(
                        tool_calls=(ModelToolCall(
                            name="start_objective_analysis",
                            arguments={
                                "objective_id": "objective-agent",
                                "document_ids": ["paper-1"],
                            },
                        ),)
                    ),
                    ModelTurn(
                        tool_calls=(ModelToolCall(
                            name="inspect_objective_analysis",
                            arguments={"objective_id": "objective-agent"},
                        ),)
                    ),
                    ModelTurn(content="Evidence analysis is running for the approved question."),
                )
            )

        async def respond(self, *, context: tuple, tool_specs: tuple, timeout_seconds=180.0, max_output_tokens=16_384) -> ModelTurn:
            messages = context.messages
            assert messages
            next_turn = self.turns[0]
            expected = {
                "preview_research_scope",
                "create_objective_candidate",
                "start_objective_analysis",
                "inspect_objective_analysis",
            }
            if next_turn.tool_calls != ():
                if next_turn.tool_calls[0].name == "start_objective_analysis":
                    expected.remove("create_objective_candidate")
                elif next_turn.tool_calls[0].name == "inspect_objective_analysis":
                    expected.difference_update(
                        {"create_objective_candidate", "start_objective_analysis"}
                    )
            else:
                expected.difference_update(
                    {"create_objective_candidate", "start_objective_analysis"}
                )
            assert {item.name for item in tool_specs} == expected
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
                    objective_authoring_service=authoring_service,
                ),
                StartObjectiveAnalysisCapability(
                    collection_service=_CollectionService(),
                    objective_repository=_ObjectiveRepository(
                        (
                            replace(
                                objective,
                                confirmation_status="confirmed",
                            ),
                        )
                    ),
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
        user_message=(
            "Please evaluate this research question's paper scope, save the "
            "candidate objective, confirm objective, and start analysis after "
            "each approval: "
            f"{objective.question}"
        ),
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
    analysis_proposal = await runner.resume_claimed_call(
        context=context,
        previous_messages=objective_proposal.messages,
        claimed_call=approved_objective.start("2026-08-19T00:01:01+00:00"),
    )

    assert analysis_proposal.tool_results[0].data["research_status"] == "untested"
    assert analysis_service.start_calls == []
    assert analysis_proposal.pending_approval.name == "start_objective_analysis"

    approved_analysis = analysis_proposal.pending_approval.approve(
        user_id="user-1",
        arguments_digest=analysis_proposal.pending_approval.arguments_digest,
        decided_at="2026-08-25T08:01:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=analysis_proposal.messages,
        claimed_call=approved_analysis.start("2026-08-19T00:02:01+00:00"),
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
    service = ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
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
            tool_calls=(ModelToolCall(
                name="get_collection_context",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
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
            ),)
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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from domain.core.document_profile import DocumentProfile
from domain.core.research_objective import (
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperResearchMap,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats
from domain.core.finding import Finding
from domain.source import (
    Collection,
    Document,
    SourceBlock,
    SourceDocument,
    SourceDocumentTree,
    SourceFigure,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    TaskRecord,
    TaskStageRecord,
)
from domain.evaluation import (
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    FindingCuration,
    FindingFeedback,
)
from domain.goal import ExperimentPlanRecord
from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult


@dataclass(frozen=True)
class CollectionPaths:
    collection_dir: Path
    input_dir: Path
    output_dir: Path


class CollectionRepository(Protocol):
    async def add_collection(self, collection: Collection) -> None: ...

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[Collection, ...]: ...

    async def read_collection(
        self, collection_id: str
    ) -> Collection | None: ...

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> Document | None: ...

    async def update_collection(self, collection: Collection) -> bool: ...

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[Document, ...],
        *,
        updated_at: str,
    ) -> None: ...

    async def update_document(self, document: Document) -> bool: ...

    async def delete_collection(self, collection_id: str) -> bool: ...


class TaskRepository(Protocol):
    async def add_task(self, record: TaskRecord) -> TaskRecord: ...

    async def get_or_create_collection_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]: ...

    async def get_or_create_document_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]: ...

    async def read_task(self, task_id: str) -> TaskRecord | None: ...

    async def list_tasks(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TaskRecord, ...]: ...

    async def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[TaskStageRecord, ...] | None = None,
    ) -> bool: ...

    async def list_stages(
        self, task_id: str
    ) -> tuple[TaskStageRecord, ...]: ...


class ChatRepository(Protocol):
    async def add_session(self, record: ChatSession) -> None: ...

    async def read_session(self, session_id: str) -> ChatSession | None: ...

    async def read_messages(
        self, session_id: str
    ) -> tuple[ChatMessage, ...]: ...

    async def read_tool_call(
        self, tool_call_id: str
    ) -> ChatToolCall | None: ...

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None: ...

    async def decide_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        arguments_digest: str,
        decision: str,
        decided_at: str,
    ) -> ChatToolCall: ...


class ExperimentPlanRepository(Protocol):
    async def upsert_plan(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord: ...

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None: ...

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]: ...


class SourceArtifactRepository(Protocol):
    backend_name: str

    async def replace_document(
        self,
        collection_id: str,
        document: SourceDocument,
    ) -> None: ...

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None: ...

    async def read_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[SourceDocument, ...]: ...

    async def read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[SourceDocument, ...]: ...

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocumentTree: ...

    async def list_documents(
        self,
        collection_id: str,
    ) -> list[SourceDocument]: ...

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTextUnit]: ...

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceBlock]: ...

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTable]: ...

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
    ) -> list[SourceTableRow]: ...

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
    ) -> list[SourceTableCell]: ...

    async def replace_document_references(
        self,
        document_id: str,
        references: SourceReferenceSet,
    ) -> None: ...

    async def read_collection_references(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> SourceReferenceSet: ...

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceFigure]: ...


class DocumentProfileRepository(Protocol):
    async def replace(self, profile: DocumentProfile) -> None: ...

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None: ...

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]: ...


class PaperMapRepository(Protocol):
    async def replace(self, collection_id: str, paper_map: PaperResearchMap) -> None: ...

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None: ...

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]: ...


class ObjectiveRepository(Protocol):
    backend_name: str

    async def replace(
        self,
        collection_id: str,
        facts: ObjectiveFactSet,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
    ) -> ObjectiveFactSet: ...

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]: ...

    async def list_objective_records(
        self,
        collection_id: str,
    ) -> tuple[dict[str, Any], ...]: ...

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective: ...

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None: ...

    async def read_objective_record(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any] | None: ...

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
        origin: str = "system_generated",
        created_by_user_id: str | None = None,
        created_by_tool_call_id: str | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None: ...

    async def update_analysis_progress(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        phase: str,
        processed_document_count: int,
        total_document_count: int,
        current_document_id: str | None,
        progress_message: str | None,
    ) -> ObjectiveAnalysis: ...

    async def update_analysis_execution_stats(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        stats: ExecutionStats,
        model_name: str | None,
        prompt_versions: dict[str, str],
        diagnostics: tuple[dict[str, Any], ...],
    ) -> ObjectiveAnalysis: ...

    async def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
        expected_status: str | None = None,
    ) -> ObjectiveAnalysis: ...

    async def interrupt_active_analyses(self) -> int: ...

    async def write_document_evidence(
        self,
        checkpoint: ObjectiveDocumentEvidence,
    ) -> None: ...

    async def read_document_evidence(
        self,
        collection_id: str,
        objective_id: str,
        document_id: str,
        input_fingerprint: str,
    ) -> ObjectiveDocumentEvidence | None: ...

    async def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def publish_authored_analysis(
        self,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        *,
        analysis: ObjectiveAnalysis,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None: ...

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None: ...

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]: ...

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]: ...

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None: ...

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]: ...


class FindingReviewRepository(Protocol):
    backend_name: str

    async def upsert_feedback(
        self,
        feedback: FindingFeedback,
    ) -> FindingFeedback: ...

    async def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]: ...

    async def upsert_curation(
        self,
        curation: FindingCuration,
    ) -> FindingCuration: ...

    async def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]: ...


class EvaluationRepository(Protocol):
    backend_name: str

    async def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None: ...

    async def read_gold_set(
        self, gold_id: str
    ) -> EvaluationGoldSet | None: ...

    async def list_gold_items(
        self, gold_id: str
    ) -> tuple[EvaluationGoldItem, ...]: ...

    async def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None: ...

    async def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None: ...

    async def upsert_evaluation_run(self, run: EvaluationRun) -> None: ...

    async def read_evaluation_run(
        self, evaluation_run_id: str
    ) -> EvaluationRun | None: ...

    async def list_evaluation_runs(
        self, collection_id: str
    ) -> tuple[EvaluationRun, ...]: ...

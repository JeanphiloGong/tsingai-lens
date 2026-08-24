from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from domain.core.comparison import (
    ComparisonFactSet,
)
from domain.core.document_profile import DocumentProfile
from domain.core.paper_fact import PaperFactSet
from domain.core.research_objective import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats
from domain.core.finding import Finding
from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionBuildRecord,
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportRecord,
    CollectionRecord,
    CollectionDocumentRecord,
    DocumentRecord,
    DocumentVersionRecord,
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
    async def add_collection(self, record: CollectionRecord) -> None: ...

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionRecord, ...]: ...

    async def read_collection(
        self, collection_id: str
    ) -> CollectionRecord | None: ...

    async def update_collection(self, record: CollectionRecord) -> bool: ...

    async def add_collection_import(
        self,
        record: CollectionImportRecord,
        *,
        updated_at: str,
    ) -> None: ...

    async def list_collection_files(
        self,
        collection_id: str,
    ) -> tuple[CollectionFileRecord, ...]: ...

    async def list_collection_imports(
        self,
        collection_id: str,
    ) -> tuple[CollectionImportRecord, ...]: ...

    async def read_document(
        self, document_id: str
    ) -> DocumentRecord | None: ...

    async def read_document_version(
        self,
        document_version_id: str,
    ) -> DocumentVersionRecord | None: ...

    async def list_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[CollectionDocumentRecord, ...]: ...

    async def add_collection_handoff(
        self, record: CollectionHandoffRecord
    ) -> None: ...

    async def list_collection_handoffs(
        self,
        collection_id: str,
    ) -> tuple[CollectionHandoffRecord, ...]: ...

    async def delete_collection(self, collection_id: str) -> bool: ...


class BuildRepository(Protocol):
    async def add_task(
        self,
        record: TaskRecord,
        *,
        build_id: str,
        mode: str = "standard",
    ) -> CollectionBuildRecord: ...

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
        stages: tuple[BuildStageRecord, ...] | None = None,
    ) -> bool: ...

    async def read_build(
        self, task_id: str
    ) -> CollectionBuildRecord | None: ...

    async def list_stages(
        self, task_id: str
    ) -> tuple[BuildStageRecord, ...]: ...

    async def add_artifact_versions(
        self,
        task_id: str,
        records: tuple[ArtifactVersionRecord, ...],
    ) -> None: ...

    async def list_artifact_versions(
        self,
        task_id: str,
    ) -> tuple[ArtifactVersionRecord, ...]: ...

    async def finish_build(
        self,
        record: TaskRecord,
        *,
        build_status: str,
        activate: bool,
    ) -> CollectionBuildRecord: ...

    async def read_active_build(
        self,
        collection_id: str,
    ) -> CollectionBuildRecord | None: ...


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

    async def replace_collection_documents(
        self,
        collection_id: str,
        build_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> None: ...

    async def read_collection_documents(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]: ...

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ) -> SourceDocumentTree: ...

    async def list_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> list[SourceDocument]: ...

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTextUnit]: ...

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceBlock]: ...

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTable]: ...

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableRow]: ...

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableCell]: ...

    async def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None: ...

    async def read_collection_references(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceReferenceSet: ...

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceFigure]: ...


class PaperFactRepository(Protocol):
    backend_name: str

    async def replace_document_profiles(
        self,
        collection_id: str,
        build_id: str,
        profiles: tuple[DocumentProfile, ...],
    ) -> None: ...

    async def replace_paper_facts(
        self,
        collection_id: str,
        build_id: str,
        facts: PaperFactSet,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> PaperFactSet: ...


class ObjectiveRepository(Protocol):
    backend_name: str

    async def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet: ...

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]: ...

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

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
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


class ComparisonRepository(Protocol):
    backend_name: str

    async def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ComparisonFactSet: ...


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

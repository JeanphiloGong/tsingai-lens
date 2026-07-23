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
    SourceArtifactSet,
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


@dataclass(frozen=True)
class CollectionPaths:
    collection_dir: Path
    input_dir: Path
    output_dir: Path


class CollectionRepository(Protocol):
    def add_collection(self, record: CollectionRecord) -> None: ...

    def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionRecord, ...]: ...

    def read_collection(self, collection_id: str) -> CollectionRecord | None: ...

    def update_collection(self, record: CollectionRecord) -> bool: ...

    def add_collection_import(
        self,
        record: CollectionImportRecord,
        *,
        updated_at: str,
    ) -> None: ...

    def list_collection_files(
        self,
        collection_id: str,
    ) -> tuple[CollectionFileRecord, ...]: ...

    def list_collection_imports(
        self,
        collection_id: str,
    ) -> tuple[CollectionImportRecord, ...]: ...

    def read_document(self, document_id: str) -> DocumentRecord | None: ...

    def read_document_version(
        self,
        document_version_id: str,
    ) -> DocumentVersionRecord | None: ...

    def list_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[CollectionDocumentRecord, ...]: ...

    def add_collection_handoff(self, record: CollectionHandoffRecord) -> None: ...

    def list_collection_handoffs(
        self,
        collection_id: str,
    ) -> tuple[CollectionHandoffRecord, ...]: ...

    def delete_collection(self, collection_id: str) -> bool: ...


class BuildRepository(Protocol):
    def add_task(
        self,
        record: TaskRecord,
        *,
        build_id: str,
    ) -> CollectionBuildRecord: ...

    def read_task(self, task_id: str) -> TaskRecord | None: ...

    def list_tasks(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TaskRecord, ...]: ...

    def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[BuildStageRecord, ...] | None = None,
    ) -> bool: ...

    def read_build(self, task_id: str) -> CollectionBuildRecord | None: ...

    def list_stages(self, task_id: str) -> tuple[BuildStageRecord, ...]: ...

    def add_artifact_versions(
        self,
        task_id: str,
        records: tuple[ArtifactVersionRecord, ...],
    ) -> None: ...

    def list_artifact_versions(
        self,
        task_id: str,
    ) -> tuple[ArtifactVersionRecord, ...]: ...

    def finish_build(
        self,
        record: TaskRecord,
        *,
        build_status: str,
        activate: bool,
    ) -> CollectionBuildRecord: ...

    def read_active_build(
        self,
        collection_id: str,
    ) -> CollectionBuildRecord | None: ...


class GoalSessionRepository(Protocol):
    backend_name: str

    def read_session(self, session_id: str) -> dict[str, Any] | None: ...

    def read_message_context(self, message_id: str) -> dict[str, Any] | None: ...

    def write_session(self, payload: Mapping[str, Any]) -> None: ...

    def read_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def write_messages(
        self,
        session_id: str,
        messages: list[Mapping[str, Any]],
    ) -> None: ...


class ExperimentPlanRepository(Protocol):
    def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord: ...

    def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None: ...

    def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]: ...


class SourceArtifactRepository(Protocol):
    backend_name: str

    def replace_collection_artifacts(
        self,
        collection_id: str,
        build_id: str,
        artifacts: SourceArtifactSet,
    ) -> None: ...

    def read_collection_artifacts(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceArtifactSet: ...

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ) -> SourceDocumentTree: ...

    def list_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> list[SourceDocument]: ...

    def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTextUnit]: ...

    def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceBlock]: ...

    def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTable]: ...

    def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableRow]: ...

    def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableCell]: ...

    def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None: ...

    def read_collection_references(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceReferenceSet: ...

    def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceFigure]: ...


class PaperFactRepository(Protocol):
    backend_name: str

    def replace_document_profiles(
        self,
        collection_id: str,
        build_id: str,
        profiles: tuple[DocumentProfile, ...],
    ) -> None: ...

    def replace_paper_facts(
        self,
        collection_id: str,
        build_id: str,
        facts: PaperFactSet,
    ) -> None: ...

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> PaperFactSet: ...


class ObjectiveRepository(Protocol):
    backend_name: str

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None: ...

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet: ...

    def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]: ...

    def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None: ...

    def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective: ...

    def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None: ...

    def update_analysis_progress(
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

    def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
    ) -> ObjectiveAnalysis: ...

    def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None: ...

    def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None: ...

    def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]: ...

    def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None: ...

    def list_evidence(
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

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> None: ...

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ComparisonFactSet: ...


class FindingReviewRepository(Protocol):
    backend_name: str

    def upsert_feedback(
        self,
        feedback: FindingFeedback,
    ) -> FindingFeedback: ...

    def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]: ...

    def upsert_curation(
        self,
        curation: FindingCuration,
    ) -> FindingCuration: ...

    def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]: ...


class EvaluationRepository(Protocol):
    backend_name: str

    def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None: ...

    def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None: ...

    def list_gold_items(self, gold_id: str) -> tuple[EvaluationGoldItem, ...]: ...

    def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None: ...

    def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None: ...

    def upsert_evaluation_run(self, run: EvaluationRun) -> None: ...

    def read_evaluation_run(self, evaluation_run_id: str) -> EvaluationRun | None: ...

    def list_evaluation_runs(self, collection_id: str) -> tuple[EvaluationRun, ...]: ...

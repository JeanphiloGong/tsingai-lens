from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    PairwiseComparisonRelation,
)
from domain.core.document_profile import DocumentProfile
from domain.core.fact_store import CoreFactSet
from domain.core.research_objective import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)
from domain.core.research_understanding import ResearchUnderstanding
from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)
from domain.evaluation import (
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)


@dataclass(frozen=True)
class CollectionPaths:
    collection_dir: Path
    input_dir: Path
    output_dir: Path
    meta_path: Path
    files_path: Path
    import_manifest_path: Path
    artifacts_path: Path


class CollectionRepository(Protocol):
    backend_name: str
    root_dir: Path

    def get_paths(self, collection_id: str) -> CollectionPaths: ...

    def create_collection_dirs(self, collection_id: str) -> CollectionPaths: ...

    def collection_exists(self, collection_id: str) -> bool: ...

    def list_collection_records(self) -> list[tuple[str, dict]]: ...

    def read_collection(self, collection_id: str) -> dict | None: ...

    def write_collection(self, collection_id: str, payload: dict) -> None: ...

    def delete_collection_dir(self, collection_id: str) -> None: ...

    def read_files(self, collection_id: str) -> list[dict] | None: ...

    def write_files(self, collection_id: str, payload: list[dict]) -> None: ...

    def read_import_manifest(self, collection_id: str) -> dict | None: ...

    def write_import_manifest(self, collection_id: str, payload: dict) -> None: ...

    def write_input_file(
        self, collection_id: str, stored_filename: str, payload: bytes
    ) -> Path: ...


class TaskRepository(Protocol):
    backend_name: str
    root_dir: Path

    def read_task(self, task_id: str) -> dict | None: ...

    def write_task(self, task_id: str, payload: dict) -> None: ...

    def list_tasks(self) -> list[dict]: ...


class ArtifactRepository(Protocol):
    backend_name: str
    root_dir: Path

    def read(self, collection_id: str) -> dict | None: ...

    def write(self, collection_id: str, payload: dict) -> None: ...


class GoalSessionRepository(Protocol):
    def read_session(self, session_id: str) -> dict[str, Any] | None: ...

    def write_session(self, payload: Mapping[str, Any]) -> None: ...

    def read_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def write_messages(
        self,
        session_id: str,
        messages: list[Mapping[str, Any]],
    ) -> None: ...


class SourceArtifactRepository(Protocol):
    backend_name: str

    def replace_collection_artifacts(
        self,
        collection_id: str,
        artifacts: SourceArtifactSet,
    ) -> None: ...

    def read_collection_artifacts(self, collection_id: str) -> SourceArtifactSet: ...

    def replace_collection_references(
        self,
        collection_id: str,
        references: SourceReferenceSet,
    ) -> None: ...

    def read_collection_references(self, collection_id: str) -> SourceReferenceSet: ...

    def list_documents(self, collection_id: str) -> list[SourceDocument]: ...

    def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTextUnit]: ...

    def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceBlock]: ...

    def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTable]: ...

    def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
    ) -> list[SourceTableRow]: ...

    def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
    ) -> list[SourceTableCell]: ...

    def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceFigure]: ...


class CoreFactRepository(Protocol):
    backend_name: str

    def replace_collection_research_objectives(
        self,
        collection_id: str,
        paper_skims: tuple[PaperSkim, ...],
        research_objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_paper_frames: tuple[ObjectivePaperFrame, ...],
        objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...],
        objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...],
        objective_logic_chains: tuple[ObjectiveLogicChain, ...],
    ) -> None: ...

    def replace_collection_document_profiles(
        self,
        collection_id: str,
        document_profiles: tuple[DocumentProfile, ...],
    ) -> None: ...

    def replace_collection_facts(
        self,
        collection_id: str,
        facts: CoreFactSet,
    ) -> None: ...

    def replace_collection_comparison_artifacts(
        self,
        collection_id: str,
        comparable_results: tuple[ComparableResult, ...],
        collection_comparable_results: tuple[CollectionComparableResult, ...],
        comparison_rows: tuple[ComparisonRowRecord, ...],
        pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = (),
    ) -> None: ...

    def read_collection_facts(self, collection_id: str) -> CoreFactSet: ...

    def replace_collection_research_understandings(
        self,
        collection_id: str,
        understandings: tuple[ResearchUnderstanding, ...],
    ) -> None: ...

    def upsert_research_understanding(
        self,
        collection_id: str,
        understanding: ResearchUnderstanding,
    ) -> None: ...

    def read_research_understanding(
        self,
        collection_id: str,
        scope_type: str,
        scope_id: str,
    ) -> ResearchUnderstanding | None: ...

    def list_research_understandings(
        self,
        collection_id: str,
        scope_type: str | None = None,
    ) -> tuple[ResearchUnderstanding, ...]: ...


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

    def upsert_research_understanding_feedback(
        self,
        feedback: ResearchUnderstandingFeedback,
    ) -> ResearchUnderstandingFeedback: ...

    def list_research_understanding_feedback(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]: ...

    def upsert_research_understanding_curation(
        self,
        curation: ResearchUnderstandingCuration,
    ) -> ResearchUnderstandingCuration: ...

    def list_research_understanding_curations(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]: ...

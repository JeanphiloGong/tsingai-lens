from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from domain.core.research_objective import (
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats
from domain.core.finding import Finding


@dataclass(frozen=True)
class StoredObjective:
    objective: ResearchObjective
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    ) -> tuple[StoredObjective, ...]: ...

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
    ) -> StoredObjective | None: ...

    async def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective: ...

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
        contributions: tuple[PaperContribution, ...] = (),
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
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
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

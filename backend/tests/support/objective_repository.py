from __future__ import annotations

from datetime import datetime, timezone

from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    ResearchObjective,
)


class MemoryObjectiveRepository:
    backend_name = "memory"

    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._facts: dict[tuple[str, str], ObjectiveFactSet] = {}
        self._objectives: dict[tuple[str, str], ResearchObjective] = {}
        self._analyses: dict[tuple[str, str, int], ObjectiveAnalysis] = {}
        self._contributions: dict[
            tuple[str, str, int], tuple[PaperContribution, ...]
        ] = {}
        self._evidence: dict[
            tuple[str, str, int], tuple[ObjectiveEvidence, ...]
        ] = {}
        self._findings: dict[tuple[str, str, int], tuple[Finding, ...]] = {}

    @classmethod
    def from_facts(
        cls,
        collection_id: str,
        facts: ObjectiveFactSet,
        *,
        build_id: str = "build_test",
    ) -> "MemoryObjectiveRepository":
        repository = cls(active_build_id=build_id)
        repository.replace(collection_id, build_id, facts)
        return repository

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        for objective in facts.research_objectives:
            if objective.collection_id != collection_id:
                raise ValueError("objective belongs to another collection")
            key = (collection_id, objective.objective_id)
            existing = self._objectives.get(key)
            self._objectives[key] = objective if existing is None else existing
        self._facts[(collection_id, build_id)] = facts

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet:
        selected_build = build_id or self.active_build_id
        return self._facts.get((collection_id, selected_build), ObjectiveFactSet())

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id

    def list_objectives(self, collection_id: str) -> tuple[ResearchObjective, ...]:
        return tuple(
            objective
            for (owned_collection_id, _), objective in self._objectives.items()
            if owned_collection_id == collection_id
        )

    def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        return self._objectives.get((collection_id, objective_id))

    def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        key = (collection_id, objective_id)
        objective = self._require_objective(*key)
        if objective.confirmation_status == "candidate":
            objective = objective.confirm()
            self._objectives[key] = objective
        return objective

    def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        key = (collection_id, objective_id)
        objective = self._require_objective(*key)
        if objective.confirmation_status != "confirmed":
            raise ValueError("objective must be confirmed before analysis")
        existing = next(
            (
                analysis
                for analysis_key, analysis in self._analyses.items()
                if analysis_key[:2] == key
                and analysis.status in {"queued", "running"}
            ),
            None,
        )
        if existing is not None:
            return objective, existing
        version = max(
            (
                analysis_key[2]
                for analysis_key in self._analyses
                if analysis_key[:2] == key
            ),
            default=0,
        ) + 1
        analysis = ObjectiveAnalysis(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=version,
            source_build_id=self.active_build_id,
            pipeline_version=pipeline_version,
            model_name=model_name,
            prompt_versions=dict(prompt_versions),
            total_document_count=len(objective.seed_document_ids),
            progress_message="Objective analysis is queued.",
            created_at=datetime.now(timezone.utc),
        )
        objective = objective.queue_analysis(version)
        self._objectives[key] = objective
        self._analyses[analysis.key] = analysis
        return objective, analysis

    def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None:
        key = (collection_id, objective_id, analysis_version)
        analysis = self._require_analysis(*key)
        if analysis.status != "queued":
            return None
        analysis = analysis.start(started_at=datetime.now(timezone.utc))
        self._analyses[key] = analysis
        return analysis

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
    ) -> ObjectiveAnalysis:
        key = (collection_id, objective_id, analysis_version)
        analysis = self._require_analysis(*key).update_progress(
            phase=phase,
            processed_document_count=processed_document_count,
            total_document_count=total_document_count,
            current_document_id=current_document_id,
            progress_message=progress_message,
        )
        self._analyses[key] = analysis
        return analysis

    def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
    ) -> ObjectiveAnalysis:
        key = (collection_id, objective_id, analysis_version)
        analysis = self._require_analysis(*key).fail(
            error_code=error_code,
            error_message=error_message,
            completed_at=datetime.now(timezone.utc),
        )
        self._analyses[key] = analysis
        return analysis

    def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        key = (collection_id, objective_id, analysis_version)
        analysis = self._require_analysis(*key)
        if analysis.status != "running":
            raise ValueError("only running objective analysis can be published")
        for record in (*contributions, *evidence_records, *findings):
            if record.key[:3] != key:
                raise ValueError("analysis artifact belongs to another version")
        contribution_documents = {item.document_id for item in contributions}
        if {item.document_id for item in evidence_records} - contribution_documents:
            raise ValueError("objective evidence lacks owning paper contribution")
        for finding in findings:
            finding.validate_evidence(evidence_records)
        analysis = analysis.succeed(completed_at=datetime.now(timezone.utc))
        objective_key = key[:2]
        objective = self._require_objective(*objective_key).publish_analysis(analysis)
        self._analyses[key] = analysis
        self._objectives[objective_key] = objective
        self._contributions[key] = contributions
        self._evidence[key] = evidence_records
        self._findings[key] = findings
        return objective, analysis

    def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        if analysis_version is None:
            objective = self.read_objective(collection_id, objective_id)
            analysis_version = (
                objective.active_analysis_version if objective is not None else None
            )
        if analysis_version is None:
            return None
        return self._analyses.get((collection_id, objective_id, analysis_version))

    def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        objective = self.read_objective(collection_id, objective_id)
        if objective is None or objective.published_analysis_version is None:
            return None
        return self._analyses.get(
            (collection_id, objective_id, objective.published_analysis_version)
        )

    def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        records = self._findings.get(
            (collection_id, objective_id, analysis_version), ()
        )
        ordered = tuple(sorted(records, key=lambda item: (item.display_rank, item.finding_id)))
        return ordered[max(0, offset) : max(0, offset) + max(1, min(limit, 200))], len(ordered)

    def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None:
        return next(
            (
                finding
                for finding in self._findings.get(
                    (collection_id, objective_id, analysis_version), ()
                )
                if finding.finding_id == finding_id
            ),
            None,
        )

    def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]:
        records = self._evidence.get(
            (collection_id, objective_id, analysis_version), ()
        )
        if finding_id is not None:
            finding = self.read_finding(
                collection_id, objective_id, analysis_version, finding_id
            )
            if finding is None:
                return (), 0
            evidence_ids = {
                *finding.derivation.supporting_evidence_ids,
                *finding.derivation.contradicting_evidence_ids,
            }
            records = tuple(
                evidence for evidence in records if evidence.evidence_id in evidence_ids
            )
        start = max(0, offset)
        return records[start : start + max(1, min(limit, 500))], len(records)

    def _require_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = self.read_objective(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(objective_id)
        return objective

    def _require_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis:
        analysis = self._analyses.get(
            (collection_id, objective_id, analysis_version)
        )
        if analysis is None:
            raise FileNotFoundError(
                f"objective analysis not found: {objective_id}/v{analysis_version}"
            )
        return analysis


__all__ = ["MemoryObjectiveRepository"]

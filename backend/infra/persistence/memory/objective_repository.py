"""In-memory persistence for current Objective discovery and analyses."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)


class MemoryObjectiveRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self._facts: dict[str, ObjectiveFactSet] = {}
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
    ) -> "MemoryObjectiveRepository":
        repository = cls()
        repository._replace_now(collection_id, facts)
        return repository

    async def replace(
        self,
        collection_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        self._replace_now(collection_id, facts)

    def _replace_now(self, collection_id: str, facts: ObjectiveFactSet) -> None:
        for objective in facts.research_objectives:
            if objective.collection_id != collection_id:
                raise ValueError("objective belongs to another collection")
            if objective.origin != "system_discovered":
                raise ValueError("Objective discovery can only replace system candidates")

        generated_ids = {
            objective.objective_id for objective in facts.research_objectives
        }
        for key, objective in tuple(self._objectives.items()):
            if (
                key[0] == collection_id
                and objective.origin == "system_discovered"
                and objective.confirmation_status == "candidate"
                and objective.objective_id not in generated_ids
            ):
                del self._objectives[key]

        current_objectives: list[ResearchObjective] = []
        for objective in facts.research_objectives:
            key = (collection_id, objective.objective_id)
            existing = self._objectives.get(key)
            if existing is not None:
                objective = replace(
                    objective,
                    confirmation_status=existing.confirmation_status,
                    active_analysis_version=existing.active_analysis_version,
                    published_analysis_version=existing.published_analysis_version,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                )
            self._objectives[key] = objective
            current_objectives.append(objective)
        self._facts[collection_id] = replace(
            facts,
            research_objectives=tuple(current_objectives),
        )

    async def read(self, collection_id: str) -> ObjectiveFactSet:
        facts = self._facts.get(collection_id)
        if facts is None:
            return ObjectiveFactSet()
        current = tuple(
            self._objectives[(collection_id, objective.objective_id)]
            for objective in facts.research_objectives
            if (collection_id, objective.objective_id) in self._objectives
        )
        return replace(facts, research_objectives=current)

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        records = tuple(
            objective
            for (owned_collection_id, _), objective in self._objectives.items()
            if owned_collection_id == collection_id
        )
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.rank if item.rank is not None else 2**31,
                    item.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    item.objective_id,
                ),
            )
        )

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective:
        if objective.origin != "chat_assisted":
            raise ValueError("authored candidate must have chat_assisted origin")
        if objective.created_by_user_id != created_by_user_id or (
            objective.created_by_tool_call_id != created_by_tool_call_id
        ):
            raise ValueError("authored candidate provenance does not match the request")
        for existing in self._objectives.values():
            if existing.created_by_tool_call_id != created_by_tool_call_id:
                continue
            if (
                existing.collection_id != objective.collection_id
                or existing.objective_id != objective.objective_id
                or existing.created_by_user_id != created_by_user_id
            ):
                raise ValueError(
                    "authored candidate tool call already created a different objective"
                )
            return existing
        facts = self._facts.get(objective.collection_id)
        if facts is None or not facts.research_objectives_ready:
            raise FileNotFoundError(
                f"research objectives not ready: {objective.collection_id}"
            )
        available = {item.document_id for item in facts.document_inputs}
        requested = set(objective.seed_document_ids) | set(
            objective.excluded_document_ids
        )
        missing = requested - available
        if missing:
            raise FileNotFoundError(
                "authored candidate document not found: "
                + ", ".join(sorted(missing))
            )
        key = (objective.collection_id, objective.objective_id)
        existing = self._objectives.get(key)
        if existing is not None:
            if existing.to_record() != objective.to_record():
                raise ValueError("research objective identity collision")
            return existing
        rank = max(
            (
                item.rank or 0
                for item in await self.list_objectives(objective.collection_id)
            ),
            default=0,
        ) + 1
        now = datetime.now(timezone.utc)
        created = replace(
            objective,
            rank=rank,
            created_at=objective.created_at or now,
            updated_at=objective.updated_at or now,
        )
        self._objectives[key] = created
        return created

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        return self._objectives.get((collection_id, objective_id))

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        key = (collection_id, objective_id)
        objective = self._require_objective(*key)
        if objective.confirmation_status == "candidate":
            objective = objective.confirm()
        existing = next(
            (
                analysis
                for analysis_key, analysis in self._analyses.items()
                if analysis_key[:2] == key and analysis.status in {"queued", "running"}
            ),
            None,
        )
        if existing is not None:
            if existing.document_inputs != document_inputs:
                raise ValueError(
                    "an active analysis already uses a different document scope"
                )
            self._objectives[key] = objective
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
            document_inputs=document_inputs,
            pipeline_version=pipeline_version,
            model_name=model_name,
            prompt_versions=dict(prompt_versions),
            total_document_count=len(document_inputs),
            progress_message="Objective analysis is queued.",
            created_at=datetime.now(timezone.utc),
        )
        objective = objective.queue_analysis(version)
        self._objectives[key] = objective
        self._analyses[analysis.key] = analysis
        return objective, analysis

    async def claim_analysis(
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

    async def update_analysis_execution_stats(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        stats,
        model_name: str | None,
        prompt_versions: dict[str, str],
        diagnostics: tuple[dict, ...],
    ) -> ObjectiveAnalysis:
        key = (collection_id, objective_id, analysis_version)
        analysis = replace(
            self._require_analysis(*key),
            stats=stats,
            model_name=model_name,
            prompt_versions=dict(prompt_versions),
            diagnostics=diagnostics,
        )
        self._analyses[key] = analysis
        return analysis

    async def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
        expected_status: str | None = None,
    ) -> ObjectiveAnalysis:
        key = (collection_id, objective_id, analysis_version)
        analysis = self._require_analysis(*key)
        if expected_status is not None and analysis.status != expected_status:
            return analysis
        analysis = analysis.fail(
            error_code=error_code,
            error_message=error_message,
            completed_at=datetime.now(timezone.utc),
        )
        self._analyses[key] = analysis
        return analysis

    async def publish_analysis(
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
        input_documents = {item.document_id for item in analysis.document_inputs}
        contribution_documents = {item.document_id for item in contributions}
        if contribution_documents != input_documents:
            raise ValueError("paper contributions must cover every analysis input")
        if {item.document_id for item in evidence_records} - contribution_documents:
            raise ValueError("objective evidence lacks owning paper contribution")
        for finding in findings:
            finding.validate_sources(evidence_records, contributions)
        analysis = analysis.succeed(completed_at=datetime.now(timezone.utc))
        objective_key = key[:2]
        objective = self._require_objective(*objective_key).publish_analysis(analysis)
        self._analyses[key] = analysis
        self._objectives[objective_key] = objective
        self._contributions[key] = contributions
        self._evidence[key] = evidence_records
        self._findings[key] = findings
        return objective, analysis

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        if analysis_version is None:
            objective = self._objectives.get((collection_id, objective_id))
            analysis_version = (
                objective.active_analysis_version if objective is not None else None
            )
        if analysis_version is None:
            return None
        return self._analyses.get((collection_id, objective_id, analysis_version))

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        objective = self._objectives.get((collection_id, objective_id))
        if objective is None or objective.published_analysis_version is None:
            return None
        return self._analyses.get(
            (collection_id, objective_id, objective.published_analysis_version)
        )

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]:
        return self._contributions.get(
            (collection_id, objective_id, analysis_version), ()
        )

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        records = tuple(
            sorted(
                self._findings.get(
                    (collection_id, objective_id, analysis_version), ()
                ),
                key=lambda item: (item.display_rank, item.finding_id),
            )
        )
        start = max(0, offset)
        return records[start : start + max(1, min(limit, 200))], len(records)

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None:
        return next(
            (
                item
                for item in self._findings.get(
                    (collection_id, objective_id, analysis_version), ()
                )
                if item.finding_id == finding_id
            ),
            None,
        )

    async def list_evidence(
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
            finding = await self.read_finding(
                collection_id,
                objective_id,
                analysis_version,
                finding_id,
            )
            if finding is None:
                return (), 0
            evidence_ids = {
                *finding.supporting_evidence_ids,
                *finding.contradicting_evidence_ids,
                *finding.context_evidence_ids,
            }
            records = tuple(
                evidence
                for evidence in records
                if evidence.evidence_id in evidence_ids
            )
        start = max(0, offset)
        return records[start : start + max(1, min(limit, 500))], len(records)

    def _require_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = self._objectives.get((collection_id, objective_id))
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return objective

    def _require_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis:
        analysis = self._analyses.get((collection_id, objective_id, analysis_version))
        if analysis is None:
            raise FileNotFoundError(
                f"objective analysis not found: {objective_id}/v{analysis_version}"
            )
        return analysis


__all__ = ["MemoryObjectiveRepository"]

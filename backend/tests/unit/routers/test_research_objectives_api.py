from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from application.core.objectives.analysis.experiment_query_service import (
    objective_evidence_response,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisDispatchError
from application.core.objectives.objective_analysis_service import (
    ObjectiveScopeNotReadyError,
    ResearchObjectiveNotFoundError,
)
from application.core.objectives.scope_screening import (
    ObjectiveScopeDecision,
    ObjectiveScopePreview,
)
from controllers.core.research_objectives import router
from controllers.schemas.core.research_objectives import (
    ObjectiveEvidenceAttributeResponse,
)
from domain.core import (
    Finding,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
    FindingPaperContribution,
)
from domain.core.finding import _choice as finding_choice
from domain.core.research_objective import (
    ObjectiveEvidence,
    PaperContribution,
    PaperStudyDisposition,
    ResearchObjective,
    _positive_int_or_none,
    _text,
    build_research_objective_id,
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from repositories.objective_repository import (
    ObjectiveAnalysis,
    StoredObjective,
)
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    TokenUsage,
)


def _objective() -> ResearchObjective:
    return ResearchObjective(
        collection_id="col-1",
        objective_id="obj-1",
        question="How does temperature affect strength?",
        material_scope=("Alloy A",),
        variables=("temperature",),
        outcomes=("strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("paper-1",),
        excluded_document_ids=(),
        confidence=0.9,
        reason=None,
        source_relationship_ids=("relationship-1",),
        rank=1,
        confirmation_status="confirmed",
        active_analysis_version=1,
        published_analysis_version=1,
    )


def _analysis(*, status: str = "succeeded") -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"
            ),
        ),
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={"paper_framing": "paper_framing.v1"},
        stats=ExecutionStats(
            duration_ms=1250,
            model_usage=(ModelUsage("model-1", 2, TokenUsage(300, 50, 350)),),
            prompt_versions={"paper_framing": "paper_framing.v1"},
        ),
        diagnostics=(
            {
                "trace_type": "table_matrix_repair",
                "table_id": "table-3",
                "status": "verified",
            },
        ),
        total_document_count=1,
    )
    if status == "queued":
        return analysis
    if status == "failed":
        return analysis.fail(
            error_code="analysis_dispatch_failed",
            error_message=(
                "Objective analysis could not be scheduled. Retry the analysis."
            ),
        )
    return analysis.start().succeed()


def _finding() -> Finding:
    return Finding(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        statement="Higher temperature was associated with greater strength.",
        factors=("temperature",),
        outcome="strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope=finding_choice(
            "isolated_effect",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status="insufficient_confirmation",
        certainty=0.5,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=("Supported by one paper.",),
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
        ),
    )


def _evidence() -> ObjectiveEvidence:
    return ObjectiveEvidence(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        evidence_id="evidence-1",
        document_id="paper-1",
        source_kind="text_window",
        source_ref="block-7",
        source_excerpt="At 500 C, tensile strength increased to 620 MPa.",
        page_numbers=(7,),
        related_source_refs=(),
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason=None,
        changed_variables=(
            ScientificVariable(
                name="temperature", baseline_value=400, target_value=500, unit="C"
            ),
        ),
        comparison=ScientificComparison(
            baseline_label="400 C",
            target_label="500 C",
            axis_names=("temperature",),
            comparable=True,
        ),
        reported_result=ScientificResult(
            outcome="strength",
            value=620,
            unit="MPa",
            direction="increase",
            result_text="Tensile strength increased to 620 MPa.",
        ),
        attribution_scope="isolated_effect",
        scientific_context=ScientificContext(
            process=(
                ScientificAttribute(
                    name="solver", value="ANSYS", context_scope="simulation"
                ),
            )
        ),
        resolution_status="resolved",
        failure_reason=None,
        confidence=0.9,
    )


def _paper_contribution() -> PaperContribution:
    return PaperContribution(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        document_id="paper-1",
        analysis_status="analyzed",
        relevance="high",
        paper_role="primary_experiment",
        contribution_summary=None,
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        exclusion_reason=None,
        warnings=(),
        confidence=0.9,
        evidence_disposition="comparable_evidence",
        routed_source_count=3,
        extracted_source_count=2,
        comparable_evidence_count=1,
        failed_source_count=1,
    )


def test_evidence_attribute_response_preserves_scope_and_outcome_applicability() -> None:
    simulation = ObjectiveEvidenceAttributeResponse.model_validate(
        {
            "name": "solver",
            "value": "ANSYS",
            "unit": None,
            "context_scope": "simulation",
            "applies_to_outcomes": ["residual stress"],
        }
    )
    legacy = ObjectiveEvidenceAttributeResponse.model_validate(
        {"name": "alloy", "value": "Ti-6Al-4V", "unit": None}
    )

    assert simulation.context_scope == "simulation"
    assert simulation.applies_to_outcomes == ["residual stress"]
    assert legacy.context_scope == "unknown"
    assert legacy.applies_to_outcomes == []


class _Repository:
    def __init__(self, facts: ObjectiveFactSet | None = None) -> None:
        self.facts = facts or _default_objective_facts()

    async def list_objectives(self, collection_id):
        return self.facts.research_objectives

    async def list_objective_records(self, collection_id):
        objectives = await self.list_objectives(collection_id)
        return tuple(StoredObjective(objective) for objective in objectives)


class _DiscoveryService:
    def __init__(self, *, scope_error: Exception | None = None) -> None:
        self.discovery_calls: list[tuple[str, tuple[str, ...]]] = []
        self.scope_calls: list[tuple[str, str]] = []
        self.scope_error = scope_error

    async def start_objective_discovery(
        self, collection_id, document_ids
    ):
        self.discovery_calls.append((collection_id, document_ids))
        return {
            "run_id": "run-discovery-1",
            "collection_id": collection_id,
            "pipeline_name": "objective_discovery",
            "scope_type": "collection",
            "scope_id": collection_id,
            "mode": "standard",
            "input_fingerprint": "scope-fingerprint",
            "status": "queued",
            "current_node": "queued",
            "progress_percent": 0,
            "progress_detail": {
                "phase": "queued",
                "unit": "documents",
                "total": len(document_ids),
                "message": "Research question formation is queued.",
            },
            "errors": [],
            "warnings": [],
            "created_at": "2026-08-31T00:00:00+00:00",
            "updated_at": "2026-08-31T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
        }

    async def preview_objective_scope(self, collection_id, objective_id):
        self.scope_calls.append((collection_id, objective_id))
        if self.scope_error is not None:
            raise self.scope_error
        return ObjectiveScopePreview(
            decisions=(
                ObjectiveScopeDecision(
                    document_id="paper-1",
                    classification="likely_relevant",
                    reason="mapped_research_scope",
                    doc_role="experimental",
                    map_status="sufficient",
                    map_limitations=(),
                    support_basis=("relationship-1",),
                    is_seed=True,
                ),
                ObjectiveScopeDecision(
                    document_id="paper-2",
                    classification="needs_inspection",
                    reason="paper_map_incomplete",
                    doc_role="experimental",
                    map_status="insufficient_map",
                    map_limitations=("Outcome was not visible.",),
                    support_basis=(),
                    is_seed=False,
                ),
            )
        )


class _Service:
    def __init__(self, *, queued: bool = False) -> None:
        self.analysis_status = "queued" if queued else "succeeded"
        self.dispatch_failure_version: int | None = None
        self.start_calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def start_analysis(self, collection_id, objective_id, document_ids):
        self.start_calls.append((collection_id, objective_id, document_ids))
        return await self.queue_analysis(collection_id, objective_id, document_ids)

    async def queue_analysis(self, collection_id, objective_id, document_ids):
        return await self.get_analysis_state(collection_id, objective_id)

    async def execute_queued_analysis(
        self, collection_id, objective_id, analysis_version
    ):
        return await self.get_analysis_state(collection_id, objective_id)

    async def fail_analysis_dispatch(
        self, collection_id, objective_id, analysis_version
    ):
        self.analysis_status = "failed"
        self.dispatch_failure_version = analysis_version
        return await self.get_analysis_state(collection_id, objective_id)

    async def get_analysis_state(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective": StoredObjective(_objective()),
            "analysis": _analysis(status=self.analysis_status),
            "published_analysis": _analysis(),
            "paper_contributions": (_paper_contribution(),),
            "warnings": [],
        }

    async def get_analysis_status(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "status": self.analysis_status,
            "phase": "started" if self.analysis_status == "running" else self.analysis_status,
            "processed_document_count": 0,
            "total_document_count": 1,
            "current_document_id": "paper-1" if self.analysis_status == "running" else None,
            "progress_message": "Analysis is running." if self.analysis_status == "running" else None,
            "error_code": None,
            "error_message": None,
            "created_at": "2026-08-31T00:00:00+00:00",
            "started_at": "2026-08-31T00:00:01+00:00" if self.analysis_status == "running" else None,
            "completed_at": None,
        }

    async def list_findings(self, collection_id, objective_id, **kwargs):
        expected_finding = _finding()
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "items": [
                {
                    "collection_id": expected_finding.collection_id,
                    "objective_id": expected_finding.objective_id,
                    "analysis_version": expected_finding.analysis_version,
                    "finding_id": expected_finding.finding_id,
                    "statement": expected_finding.statement,
                    "factors": list(expected_finding.factors),
                    "outcome": expected_finding.outcome,
                    "direction": expected_finding.direction,
                    "assertion_strength": expected_finding.assertion_strength,
                    "attribution_scope": expected_finding.attribution_scope,
                    "synthesis_status": expected_finding.synthesis_status,
                    "certainty": expected_finding.certainty,
                    "display_rank": expected_finding.display_rank,
                    "mechanisms": [
                        {
                            "source_term": mechanism.source_term,
                            "relation_type": mechanism.relation_type,
                            "target_term": mechanism.target_term,
                            "direction": mechanism.direction,
                            "assertion_strength": mechanism.assertion_strength,
                            "supporting_evidence_ids": list(
                                mechanism.supporting_evidence_ids
                            ),
                        }
                        for mechanism in expected_finding.mechanisms
                    ],
                    "scientific_context": {
                        "material": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in expected_finding.scientific_context.material
                        ],
                        "sample": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in expected_finding.scientific_context.sample
                        ],
                        "process": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in expected_finding.scientific_context.process
                        ],
                        "test": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in expected_finding.scientific_context.test
                        ],
                    },
                    "limitations": list(expected_finding.limitations),
                    "paper_contributions": [
                        {
                            "document_id": contribution.document_id,
                            "analysis_status": contribution.analysis_status,
                            "supporting_evidence_ids": list(
                                contribution.supporting_evidence_ids
                            ),
                            "contradicting_evidence_ids": list(
                                contribution.contradicting_evidence_ids
                            ),
                            "context_evidence_ids": list(
                                contribution.context_evidence_ids
                            ),
                            "condition_boundary_evidence_ids": list(
                                contribution.condition_boundary_evidence_ids
                            ),
                        }
                        for contribution in expected_finding.paper_contributions
                    ],
                    "origin": expected_finding.origin,
                    "source_analysis_version": expected_finding.source_analysis_version,
                    "parent_finding_id": expected_finding.parent_finding_id,
                    "created_by_user_id": expected_finding.created_by_user_id,
                    "created_by_tool_call_id": expected_finding.created_by_tool_call_id,
                    "created_at": (
                        expected_finding.created_at.isoformat()
                        if expected_finding.created_at
                        else None
                    ),
                    **(
                        {"selection_ids": list(expected_finding.selection_ids)}
                        if expected_finding.selection_ids
                        else {}
                    ),
                    **(
                        {
                            "comparison_group_ids": list(
                                expected_finding.comparison_group_ids
                            )
                        }
                        if expected_finding.comparison_group_ids
                        else {}
                    ),
                    **(
                        {"warnings": list(expected_finding.warnings)}
                        if expected_finding.warnings
                        else {}
                    ),
                }
            ],
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "total": 1,
        }

    async def get_finding(
        self, collection_id, objective_id, finding_id, **kwargs
    ):
        expected_finding = _finding()
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "finding": {
                "collection_id": expected_finding.collection_id,
                "objective_id": expected_finding.objective_id,
                "analysis_version": expected_finding.analysis_version,
                "finding_id": expected_finding.finding_id,
                "statement": expected_finding.statement,
                "factors": list(expected_finding.factors),
                "outcome": expected_finding.outcome,
                "direction": expected_finding.direction,
                "assertion_strength": expected_finding.assertion_strength,
                "attribution_scope": expected_finding.attribution_scope,
                "synthesis_status": expected_finding.synthesis_status,
                "certainty": expected_finding.certainty,
                "display_rank": expected_finding.display_rank,
                "mechanisms": [
                    {
                        "source_term": mechanism.source_term,
                        "relation_type": mechanism.relation_type,
                        "target_term": mechanism.target_term,
                        "direction": mechanism.direction,
                        "assertion_strength": mechanism.assertion_strength,
                        "supporting_evidence_ids": list(
                            mechanism.supporting_evidence_ids
                        ),
                    }
                    for mechanism in expected_finding.mechanisms
                ],
                "scientific_context": {
                    "material": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in expected_finding.scientific_context.material
                    ],
                    "sample": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in expected_finding.scientific_context.sample
                    ],
                    "process": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in expected_finding.scientific_context.process
                    ],
                    "test": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in expected_finding.scientific_context.test
                    ],
                },
                "limitations": list(expected_finding.limitations),
                "paper_contributions": [
                    {
                        "document_id": contribution.document_id,
                        "analysis_status": contribution.analysis_status,
                        "supporting_evidence_ids": list(
                            contribution.supporting_evidence_ids
                        ),
                        "contradicting_evidence_ids": list(
                            contribution.contradicting_evidence_ids
                        ),
                        "context_evidence_ids": list(contribution.context_evidence_ids),
                        "condition_boundary_evidence_ids": list(
                            contribution.condition_boundary_evidence_ids
                        ),
                    }
                    for contribution in expected_finding.paper_contributions
                ],
                "origin": expected_finding.origin,
                "source_analysis_version": expected_finding.source_analysis_version,
                "parent_finding_id": expected_finding.parent_finding_id,
                "created_by_user_id": expected_finding.created_by_user_id,
                "created_by_tool_call_id": expected_finding.created_by_tool_call_id,
                "created_at": (
                    expected_finding.created_at.isoformat()
                    if expected_finding.created_at
                    else None
                ),
                **(
                    {"selection_ids": list(expected_finding.selection_ids)}
                    if expected_finding.selection_ids
                    else {}
                ),
                **(
                    {
                        "comparison_group_ids": list(
                            expected_finding.comparison_group_ids
                        )
                    }
                    if expected_finding.comparison_group_ids
                    else {}
                ),
                **(
                    {"warnings": list(expected_finding.warnings)}
                    if expected_finding.warnings
                    else {}
                ),
            },
        }

    async def list_evidence(self, collection_id, objective_id, **kwargs):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "finding_id": kwargs["finding_id"],
            "items": [objective_evidence_response(_evidence())],
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "total": 1,
        }

    async def get_evidence_map(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "projection_version": "objective-evidence-map.v1",
            "complete": True,
            "coverage": {
                "total_document_count": 1,
                "analyzed_document_count": 1,
                "excluded_document_count": 0,
                "failed_document_count": 0,
                "direct_evidence_document_count": 1,
                "finding_count": 1,
                "evidence_count": 1,
                "source_count": 1,
                "unlinked_evidence_count": 0,
            },
            "nodes": [
                {
                    "id": "objective:obj-1",
                    "type": "objective",
                    "label": _objective().question,
                    "objective_id": "obj-1",
                    "question": _objective().question,
                    "material_scope": ["Alloy A"],
                    "variables": ["temperature"],
                    "outcomes": ["strength"],
                },
                {
                    "id": "finding:finding-1",
                    "type": "finding",
                    "label": _finding().statement,
                    "finding_id": "finding-1",
                    "statement": _finding().statement,
                    "factors": ["temperature"],
                    "outcome": "strength",
                    "direction": "increase",
                    "assertion_strength": "associative",
                    "synthesis_status": "insufficient_confirmation",
                    "certainty": 0.5,
                    "limitations": ["Supported by one paper."],
                },
                {
                    "id": "evidence:evidence-1",
                    "type": "evidence",
                    "label": "Tensile strength increased to 620 MPa.",
                    "evidence_id": "evidence-1",
                    "document_id": "paper-1",
                    "evidence_role": "direct_result",
                    "attribution_scope": "isolated_effect",
                    "confidence": 0.9,
                    "direction": "increase",
                    "outcome": "strength",
                    "source_excerpt": _evidence().source_excerpt,
                },
                {
                    "id": "source:source-1",
                    "type": "source",
                    "label": "Text window · block-7",
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-7",
                    "source_excerpt": _evidence().source_excerpt,
                    "page_numbers": [7],
                    "evidence_ids": ["evidence-1"],
                },
                {
                    "id": "document:paper-1",
                    "type": "document",
                    "label": "Paper one",
                    "document_id": "paper-1",
                    "analysis_status": "analyzed",
                    "evidence_disposition": "comparable_evidence",
                    "evidence_disposition_reason": None,
                },
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source": "objective:obj-1",
                    "target": "finding:finding-1",
                    "relation": "has_finding",
                    "condition_boundary": False,
                },
                {
                    "id": "edge-2",
                    "source": "finding:finding-1",
                    "target": "evidence:evidence-1",
                    "relation": "supports",
                    "condition_boundary": False,
                },
            ],
        }


def _client(
    service: _Service | None = None,
    *,
    repository: _Repository | None = None,
    discovery_service: _DiscoveryService | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.state.objective_repository = repository or _Repository()
    app.state.objective_analysis_service = service or _Service()
    scope_and_discovery = discovery_service or _DiscoveryService()
    app.state.objective_discovery_service = scope_and_discovery
    app.state.experiment_analysis_service = scope_and_discovery
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _ranked_objective(rank: int) -> ResearchObjective:
    return ResearchObjective(
        collection_id="col-1",
        objective_id=_text(f"obj-{rank}")
        or build_research_objective_id(
            question=_text(f"How does variable {rank} affect outcome {rank}?") or "",
            material_scope=(),
            variables=normalize_objective_terms([f"variable {rank}"]),
            outcomes=normalize_objective_terms([f"outcome {rank}"]),
            mechanisms=(),
            constraints=(),
            requested_comparator=None,
            parent_objective_id=None,
            parent_analysis_version=None,
        ),
        question=_text(f"How does variable {rank} affect outcome {rank}?") or "",
        material_scope=(),
        variables=normalize_objective_terms([f"variable {rank}"]),
        outcomes=normalize_objective_terms([f"outcome {rank}"]),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=normalize_objective_terms([f"paper-{rank}"]),
        excluded_document_ids=(),
        confidence=normalize_objective_confidence(1 - rank / 100),
        reason=None,
        source_relationship_ids=normalize_objective_terms([f"relationship-{rank}"]),
        rank=_positive_int_or_none(rank),
    )


def _ranked_facts(count: int) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=tuple(
            PreparedDocumentInput(f"paper-{rank}", f"fingerprint-paper-{rank}")
            for rank in range(1, count + 1)
        ),
        research_objectives=tuple(
            _ranked_objective(rank) for rank in range(1, count + 1)
        ),
        study_dispositions=tuple(
            PaperStudyDisposition(
                document_id=_text(f"paper-{rank}") or "",
                study_id=_text(f"study-{rank}") or "",
                relationship_id=_text(f"relationship-{rank}") or "",
                status=PaperStudyDisposition._status("promoted"),
                objective_id=_text(f"obj-{rank}"),
            )
            for rank in range(1, count + 1)
        ),
    )


def _default_objective_facts() -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"
            ),
        ),
        research_objectives=(_objective(),),
        study_dispositions=(
            PaperStudyDisposition(
                document_id="paper-1",
                study_id="study-1",
                relationship_id="relationship-1",
                status=PaperStudyDisposition._status("promoted"),
                objective_id="obj-1",
            ),
        ),
    )


def test_objective_list_returns_every_ranked_candidate_when_limit_is_omitted() -> None:
    repository = _Repository(_ranked_facts(8))

    response = _client(repository=repository).get("/collections/col-1/objectives")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert payload["offset"] == 0
    assert payload["limit"] is None
    assert [objective["objective_id"] for objective in payload["objectives"]] == [
        f"obj-{rank}" for rank in range(1, 9)
    ]
    assert [objective["rank"] for objective in payload["objectives"]] == list(
        range(1, 9)
    )


def test_objective_list_exposes_candidates_after_rank_six() -> None:
    repository = _Repository(_ranked_facts(8))

    response = _client(repository=repository).get(
        "/collections/col-1/objectives",
        params={"offset": 6, "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert [objective["objective_id"] for objective in payload["objectives"]] == [
        "obj-7",
        "obj-8",
    ]
    assert [objective["rank"] for objective in payload["objectives"]] == [7, 8]


def test_objective_list_hides_stale_objectives_from_an_unready_build() -> None:
    class UnreadyRepository(_Repository):
        async def list_objectives(self, collection_id):
            return ()

    response = _client(repository=UnreadyRepository()).get(
        "/collections/col-1/objectives"
    )

    assert response.status_code == 200
    assert response.json()["objectives"] == []
    assert response.json()["total"] == 0


def test_objective_scope_returns_complete_analysis_ids_and_decisions() -> None:
    service = _DiscoveryService()

    response = _client(discovery_service=service).get(
        "/collections/col-1/objectives/obj-1/scope"
    )

    assert response.status_code == 200
    assert response.json() == {
        "collection_id": "col-1",
        "objective_id": "obj-1",
        "counts": {
            "likely_relevant": 1,
            "needs_inspection": 1,
            "confidently_out_of_scope": 0,
        },
        "recommended_document_ids": ["paper-1"],
        "review_document_ids": ["paper-2"],
        "excluded_document_ids": [],
        "decisions": [
            {
                "document_id": "paper-1",
                "classification": "likely_relevant",
                "reason": "mapped_research_scope",
                "doc_role": "experimental",
                "map_status": "sufficient",
                "map_limitations": [],
                "support_basis": ["relationship-1"],
                "is_seed": True,
            },
            {
                "document_id": "paper-2",
                "classification": "needs_inspection",
                "reason": "paper_map_incomplete",
                "doc_role": "experimental",
                "map_status": "insufficient_map",
                "map_limitations": ["Outcome was not visible."],
                "support_basis": [],
                "is_seed": False,
            },
        ],
        "support_is_evidence": False,
    }
    assert service.scope_calls == [("col-1", "obj-1")]


def test_objective_scope_returns_404_when_objective_does_not_exist() -> None:
    service = _DiscoveryService(
        scope_error=ResearchObjectiveNotFoundError("col-1", "obj-missing")
    )

    response = _client(discovery_service=service).get(
        "/collections/col-1/objectives/obj-missing/scope"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "research_objective_not_found"


def test_objective_scope_returns_409_when_paper_maps_are_not_ready() -> None:
    service = _DiscoveryService(
        scope_error=ObjectiveScopeNotReadyError("col-1")
    )

    response = _client(discovery_service=service).get(
        "/collections/col-1/objectives/obj-1/scope"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "objective_scope_not_ready",
        "message": "objective paper scope not ready: col-1",
        "collection_id": "col-1",
        "objective_id": "obj-1",
    }


def test_start_analysis_uses_the_canonical_service_dispatch() -> None:
    service = _Service(queued=True)

    response = _client(service).post(
        "/collections/col-1/objectives/obj-1/analysis",
        json={"document_ids": ["paper-1"]},
    )

    assert response.status_code == 200
    assert response.json()["active_analysis"]["status"] == "queued"
    assert service.start_calls == [("col-1", "obj-1", ("paper-1",))]


def test_objective_commands_accept_a_complete_scope_beyond_one_hundred_documents() -> None:
    document_ids = [f"paper-{index}" for index in range(1, 132)]
    discovery_service = _DiscoveryService()
    analysis_service = _Service(queued=True)
    client = _client(
        analysis_service,
        discovery_service=discovery_service,
    )

    discovery_response = client.post(
        "/collections/col-1/objective-discovery",
        json={"document_ids": document_ids},
    )
    analysis_response = client.post(
        "/collections/col-1/objectives/obj-1/analysis",
        json={"document_ids": document_ids},
    )

    assert discovery_response.status_code == 200
    assert analysis_response.status_code == 200
    assert discovery_response.json()["run_id"] == "run-discovery-1"
    assert discovery_response.json()["pipeline_name"] == "objective_discovery"
    assert discovery_response.json()["status"] == "queued"
    assert discovery_service.discovery_calls == [
        ("col-1", tuple(document_ids)),
    ]
    assert analysis_service.start_calls == [
        ("col-1", "obj-1", tuple(document_ids)),
    ]


def test_start_analysis_preserves_the_dispatch_failure_http_contract() -> None:
    class DispatchFailureService(_Service):
        async def start_analysis(self, collection_id, objective_id, document_ids):
            raise ObjectiveAnalysisDispatchError(collection_id, objective_id, 1)

    response = _client(DispatchFailureService(), raise_server_exceptions=False).post(
        "/collections/col-1/objectives/obj-1/analysis",
        json={"document_ids": ["paper-1"]},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "objective_analysis_dispatch_failed"
    assert response.json()["detail"]["analysis_version"] == 1


def test_duplicate_objective_detail_route_is_not_registered() -> None:
    response = _client().get("/collections/col-1/objectives/obj-1")

    assert response.status_code == 404


def test_confirm_objective_route_is_not_registered() -> None:
    response = _client().post("/collections/col-1/objectives/obj-1/confirm")

    assert response.status_code == 404


def test_objective_analysis_api_exposes_definition_and_separate_analysis_state(
) -> None:
    response = _client().get("/collections/col-1/objectives/obj-1/analysis")

    assert response.status_code == 200
    payload = response.json()
    assert payload["objective"]["confirmation_status"] == "confirmed"
    assert payload["active_analysis"]["status"] == "succeeded"
    assert payload["published_analysis"]["analysis_version"] == 1
    assert "diagnostics" not in payload["active_analysis"]
    assert "diagnostics" not in payload["published_analysis"]
    assert payload["paper_contributions"] == [
        {
            **{
                "collection_id": _paper_contribution().collection_id,
                "objective_id": _paper_contribution().objective_id,
                "analysis_version": _paper_contribution().analysis_version,
                "document_id": _paper_contribution().document_id,
                "analysis_status": _paper_contribution().analysis_status,
                "relevance": _paper_contribution().relevance,
                "paper_role": _paper_contribution().paper_role,
                "contribution_summary": _paper_contribution().contribution_summary,
                "material_match": list(_paper_contribution().material_match),
                "changed_variables": list(_paper_contribution().changed_variables),
                "measured_property_scope": list(
                    _paper_contribution().measured_property_scope
                ),
                "test_environment_scope": list(
                    _paper_contribution().test_environment_scope
                ),
                "exclusion_reason": _paper_contribution().exclusion_reason,
                "warnings": list(_paper_contribution().warnings),
                "confidence": _paper_contribution().confidence,
                "evidence_disposition": _paper_contribution().evidence_disposition,
                "routed_source_count": _paper_contribution().routed_source_count,
                "extracted_source_count": _paper_contribution().extracted_source_count,
                "comparable_evidence_count": _paper_contribution().comparable_evidence_count,
                "failed_source_count": _paper_contribution().failed_source_count,
                "uninspected_source_count": _paper_contribution().uninspected_source_count,
                "evidence_disposition_reason": _paper_contribution().evidence_disposition_reason,
                "evidence_status_counts": {
                    status: count
                    for status, count in _paper_contribution().evidence_status_counts
                },
                "inspected_source_refs": [
                    {
                        "source_kind": source_ref.source_kind,
                        "source_ref": source_ref.source_ref,
                        "source_digest": source_ref.source_digest,
                    }
                    for source_ref in _paper_contribution().inspected_source_refs
                ],
            },
        }
    ]
    assert payload["active_analysis"]["stats"] == {
        "duration_ms": 1250,
        "token_usage": {
            "input_tokens": 300,
            "output_tokens": 50,
            "total_tokens": 350,
        },
        "model_usage": [
            {
                "model_name": "model-1",
                "request_count": 2,
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 50,
                    "total_tokens": 350,
                },
                "unreported_request_count": 0,
            }
        ],
        "unreported_request_count": 0,
        "prompt_versions": {"paper_framing": "paper_framing.v1"},
    }
    assert "status" not in payload["objective"]
    assert "understanding" not in payload


def test_objective_analysis_status_api_returns_only_progress_state() -> None:
    response = _client(_Service(queued=True)).get(
        "/collections/col-1/objectives/obj-1/analysis/status"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["analysis_version"] == 1
    assert "paper_contributions" not in payload
    assert "published_analysis" not in payload
    assert "stats" not in payload


def test_finding_api_returns_canonical_finding_without_claim_identity() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/findings",
        params={"analysis_version": 1, "offset": 0, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["finding_id"] == "finding-1"
    assert payload["items"][0]["factors"] == ["temperature"]
    assert payload["items"][0]["outcome"] == "strength"
    assert payload["items"][0]["paper_contributions"][0]["supporting_evidence_ids"] == [
        "evidence-1"
    ]
    assert payload["items"][0]["created_by_tool_call_id"] is None
    assert "finding_level" not in str(payload)
    assert "claim_id" not in str(payload)
    assert "logic_chain_id" not in str(payload)


def test_evidence_api_returns_exact_source_excerpt_and_locator() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/evidence",
        params={"analysis_version": 1, "finding_id": "finding-1"},
    )

    assert response.status_code == 200
    evidence = response.json()["items"][0]
    assert evidence["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert evidence["source_ref"] == "block-7"
    assert evidence["page_numbers"] == [7]
    assert evidence["reported_result"]["result_kind"] == "observed"
    assert evidence["scientific_context"]["process"][0]["context_scope"] == (
        "simulation"
    )
    assert evidence["created_by_tool_call_id"] is None
    assert "anchor_ids" not in evidence
    assert "evidence_unit_id" not in evidence


def test_objective_result_apis_expose_agent_authoring_provenance() -> None:
    created_at = datetime(2026, 9, 1, tzinfo=UTC)

    class AgentAuthoredService(_Service):
        async def get_analysis_state(self, collection_id, objective_id):
            analysis = replace(
                _analysis(),
                origin="agent_authored",
                scientific_record_source="authored_snapshot",
                created_by_user_id="user-1",
                created_by_tool_call_id="call-agent-analysis",
            )
            return {
                "collection_id": collection_id,
                "objective": StoredObjective(_objective()),
                "analysis": analysis,
                "published_analysis": analysis,
                "paper_contributions": (_paper_contribution(),),
                "warnings": [],
            }

        async def list_findings(self, collection_id, objective_id, **kwargs):
            finding = replace(
                _finding(),
                analysis_version=2,
                origin="agent_authored",
                source_analysis_version=1,
                created_by_user_id="user-1",
                created_by_tool_call_id="call-agent-finding",
                created_at=created_at,
            )
            return {
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": 2,
                "items": [
                    {
                        "collection_id": finding.collection_id,
                        "objective_id": finding.objective_id,
                        "analysis_version": finding.analysis_version,
                        "finding_id": finding.finding_id,
                        "statement": finding.statement,
                        "factors": list(finding.factors),
                        "outcome": finding.outcome,
                        "direction": finding.direction,
                        "assertion_strength": finding.assertion_strength,
                        "attribution_scope": finding.attribution_scope,
                        "synthesis_status": finding.synthesis_status,
                        "certainty": finding.certainty,
                        "display_rank": finding.display_rank,
                        "mechanisms": [
                            {
                                "source_term": mechanism.source_term,
                                "relation_type": mechanism.relation_type,
                                "target_term": mechanism.target_term,
                                "direction": mechanism.direction,
                                "assertion_strength": mechanism.assertion_strength,
                                "supporting_evidence_ids": list(
                                    mechanism.supporting_evidence_ids
                                ),
                            }
                            for mechanism in finding.mechanisms
                        ],
                        "scientific_context": {
                            "material": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.material
                            ],
                            "sample": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.sample
                            ],
                            "process": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.process
                            ],
                            "test": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.test
                            ],
                        },
                        "limitations": list(finding.limitations),
                        "paper_contributions": [
                            {
                                "document_id": contribution.document_id,
                                "analysis_status": contribution.analysis_status,
                                "supporting_evidence_ids": list(
                                    contribution.supporting_evidence_ids
                                ),
                                "contradicting_evidence_ids": list(
                                    contribution.contradicting_evidence_ids
                                ),
                                "context_evidence_ids": list(
                                    contribution.context_evidence_ids
                                ),
                                "condition_boundary_evidence_ids": list(
                                    contribution.condition_boundary_evidence_ids
                                ),
                            }
                            for contribution in finding.paper_contributions
                        ],
                        "origin": finding.origin,
                        "source_analysis_version": finding.source_analysis_version,
                        "parent_finding_id": finding.parent_finding_id,
                        "created_by_user_id": finding.created_by_user_id,
                        "created_by_tool_call_id": finding.created_by_tool_call_id,
                        "created_at": (
                            finding.created_at.isoformat()
                            if finding.created_at
                            else None
                        ),
                        **(
                            {"selection_ids": list(finding.selection_ids)}
                            if finding.selection_ids
                            else {}
                        ),
                        **(
                            {"comparison_group_ids": list(finding.comparison_group_ids)}
                            if finding.comparison_group_ids
                            else {}
                        ),
                        **(
                            {"warnings": list(finding.warnings)}
                            if finding.warnings
                            else {}
                        ),
                    }
                ],
                "offset": kwargs["offset"],
                "limit": kwargs["limit"],
                "total": 1,
            }

        async def list_evidence(self, collection_id, objective_id, **kwargs):
            evidence = replace(
                _evidence(),
                analysis_version=2,
                origin="agent_authored",
                source_analysis_version=1,
                created_by_user_id="user-1",
                created_by_tool_call_id="call-agent-evidence",
                created_at=created_at,
            )
            return {
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": 2,
                "finding_id": kwargs["finding_id"],
                "items": [objective_evidence_response(evidence)],
                "offset": kwargs["offset"],
                "limit": kwargs["limit"],
                "total": 1,
            }

    client = _client(AgentAuthoredService())

    analysis_response = client.get(
        "/collections/col-1/objectives/obj-1/analysis"
    )
    findings_response = client.get(
        "/collections/col-1/objectives/obj-1/findings"
    )
    evidence_response = client.get(
        "/collections/col-1/objectives/obj-1/evidence"
    )

    assert analysis_response.status_code == 200
    assert findings_response.status_code == 200
    assert evidence_response.status_code == 200
    assert (
        analysis_response.json()["published_analysis"]["created_by_tool_call_id"]
        == "call-agent-analysis"
    )
    assert (
        findings_response.json()["items"][0]["created_by_tool_call_id"]
        == "call-agent-finding"
    )
    assert (
        evidence_response.json()["items"][0]["created_by_tool_call_id"]
        == "call-agent-evidence"
    )


def test_evidence_map_api_returns_the_published_objective_projection() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/evidence-map"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["analysis_version"] == 1
    assert [node["type"] for node in payload["nodes"]] == [
        "objective",
        "finding",
        "evidence",
        "source",
        "document",
    ]
    assert payload["edges"][1]["relation"] == "supports"

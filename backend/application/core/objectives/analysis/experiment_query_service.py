"""Read-only projections and exports for experiment-backed analysis."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.research_objective import ObjectiveEvidence
from domain.core.scientific_fact import ScientificAttribute, ScientificContext
from repositories.comparison_group_repository import ComparisonGroupRepository
from repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)


@dataclass(frozen=True)
class ExperimentAnalysisBundle:
    """All fixed-version records used by one Objective analysis snapshot."""

    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]
    revisions: tuple[StoredPaperExperimentRevision, ...]


class ExperimentQueryService:
    """Assemble one immutable analysis view and expose lossless exports."""

    def __init__(
        self,
        paper_experiment_repository: PaperExperimentRepository,
        selection_repository: ObjectiveExperimentSelectionRepository,
        group_repository: ComparisonGroupRepository,
        finding_repository: ExperimentFindingRepository,
        objective_repository: Any | None = None,
    ) -> None:
        self.paper_experiment_repository = paper_experiment_repository
        self.selection_repository = selection_repository
        self.group_repository = group_repository
        self.finding_repository = finding_repository
        self.objective_repository = objective_repository

    async def read_analysis_bundle(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ExperimentAnalysisBundle:
        if analysis_version < 1:
            raise ValueError("analysis_version must be positive")
        await self._validate_analysis_snapshot(
            collection_id,
            objective_id,
            analysis_version,
        )
        selections = await self.selection_repository.list_selections(
            collection_id,
            objective_id,
            analysis_version,
        )
        groups = await self.group_repository.list_groups(
            collection_id,
            objective_id,
            analysis_version,
        )
        findings = await self.finding_repository.list_findings(
            collection_id,
            objective_id,
            analysis_version,
        )

        revisions_by_identity: dict[tuple[str, int], StoredPaperExperimentRevision] = {}
        for selection in selections:
            identity = (selection.experiment_id, selection.experiment_version)
            if identity in revisions_by_identity:
                continue
            stored = await self.paper_experiment_repository.read_revision(*identity)
            if stored is None:
                raise ValueError(
                    "selection references a missing experiment revision: "
                    f"{identity[0]}/{identity[1]}"
                )
            revisions_by_identity[identity] = stored

        return ExperimentAnalysisBundle(
            selections=selections,
            groups=groups,
            findings=findings,
            revisions=tuple(
                revisions_by_identity[key] for key in sorted(revisions_by_identity)
            ),
        )

    async def _validate_analysis_snapshot(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        """Reject empty or in-flight snapshots when the runtime can inspect them.

        The repository dependency is optional so small in-memory projections can
        remain useful in isolation.  The production wiring supplies the
        Objective repository, which makes the HTTP export a fixed analysis
        snapshot rather than an unscoped query that can return an empty 200 for
        a typo or a running analysis.
        """

        reader = getattr(self.objective_repository, "read_analysis", None)
        if not callable(reader):
            return
        analysis = await reader(collection_id, objective_id, analysis_version)
        if analysis is None:
            raise FileNotFoundError(
                "analysis snapshot not found: "
                f"{collection_id}/{objective_id}/v{analysis_version}"
            )
        status = str(getattr(analysis, "status", "") or "").strip().casefold()
        if status and status != "succeeded":
            raise ValueError(
                "analysis snapshot is not completed: "
                f"{collection_id}/{objective_id}/v{analysis_version}"
            )

    async def export_json(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        bundle = await self.read_analysis_bundle(
            collection_id,
            objective_id,
            analysis_version,
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": analysis_version,
            "projection_version": "paper-experiment-analysis.v1",
            **{
                "selections": [
                    {
                        "selection_id": item.selection_id,
                        "objective_id": item.objective_id,
                        "analysis_version": item.analysis_version,
                        "experiment_id": item.experiment_id,
                        "experiment_version": item.experiment_version,
                        "outcome": item.outcome,
                        "measurement_keys": list(item.measurement_keys),
                        "comparison_keys": list(item.comparison_keys),
                        "missing_context": list(item.missing_context),
                        "reasons": list(item.reasons),
                    }
                    for item in bundle.selections
                ],
                "comparison_groups": [
                    {
                        "group_id": item.group_id,
                        "objective_id": item.objective_id,
                        "analysis_version": item.analysis_version,
                        "outcome": item.outcome,
                        "comparison_target": item.comparison_target,
                        "comparison_basis": list(item.comparison_basis),
                        "members": [
                            {
                                "selection_id": item.selection_id,
                                "role": item.role,
                                "comparability": item.comparability,
                                "reason": item.reason,
                            }
                            for item in item.members
                        ],
                        "normalizations": [dict(item) for item in item.normalizations],
                        "status": item.status,
                        "limitations": list(item.limitations),
                    }
                    for item in bundle.groups
                ],
                "findings": [
                    {
                        "collection_id": item.collection_id,
                        "objective_id": item.objective_id,
                        "analysis_version": item.analysis_version,
                        "finding_id": item.finding_id,
                        "statement": item.statement,
                        "factors": list(item.factors),
                        "outcome": item.outcome,
                        "direction": item.direction,
                        "assertion_strength": item.assertion_strength,
                        "attribution_scope": item.attribution_scope,
                        "synthesis_status": item.synthesis_status,
                        "certainty": item.certainty,
                        "display_rank": item.display_rank,
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
                            for mechanism in item.mechanisms
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
                                for attribute in item.scientific_context.material
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
                                for attribute in item.scientific_context.sample
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
                                for attribute in item.scientific_context.process
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
                                for attribute in item.scientific_context.test
                            ],
                        },
                        "limitations": list(item.limitations),
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
                            for contribution in item.paper_contributions
                        ],
                        "origin": item.origin,
                        "source_analysis_version": item.source_analysis_version,
                        "parent_finding_id": item.parent_finding_id,
                        "created_by_user_id": item.created_by_user_id,
                        "created_by_tool_call_id": item.created_by_tool_call_id,
                        "created_at": (
                            item.created_at.isoformat() if item.created_at else None
                        ),
                        **(
                            {"selection_ids": list(item.selection_ids)}
                            if item.selection_ids
                            else {}
                        ),
                        **(
                            {"comparison_group_ids": list(item.comparison_group_ids)}
                            if item.comparison_group_ids
                            else {}
                        ),
                        **({"warnings": list(item.warnings)} if item.warnings else {}),
                    }
                    for item in bundle.findings
                ],
                "experiments": [
                    {
                        "experiment_id": item.revision.experiment_id,
                        "document_id": item.revision.document_id,
                        "experiment_version": item.revision.experiment_version,
                        "source_fingerprint": item.revision.source_fingerprint,
                        "label": item.revision.label,
                        "scope_description": item.revision.scope_description,
                        "design_type": item.revision.design_type,
                        "identity_status": item.revision.identity_status,
                        "binding_status": item.revision.binding_status,
                        "variants": [
                            {
                                "variant_key": item.variant_key,
                                "variant_label": item.variant_label,
                                "subject_attributes": [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        **(
                                            {"context_scope": item.context_scope}
                                            if item.context_scope != "unknown"
                                            else {}
                                        ),
                                        **(
                                            {
                                                "applies_to_outcomes": list(
                                                    item.applies_to_outcomes
                                                )
                                            }
                                            if item.applies_to_outcomes
                                            else {}
                                        ),
                                    }
                                    for item in item.subject_attributes
                                ],
                                "intervention_attributes": [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        **(
                                            {"context_scope": item.context_scope}
                                            if item.context_scope != "unknown"
                                            else {}
                                        ),
                                        **(
                                            {
                                                "applies_to_outcomes": list(
                                                    item.applies_to_outcomes
                                                )
                                            }
                                            if item.applies_to_outcomes
                                            else {}
                                        ),
                                    }
                                    for item in item.intervention_attributes
                                ],
                                "state": [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        **(
                                            {"context_scope": item.context_scope}
                                            if item.context_scope != "unknown"
                                            else {}
                                        ),
                                        **(
                                            {
                                                "applies_to_outcomes": list(
                                                    item.applies_to_outcomes
                                                )
                                            }
                                            if item.applies_to_outcomes
                                            else {}
                                        ),
                                    }
                                    for item in item.state
                                ],
                                "population_scope": (
                                    dict(item.population_scope)
                                    if item.population_scope is not None
                                    else None
                                ),
                                "source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.source_refs
                                ],
                                "binding_source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.binding_source_refs
                                ],
                                "binding_status": item.binding_status,
                                "notes": list(item.notes),
                                "identity_specificity": item.identity_specificity,
                                "missing_dimensions": list(item.missing_dimensions),
                                "identity_evidence": list(item.identity_evidence),
                            }
                            for item in item.revision.variants
                        ],
                        "test_conditions": [
                            {
                                "test_key": item.test_key,
                                "test_type": item.test_type,
                                "parameters": [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        **(
                                            {"context_scope": item.context_scope}
                                            if item.context_scope != "unknown"
                                            else {}
                                        ),
                                        **(
                                            {
                                                "applies_to_outcomes": list(
                                                    item.applies_to_outcomes
                                                )
                                            }
                                            if item.applies_to_outcomes
                                            else {}
                                        ),
                                    }
                                    for item in item.parameters
                                ],
                                "population_scope": (
                                    dict(item.population_scope)
                                    if item.population_scope is not None
                                    else None
                                ),
                                "source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.source_refs
                                ],
                                "binding_status": item.binding_status,
                                "notes": list(item.notes),
                                "protocol_specificity": item.protocol_specificity,
                                "test_identity_status": item.test_identity_status,
                                "protocol_completeness": item.protocol_completeness,
                                "missing_parameters": list(item.missing_parameters),
                                "method": item.method,
                                "standard": item.standard,
                                "outcome_scope": list(item.outcome_scope),
                                "binding_source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.binding_source_refs
                                ],
                                "protocol_evidence": list(item.protocol_evidence),
                            }
                            for item in item.revision.test_conditions
                        ],
                        "measurements": [
                            {
                                "measurement_key": item.measurement_key,
                                "outcome": item.outcome,
                                "variant_key": item.variant_key,
                                "test_key": item.test_key,
                                "value": item.value,
                                "unit": item.unit,
                                "result_text": item.result_text,
                                "statistics": dict(item.statistics),
                                "measurement_scope": dict(item.measurement_scope),
                                "result_kind": item.result_kind,
                                "source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.source_refs
                                ],
                                "binding_source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.binding_source_refs
                                ],
                                "binding_status": item.binding_status,
                                "notes": list(item.notes),
                            }
                            for item in item.revision.measurements
                        ],
                        "comparisons": [
                            {
                                "comparison_key": item.comparison_key,
                                "baseline_variant_key": item.baseline_variant_key,
                                "target_variant_key": item.target_variant_key,
                                "outcome": item.outcome,
                                "baseline_measurement_keys": list(
                                    item.baseline_measurement_keys
                                ),
                                "target_measurement_keys": list(
                                    item.target_measurement_keys
                                ),
                                "changed_variables": [
                                    {
                                        "name": item.name,
                                        "baseline_value": item.baseline_value,
                                        "target_value": item.target_value,
                                        "unit": item.unit,
                                    }
                                    for item in item.changed_variables
                                ],
                                "matched_conditions": [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        **(
                                            {"context_scope": item.context_scope}
                                            if item.context_scope != "unknown"
                                            else {}
                                        ),
                                        **(
                                            {
                                                "applies_to_outcomes": list(
                                                    item.applies_to_outcomes
                                                )
                                            }
                                            if item.applies_to_outcomes
                                            else {}
                                        ),
                                    }
                                    for item in item.matched_conditions
                                ],
                                "basis": item.basis,
                                "direction": item.direction,
                                "reported_statement": item.reported_statement,
                                "attribution_scope": item.attribution_scope,
                                "status": item.status,
                                "reasons": list(item.reasons),
                                "source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.source_refs
                                ],
                                "binding_source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.binding_source_refs
                                ],
                                "relation_status": item.relation_status,
                            }
                            for item in item.revision.comparisons
                        ],
                        "reported_interpretations": [
                            {
                                "statement": item.statement,
                                "kind": item.kind,
                                "measurement_keys": list(item.measurement_keys),
                                "comparison_keys": list(item.comparison_keys),
                                "source_refs": [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in item.source_refs
                                ],
                            }
                            for item in item.revision.reported_interpretations
                        ],
                        "source_refs": [
                            {
                                "document_id": item.document_id,
                                "source_fingerprint": item.source_fingerprint,
                                "source_kind": item.source_kind,
                                "source_ref": item.source_ref,
                                "quote": item.quote,
                            }
                            for item in item.revision.source_refs
                        ],
                        "unresolved_issues": [
                            dict(item) for item in item.revision.unresolved_issues
                        ],
                    }
                    for item in bundle.revisions
                ],
            },
        }

    async def export_csv(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> str:
        bundle = await self.read_analysis_bundle(
            collection_id,
            objective_id,
            analysis_version,
        )
        revision_by_identity = {
            (
                item.revision.experiment_id,
                item.revision.experiment_version,
            ): item.revision
            for item in bundle.revisions
        }
        variants_by_identity = {
            (
                revision.experiment_id,
                revision.experiment_version,
                variant.variant_key,
            ): variant
            for revision in (item.revision for item in bundle.revisions)
            for variant in revision.variants
        }
        tests_by_identity = {
            (revision.experiment_id, revision.experiment_version, test.test_key): test
            for revision in (item.revision for item in bundle.revisions)
            for test in revision.test_conditions
        }
        rows: list[dict[str, str]] = []
        for selection in bundle.selections:
            revision = revision_by_identity.get(
                (selection.experiment_id, selection.experiment_version)
            )
            if revision is None:
                continue
            selected_keys = set(selection.measurement_keys)
            for measurement in revision.measurements:
                if measurement.measurement_key not in selected_keys:
                    continue
                variant = variants_by_identity.get(
                    (
                        revision.experiment_id,
                        revision.experiment_version,
                        measurement.variant_key,
                    )
                )
                test = tests_by_identity.get(
                    (
                        revision.experiment_id,
                        revision.experiment_version,
                        measurement.test_key,
                    )
                )
                comparison_keys = tuple(
                    comparison.comparison_key
                    for comparison in revision.comparisons
                    if measurement.measurement_key
                    in (
                        *comparison.baseline_measurement_keys,
                        *comparison.target_measurement_keys,
                    )
                )
                rows.append(
                    {
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": str(analysis_version),
                        "selection_id": selection.selection_id,
                        "experiment_id": revision.experiment_id,
                        "experiment_version": str(revision.experiment_version),
                        "measurement_key": measurement.measurement_key,
                        "variant_key": measurement.variant_key or "",
                        "variant_label": variant.variant_label if variant else "",
                        "variant_subject_attributes": json.dumps(
                            (
                                [
                                    scientific_attribute_response(item)
                                    for item in variant.subject_attributes
                                ]
                                if variant
                                else []
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_intervention_attributes": json.dumps(
                            (
                                [
                                    scientific_attribute_response(item)
                                    for item in variant.intervention_attributes
                                ]
                                if variant
                                else []
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_state": json.dumps(
                            (
                                [
                                    scientific_attribute_response(item)
                                    for item in variant.state
                                ]
                                if variant
                                else []
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_population_scope": json.dumps(
                            (
                                dict(variant.population_scope)
                                if variant and variant.population_scope is not None
                                else {}
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_binding_status": (
                            variant.binding_status if variant else ""
                        ),
                        "variant_source_refs": json.dumps(
                            (
                                [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in variant.source_refs
                                ]
                                if variant
                                else []
                            ),
                            ensure_ascii=False,
                        ),
                        "variant_binding_source_refs": json.dumps(
                            (
                                [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in variant.binding_source_refs
                                ]
                                if variant
                                else []
                            ),
                            ensure_ascii=False,
                        ),
                        "test_key": measurement.test_key or "",
                        "test_type": test.test_type if test else "",
                        "test_parameters": json.dumps(
                            (
                                [
                                    scientific_attribute_response(item)
                                    for item in test.parameters
                                ]
                                if test
                                else []
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "test_population_scope": json.dumps(
                            (
                                dict(test.population_scope)
                                if test and test.population_scope is not None
                                else {}
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "test_method": test.method if test and test.method else "",
                        "test_standard": (
                            test.standard if test and test.standard else ""
                        ),
                        "test_outcome_scope": json.dumps(
                            list(test.outcome_scope) if test else [],
                            ensure_ascii=False,
                        ),
                        "test_protocol_specificity": (
                            test.protocol_specificity if test else ""
                        ),
                        "test_identity_status": (
                            test.test_identity_status if test else ""
                        ),
                        "test_protocol_completeness": (
                            test.protocol_completeness if test else ""
                        ),
                        "test_missing_parameters": json.dumps(
                            list(test.missing_parameters) if test else [],
                            ensure_ascii=False,
                        ),
                        "test_binding_status": test.binding_status if test else "",
                        "test_source_refs": json.dumps(
                            (
                                [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in test.source_refs
                                ]
                                if test
                                else []
                            ),
                            ensure_ascii=False,
                        ),
                        "test_binding_source_refs": json.dumps(
                            (
                                [
                                    {
                                        "document_id": item.document_id,
                                        "source_fingerprint": item.source_fingerprint,
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                        "quote": item.quote,
                                    }
                                    for item in test.binding_source_refs
                                ]
                                if test
                                else []
                            ),
                            ensure_ascii=False,
                        ),
                        "test_protocol_evidence": json.dumps(
                            list(test.protocol_evidence) if test else [],
                            ensure_ascii=False,
                        ),
                        "outcome": measurement.outcome,
                        "value": (
                            "" if measurement.value is None else str(measurement.value)
                        ),
                        "unit": measurement.unit or "",
                        "result_text": measurement.result_text or "",
                        "statistics": json.dumps(
                            dict(measurement.statistics),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "measurement_scope": json.dumps(
                            dict(measurement.measurement_scope),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "source_refs": json.dumps(
                            [
                                {
                                    "document_id": item.document_id,
                                    "source_fingerprint": item.source_fingerprint,
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                    "quote": item.quote,
                                }
                                for item in measurement.source_refs
                            ],
                            ensure_ascii=False,
                        ),
                        "binding_source_refs": json.dumps(
                            [
                                {
                                    "document_id": item.document_id,
                                    "source_fingerprint": item.source_fingerprint,
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                    "quote": item.quote,
                                }
                                for item in measurement.binding_source_refs
                            ],
                            ensure_ascii=False,
                        ),
                        "binding_status": measurement.binding_status,
                        "result_kind": measurement.result_kind,
                        "notes": json.dumps(
                            list(measurement.notes), ensure_ascii=False
                        ),
                        "comparison_keys": json.dumps(
                            list(comparison_keys), ensure_ascii=False
                        ),
                        "selection_comparison_keys": json.dumps(
                            list(selection.comparison_keys), ensure_ascii=False
                        ),
                    }
                )

        output = io.StringIO(newline="")
        fieldnames = (
            "collection_id",
            "objective_id",
            "analysis_version",
            "selection_id",
            "experiment_id",
            "experiment_version",
            "measurement_key",
            "variant_key",
            "variant_label",
            "variant_subject_attributes",
            "variant_intervention_attributes",
            "variant_state",
            "variant_population_scope",
            "variant_binding_status",
            "variant_source_refs",
            "variant_binding_source_refs",
            "test_key",
            "test_type",
            "test_parameters",
            "test_population_scope",
            "test_method",
            "test_standard",
            "test_outcome_scope",
            "test_protocol_specificity",
            "test_identity_status",
            "test_protocol_completeness",
            "test_missing_parameters",
            "test_binding_status",
            "test_source_refs",
            "test_binding_source_refs",
            "test_protocol_evidence",
            "outcome",
            "value",
            "unit",
            "result_text",
            "statistics",
            "measurement_scope",
            "source_refs",
            "binding_source_refs",
            "binding_status",
            "result_kind",
            "notes",
            "comparison_keys",
            "selection_comparison_keys",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()


__all__ = ["ExperimentAnalysisBundle", "ExperimentQueryService"]


def scientific_attribute_response(value: ScientificAttribute) -> dict[str, Any]:
    return {
        "name": value.name,
        "value": value.value,
        "unit": value.unit,
        **(
            {"context_scope": value.context_scope}
            if value.context_scope != "unknown"
            else {}
        ),
        **(
            {"applies_to_outcomes": list(value.applies_to_outcomes)}
            if value.applies_to_outcomes
            else {}
        ),
    }


def _scientific_context_response(value: ScientificContext) -> dict[str, Any]:
    return {
        "material": [
            scientific_attribute_response(attribute) for attribute in value.material
        ],
        "sample": [
            scientific_attribute_response(attribute) for attribute in value.sample
        ],
        "process": [
            scientific_attribute_response(attribute) for attribute in value.process
        ],
        "test": [scientific_attribute_response(attribute) for attribute in value.test],
    }


def objective_evidence_response(value: ObjectiveEvidence) -> dict[str, Any]:
    return {
        "collection_id": value.collection_id,
        "objective_id": value.objective_id,
        "analysis_version": value.analysis_version,
        "evidence_id": value.evidence_id,
        "document_id": value.document_id,
        "source_kind": value.source_kind,
        "source_ref": value.source_ref,
        "source_excerpt": value.source_excerpt,
        "page_numbers": list(value.page_numbers),
        "evidence_role": value.evidence_role,
        "selection_status": value.selection_status,
        "selection_reason": value.selection_reason,
        "evidence_status": value.evidence_status,
        "evidence_status_reason": value.evidence_status_reason,
        "changed_variables": [
            {
                "name": variable.name,
                "baseline_value": variable.baseline_value,
                "target_value": variable.target_value,
                "unit": variable.unit,
            }
            for variable in value.changed_variables
        ],
        "comparison": (
            {
                "baseline_label": value.comparison.baseline_label,
                "target_label": value.comparison.target_label,
                "axis_names": list(value.comparison.axis_names),
                "comparable": value.comparison.comparable,
                "incomparability_reasons": list(
                    value.comparison.incomparability_reasons
                ),
            }
            if value.comparison
            else None
        ),
        "reported_result": (
            {
                "outcome": value.reported_result.outcome,
                "value": value.reported_result.value,
                "baseline_value": value.reported_result.baseline_value,
                "target_value": value.reported_result.target_value,
                "unit": value.reported_result.unit,
                "direction": value.reported_result.direction,
                "result_text": value.reported_result.result_text,
                "result_kind": value.reported_result.result_kind,
            }
            if value.reported_result
            else None
        ),
        "attribution_scope": value.attribution_scope,
        "scientific_context": _scientific_context_response(value.scientific_context),
        "resolution_status": value.resolution_status,
        "failure_reason": value.failure_reason,
        "confidence": value.confidence,
        "origin": value.origin,
        "source_analysis_version": value.source_analysis_version,
        "supersedes_evidence_id": value.supersedes_evidence_id,
        "superseded_by_evidence_id": value.superseded_by_evidence_id,
        "created_by_user_id": value.created_by_user_id,
        "created_by_tool_call_id": value.created_by_tool_call_id,
        "created_at": (
            value.created_at.isoformat() if value.created_at is not None else None
        ),
        "authoring_note": value.authoring_note,
        **({"warnings": list(value.warnings)} if value.warnings else {}),
        **(
            {"related_source_refs": [dict(item) for item in value.related_source_refs]}
            if value.related_source_refs or value.related_source_refs_explicit
            else {}
        ),
    }

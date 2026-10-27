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
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    ReportedInterpretation,
    SourceReference,
)
from domain.core.research_objective import ObjectiveEvidence, PaperContribution
from domain.core.scientific_fact import ScientificAttribute, ScientificContext
from repositories.comparison_group_repository import ComparisonGroupRepository
from repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from repositories.objective_repository import ObjectiveAnalysis
from repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)
from repositories.pipeline_run_repository import execution_stats_record


@dataclass(frozen=True)
class ExperimentAnalysisBundle:
    """All fixed-version records used by one Objective analysis snapshot."""

    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]
    revisions: tuple[StoredPaperExperimentRevision, ...]

    def to_record(self) -> dict[str, Any]:
        return {
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
                for item in self.selections
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
                for item in self.groups
            ],
            "findings": [finding_response(item) for item in self.findings],
            "experiments": [
                paper_experiment_revision_response(item.revision)
                for item in self.revisions
            ],
        }


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
            **bundle.to_record(),
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
            (item.revision.experiment_id, item.revision.experiment_version): item.revision
            for item in bundle.revisions
        }
        variants_by_identity = {
            (revision.experiment_id, revision.experiment_version, variant.variant_key): variant
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


def _source_reference_response(value: SourceReference) -> dict[str, str]:
    return {
        "document_id": value.document_id,
        "source_fingerprint": value.source_fingerprint,
        "source_kind": value.source_kind,
        "source_ref": value.source_ref,
        "quote": value.quote,
    }


def _experimental_variant_response(value: ExperimentalVariant) -> dict[str, Any]:
    return {
        "variant_key": value.variant_key,
        "variant_label": value.variant_label,
        "subject_attributes": [
            scientific_attribute_response(item) for item in value.subject_attributes
        ],
        "intervention_attributes": [
            scientific_attribute_response(item)
            for item in value.intervention_attributes
        ],
        "state": [scientific_attribute_response(item) for item in value.state],
        "population_scope": (
            dict(value.population_scope) if value.population_scope is not None else None
        ),
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
        "binding_source_refs": [
            _source_reference_response(item) for item in value.binding_source_refs
        ],
        "binding_status": value.binding_status,
        "notes": list(value.notes),
        "identity_specificity": value.identity_specificity,
        "missing_dimensions": list(value.missing_dimensions),
        "identity_evidence": list(value.identity_evidence),
    }


def _experiment_test_condition_response(
    value: ExperimentTestCondition,
) -> dict[str, Any]:
    return {
        "test_key": value.test_key,
        "test_type": value.test_type,
        "parameters": [
            scientific_attribute_response(item) for item in value.parameters
        ],
        "population_scope": (
            dict(value.population_scope) if value.population_scope is not None else None
        ),
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
        "binding_status": value.binding_status,
        "notes": list(value.notes),
        "protocol_specificity": value.protocol_specificity,
        "test_identity_status": value.test_identity_status,
        "protocol_completeness": value.protocol_completeness,
        "missing_parameters": list(value.missing_parameters),
        "method": value.method,
        "standard": value.standard,
        "outcome_scope": list(value.outcome_scope),
        "binding_source_refs": [
            _source_reference_response(item) for item in value.binding_source_refs
        ],
        "protocol_evidence": list(value.protocol_evidence),
    }


def _experiment_measurement_result_response(
    value: ExperimentMeasurementResult,
) -> dict[str, Any]:
    return {
        "measurement_key": value.measurement_key,
        "outcome": value.outcome,
        "variant_key": value.variant_key,
        "test_key": value.test_key,
        "value": value.value,
        "unit": value.unit,
        "result_text": value.result_text,
        "statistics": dict(value.statistics),
        "measurement_scope": dict(value.measurement_scope),
        "result_kind": value.result_kind,
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
        "binding_source_refs": [
            _source_reference_response(item) for item in value.binding_source_refs
        ],
        "binding_status": value.binding_status,
        "notes": list(value.notes),
    }


def _experiment_comparison_response(value: ExperimentComparison) -> dict[str, Any]:
    return {
        "comparison_key": value.comparison_key,
        "baseline_variant_key": value.baseline_variant_key,
        "target_variant_key": value.target_variant_key,
        "outcome": value.outcome,
        "baseline_measurement_keys": list(value.baseline_measurement_keys),
        "target_measurement_keys": list(value.target_measurement_keys),
        "changed_variables": [
            {
                "name": item.name,
                "baseline_value": item.baseline_value,
                "target_value": item.target_value,
                "unit": item.unit,
            }
            for item in value.changed_variables
        ],
        "matched_conditions": [
            scientific_attribute_response(item) for item in value.matched_conditions
        ],
        "basis": value.basis,
        "direction": value.direction,
        "reported_statement": value.reported_statement,
        "attribution_scope": value.attribution_scope,
        "status": value.status,
        "reasons": list(value.reasons),
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
        "binding_source_refs": [
            _source_reference_response(item) for item in value.binding_source_refs
        ],
        "relation_status": value.relation_status,
    }


def _reported_interpretation_response(value: ReportedInterpretation) -> dict[str, Any]:
    return {
        "statement": value.statement,
        "kind": value.kind,
        "measurement_keys": list(value.measurement_keys),
        "comparison_keys": list(value.comparison_keys),
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
    }


def paper_experiment_revision_response(
    value: PaperExperimentRevision,
) -> dict[str, Any]:
    return {
        "experiment_id": value.experiment_id,
        "document_id": value.document_id,
        "experiment_version": value.experiment_version,
        "source_fingerprint": value.source_fingerprint,
        "label": value.label,
        "scope_description": value.scope_description,
        "design_type": value.design_type,
        "identity_status": value.identity_status,
        "binding_status": value.binding_status,
        "variants": [_experimental_variant_response(item) for item in value.variants],
        "test_conditions": [
            _experiment_test_condition_response(item) for item in value.test_conditions
        ],
        "measurements": [
            _experiment_measurement_result_response(item) for item in value.measurements
        ],
        "comparisons": [
            _experiment_comparison_response(item) for item in value.comparisons
        ],
        "reported_interpretations": [
            _reported_interpretation_response(item)
            for item in value.reported_interpretations
        ],
        "source_refs": [_source_reference_response(item) for item in value.source_refs],
        "unresolved_issues": [dict(item) for item in value.unresolved_issues],
    }


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


def finding_response(value: Finding) -> dict[str, Any]:
    return {
        "collection_id": value.collection_id,
        "objective_id": value.objective_id,
        "analysis_version": value.analysis_version,
        "finding_id": value.finding_id,
        "statement": value.statement,
        "factors": list(value.factors),
        "outcome": value.outcome,
        "direction": value.direction,
        "assertion_strength": value.assertion_strength,
        "attribution_scope": value.attribution_scope,
        "synthesis_status": value.synthesis_status,
        "certainty": value.certainty,
        "display_rank": value.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in value.mechanisms
        ],
        "scientific_context": _scientific_context_response(value.scientific_context),
        "limitations": list(value.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in value.paper_contributions
        ],
        "origin": value.origin,
        "source_analysis_version": value.source_analysis_version,
        "parent_finding_id": value.parent_finding_id,
        "created_by_user_id": value.created_by_user_id,
        "created_by_tool_call_id": value.created_by_tool_call_id,
        "created_at": value.created_at.isoformat() if value.created_at else None,
        **({"selection_ids": list(value.selection_ids)} if value.selection_ids else {}),
        **(
            {"comparison_group_ids": list(value.comparison_group_ids)}
            if value.comparison_group_ids
            else {}
        ),
        **({"warnings": list(value.warnings)} if value.warnings else {}),
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


def paper_contribution_response(value: PaperContribution) -> dict[str, Any]:
    return {
        "collection_id": value.collection_id,
        "objective_id": value.objective_id,
        "analysis_version": value.analysis_version,
        "document_id": value.document_id,
        "analysis_status": value.analysis_status,
        "relevance": value.relevance,
        "paper_role": value.paper_role,
        "contribution_summary": value.contribution_summary,
        "material_match": list(value.material_match),
        "changed_variables": list(value.changed_variables),
        "measured_property_scope": list(value.measured_property_scope),
        "test_environment_scope": list(value.test_environment_scope),
        "exclusion_reason": value.exclusion_reason,
        "warnings": list(value.warnings),
        "confidence": value.confidence,
        "evidence_disposition": value.evidence_disposition,
        "routed_source_count": value.routed_source_count,
        "extracted_source_count": value.extracted_source_count,
        "comparable_evidence_count": value.comparable_evidence_count,
        "failed_source_count": value.failed_source_count,
        "uninspected_source_count": value.uninspected_source_count,
        "evidence_disposition_reason": value.evidence_disposition_reason,
        "evidence_status_counts": {
            status: count for status, count in value.evidence_status_counts
        },
        "inspected_source_refs": [
            {
                "source_kind": source_ref.source_kind,
                "source_ref": source_ref.source_ref,
                "source_digest": source_ref.source_digest,
            }
            for source_ref in value.inspected_source_refs
        ],
    }


def objective_analysis_response(value: ObjectiveAnalysis) -> dict[str, Any]:
    return {
        "collection_id": value.collection_id,
        "objective_id": value.objective_id,
        "analysis_version": value.analysis_version,
        "document_inputs": [
            {
                "document_id": document_input.document_id,
                "preparation_fingerprint": document_input.preparation_fingerprint,
            }
            for document_input in value.document_inputs
        ],
        "pipeline_version": value.pipeline_version,
        "model_name": value.model_name,
        "prompt_versions": dict(value.prompt_versions),
        "stats": execution_stats_record(value.stats),
        "status": value.status,
        "phase": value.phase,
        "processed_document_count": value.processed_document_count,
        "total_document_count": value.total_document_count,
        "current_document_id": value.current_document_id,
        "progress_message": value.progress_message,
        "error_code": value.error_code,
        "error_message": value.error_message,
        "created_at": (
            value.created_at.isoformat() if value.created_at is not None else None
        ),
        "started_at": (
            value.started_at.isoformat() if value.started_at is not None else None
        ),
        "completed_at": (
            value.completed_at.isoformat() if value.completed_at is not None else None
        ),
        "origin": value.origin,
        "scientific_record_source": value.scientific_record_source,
        "source_analysis_version": value.source_analysis_version,
        "created_by_user_id": value.created_by_user_id,
        "created_by_tool_call_id": value.created_by_tool_call_id,
        "abstention_reason": value.abstention_reason,
        "abstention_note": value.abstention_note,
    }

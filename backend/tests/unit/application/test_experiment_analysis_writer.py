from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
    stable_draft_experiment_id,
)
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentModelOutput,
    ReconciledPaperExperimentOutput,
    reconcile_model_output,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from application.repositories.experiment_analysis_repository import (
    ExperimentAnalysisWrite,
    StoredExperimentAnalysis,
)
from application.repositories.objective_repository import ObjectiveAnalysis
from application.repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)
from domain.core.research_objective import (
    ObjectiveFactSet,
    PaperContribution,
    ResearchObjective,
)
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _objective(
    *, variables: tuple[str, ...] = ("preheat",)
) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "Does preheat change elongation?",
            "material_scope": ["316L"],
            "variables": list(variables),
            "outcomes": ["elongation"],
            "confirmation_status": "confirmed",
        }
    )


def _analysis(version: int = 1) -> ObjectiveAnalysis:
    return ObjectiveAnalysis.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": version,
            "document_inputs": [
                {
                    "document_id": "paper-a",
                    "preparation_fingerprint": "prepared-a",
                },
                {
                    "document_id": "paper-b",
                    "preparation_fingerprint": "prepared-b",
                },
            ],
            "pipeline_version": "test",
            "status": "succeeded",
            "processed_document_count": 2,
            "total_document_count": 2,
        }
    )


def _draft_output(
    document_id: str,
    *,
    include_speed: bool = False,
    source_fingerprint: str | None = None,
    test_method: str = "uniaxial tensile test",
    test_standard: str = "ASTM E8/E8M",
) -> ReconciledPaperExperimentOutput:
    """Build a service-owned Draft handoff without formal database identity."""

    fingerprint = source_fingerprint or f"prepared-{document_id}"
    variants = [
        {
            "variant_key": "np",
            "variant_label": "NP",
            "identity_specificity": "exact",
            "subject_attributes": [{"name": "material", "value": "316L"}],
            "intervention_attributes": [{"name": "preheat", "value": 0, "unit": "C"}],
            "source_labels": ["methods"],
            "binding_source_labels": ["methods"],
        },
        {
            "variant_key": "p150",
            "variant_label": "P150",
            "identity_specificity": "exact",
            "subject_attributes": [{"name": "material", "value": "316L"}],
            "intervention_attributes":[{"name": "preheat", "value": 150, "unit": "C"}],
            "source_labels": ["methods"],
            "binding_source_labels": ["methods"],
        },
    ]
    measurements = [
        {
            "measurement_key": "np-elongation",
            "variant_key": "np",
            "test_key": "tensile",
            "outcome": "elongation",
            "value": 72,
            "unit": "%",
            "source_labels": ["table"],
            "variant_binding_source_labels": ["table"],
            "test_binding_source_labels": ["methods"],
        },
        {
            "measurement_key": "p150-elongation",
            "variant_key": "p150",
            "test_key": "tensile",
            "outcome": "elongation",
            "value": 82,
            "unit": "%",
            "source_labels": ["table"],
            "variant_binding_source_labels": ["table"],
            "test_binding_source_labels": ["methods"],
        },
    ]
    comparisons = [
        {
            "comparison_key": "preheat-comparison",
            "baseline_variant_key": "np",
            "target_variant_key": "p150",
            "outcome": "elongation",
            "baseline_measurement_keys": ["np-elongation"],
            "target_measurement_keys": ["p150-elongation"],
            "changed_variables": [
                {"name": "preheat", "baseline_value": 0, "target_value": 150, "unit": "C"}
            ],
            "source_labels": ["table"],
            "binding_source_labels": ["table"],
        }
    ]
    if include_speed:
        variants.extend(
            [
                {
                    "variant_key": "s800",
                    "variant_label": "S800",
                    "identity_specificity": "exact",
                    "subject_attributes": [{"name": "material", "value": "316L"}],
                    "intervention_attributes": [{"name": "scan speed", "value": 800, "unit": "mm/s"}],
                    "source_labels": ["methods"],
                    "binding_source_labels": ["methods"],
                },
                {
                    "variant_key": "s1000",
                    "variant_label": "S1000",
                    "identity_specificity": "exact",
                    "subject_attributes": [{"name": "material", "value": "316L"}],
                    "intervention_attributes": [{"name": "scan speed", "value": 1000, "unit": "mm/s"}],
                    "source_labels": ["methods"],
                    "binding_source_labels": ["methods"],
                },
            ]
        )
        measurements.extend(
            [
                {
                    "measurement_key": "s800-elongation",
                    "variant_key": "s800",
                    "test_key": "tensile",
                    "outcome": "elongation",
                    "value": 20,
                    "unit": "%",
                    "source_labels": ["table"],
                    "variant_binding_source_labels": ["table"],
                    "test_binding_source_labels": ["methods"],
                },
                {
                    "measurement_key": "s1000-elongation",
                    "variant_key": "s1000",
                    "test_key": "tensile",
                    "outcome": "elongation",
                    "value": 18,
                    "unit": "%",
                    "source_labels": ["table"],
                    "variant_binding_source_labels": ["table"],
                    "test_binding_source_labels": ["methods"],
                },
            ]
        )
        comparisons.append(
            {
                "comparison_key": "speed-comparison",
                "baseline_variant_key": "s800",
                "target_variant_key": "s1000",
                "outcome": "elongation",
                "baseline_measurement_keys": ["s800-elongation"],
                "target_measurement_keys": ["s1000-elongation"],
                "changed_variables": [
                    {"name": "scan speed", "baseline_value": 800, "target_value": 1000, "unit": "mm/s"}
                ],
                "source_labels": ["table"],
                "binding_source_labels": ["table"],
            }
        )
    payload = {
        "document_id": document_id,
        "source_fingerprint": fingerprint,
        "source_labels": {
            "methods": {
                "document_id": document_id,
                "source_fingerprint": fingerprint,
                "source_kind": "section",
                "source_ref": f"{document_id}-methods",
                "quote": "All variants use the same tensile protocol.",
            },
            "table": {
                "document_id": document_id,
                "source_fingerprint": fingerprint,
                "source_kind": "table",
                "source_ref": f"{document_id}-table",
                "quote": "NP 72%; P150 82%.",
            },
        },
        "experiments": [
            {
                "series_key": "series-1",
                "label": "Preheat tensile series",
                "scope_description": "Variants compared under one tensile protocol.",
                "design_type": "parallel",
                "scope_kind": "parent",
                "experimental_variants": variants,
                "test_conditions": [
                    {
                        "test_key": "tensile",
                        "test_type": "tensile test",
                        "method": test_method,
                        "standard": test_standard,
                        "protocol_specificity": "exact",
                        "test_identity_status": "identified",
                        "protocol_completeness": "complete",
                        "outcome_scope": ["elongation"],
                        "source_labels": ["methods"],
                        "binding_source_labels": ["methods"],
                    }
                ],
                "measurements": measurements,
                "comparisons": comparisons,
                "source_labels": ["methods", "table"],
            }
        ],
    }
    output = PaperExperimentModelOutput.from_mapping(payload)
    return reconcile_model_output(output, accepted_experiment_keys=("series-1",))


def _comparison_experiment(document_id: str):
    return _draft_output(document_id)


def _partial_archive_without_variants(
    document_id: str,
) -> ReconciledPaperExperimentOutput:
    """A source-grounded report whose physical experiment boundary is unknown."""

    fingerprint = f"prepared-{document_id}"
    payload = {
        "document_id": document_id,
        "source_fingerprint": fingerprint,
        "source_labels": {
            "table": {
                "document_id": document_id,
                "source_fingerprint": fingerprint,
                "source_kind": "table",
                "source_ref": f"{document_id}-table",
                "quote": "The paper reports an elongation value, but the sample row is not identified.",
            }
        },
        "experiments": [
            {
                "series_key": "unresolved-series",
                "label": "Unresolved reported result",
                "scope_description": "A reported result retained pending boundary reconciliation.",
                "design_type": "unknown",
                "scope_kind": "unknown",
                "experimental_variants": [],
                "test_conditions": [],
                "measurements": [
                    {
                        "measurement_key": "reported-elongation",
                        "outcome": "elongation",
                        "value": 72,
                        "unit": "%",
                        "result_text": "72%",
                        "source_labels": ["table"],
                    }
                ],
                "comparisons": [],
                "source_labels": ["table"],
                "unresolved_issues": [
                    {
                        "target_ref": "measurements/reported-elongation",
                        "description": "The sample and test bindings are not identified.",
                    }
                ],
            }
        ],
    }
    output = PaperExperimentModelOutput.from_mapping(payload)
    return reconcile_model_output(
        output,
        accepted_experiment_keys=("unresolved-series",),
    )


def test_formal_identity_remains_strict_without_physical_variants():
    with pytest.raises(
        ValueError, match="without physical variants"
    ):
        stable_draft_experiment_id(
            document_id="paper-a",
            payload={"scope_kind": "parent", "experimental_variants": []},
        )


def _multi_factor_comparison_experiment(document_id: str):
    return _draft_output(document_id, include_speed=True)


def _mixed_valid_invalid_comparison_experiment(document_id: str):
    """Keep one comparable slice while forcing a second slice out of context."""

    base = _multi_factor_comparison_experiment(document_id)
    draft = base.output.experiments[0]
    measurements = [dict(item) for item in draft.payload["measurements"]]
    for measurement in measurements:
        if measurement["measurement_key"] == "s1000-elongation":
            # A unit mismatch is a source-level fact we can preserve, but it
            # cannot be finalized as a comparison with the percent baseline.
            measurement["unit"] = "MPa"
    experiment_payload = {
        **draft.payload,
        "measurements": measurements,
        "source_labels": list(draft.source_labels),
        "unresolved_issues": list(draft.unresolved_issues),
    }
    output = PaperExperimentModelOutput.from_mapping(
        {
            "document_id": base.output.document_id,
            "source_fingerprint": base.output.source_fingerprint,
            "source_labels": base.output.source_labels,
            "experiments": [experiment_payload],
            "unresolved_issues": list(base.output.unresolved_issues),
        }
    )
    return reconcile_model_output(
        output,
        accepted_experiment_keys=base.accepted_experiment_keys,
    )


def _physical_split_experiment(
    document_id: str,
    *,
    distinct_boundary: bool = True,
) -> ReconciledPaperExperimentOutput:
    """Build retained physical splits with identical variant/test content."""

    base = _draft_output(document_id)
    first = deepcopy(base.output.experiments[0].payload)
    first.update(
        {
            "series_key": "split-a",
            "scope_kind": "physical_split",
            "split_reason": "different population assignment",
            "split_evidence": [{"source_label": "methods"}],
        }
    )
    second = deepcopy(first)
    second["series_key"] = "split-b"
    if distinct_boundary:
        second["split_reason"] = "different population and intervention assignment"
        second["split_evidence"] = [{"source_label": "table"}]
    payload = {
        "document_id": base.output.document_id,
        "source_fingerprint": base.output.source_fingerprint,
        "source_labels": base.output.source_labels,
        "experiments": [first, second],
    }
    return reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("split-a", "split-b"),
    )


class _RevisionRepository:
    def __init__(self):
        self.records: dict[tuple[str, int], StoredPaperExperimentRevision] = {}
        self.next_id = 1
        self.transaction_handles: list[object | None] = []
        self.latest_revision_calls: list[str] = []
        self.document_lock_calls: list[str] = []

    async def lock_document(self, document_id, *, transaction=None):
        self.document_lock_calls.append(document_id)
        self.transaction_handles.append(transaction)

    async def read_latest_revision(self, experiment_id, *, transaction=None):
        self.latest_revision_calls.append(experiment_id)
        self.transaction_handles.append(transaction)
        values = [
            record
            for (identity, _), record in self.records.items()
            if identity == experiment_id
        ]
        return max(values, key=lambda item: item.revision.experiment_version) if values else None

    async def list_latest_for_document(self, document_id, *, transaction=None):
        self.transaction_handles.append(transaction)
        latest_by_identity: dict[str, StoredPaperExperimentRevision] = {}
        for record in self.records.values():
            if record.revision.document_id != document_id:
                continue
            previous = latest_by_identity.get(record.revision.experiment_id)
            if (
                previous is None
                or record.revision.experiment_version
                > previous.revision.experiment_version
            ):
                latest_by_identity[record.revision.experiment_id] = record
        return tuple(latest_by_identity.values())

    async def add_revision(
        self, revision, *, created_by=None, created_at=None, transaction=None
    ):
        self.transaction_handles.append(transaction)
        key = (revision.experiment_id, revision.experiment_version)
        existing = self.records.get(key)
        if existing is not None:
            if existing.revision == revision:
                return existing
            raise ValueError("immutable revision conflict")
        stored = StoredPaperExperimentRevision(
            revision_id=self.next_id,
            revision=revision,
            created_at=created_at or datetime.now(timezone.utc),
            created_by=created_by,
        )
        self.next_id += 1
        self.records[key] = stored
        return stored


class _AnalysisRepository:
    def __init__(self, revisions: _RevisionRepository) -> None:
        self.revisions = revisions
        self.graphs: list[ExperimentAnalysisWrite] = []
        self.transaction_handles: list[object | None] = []

    async def write_graph(self, graph, *, transaction=None):
        self.graphs.append(graph)
        self.transaction_handles.append(transaction)
        stored_revisions = tuple(
            [
                await self.revisions.add_revision(
                    revision,
                    created_by=graph.created_by,
                    transaction=transaction,
                )
                for revision in graph.revisions
            ]
        )
        return StoredExperimentAnalysis(
            revisions=stored_revisions,
            selections=graph.selections,
            groups=graph.groups,
            findings=graph.findings,
        )


def _writer():
    revisions = _RevisionRepository()
    analyses = _AnalysisRepository(revisions)
    writer = ExperimentAnalysisWriter(
        paper_experiment_repository=revisions,
        experiment_analysis_repository=analyses,
    )
    return writer, revisions, analyses


async def test_writer_creates_revision_selection_and_finding_idempotently():
    writer, revisions, analyses = _writer()
    experiment = _comparison_experiment("paper-a")

    first = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(experiment,),
    )
    second = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(experiment,),
    )

    assert len(first.revisions) == len(second.revisions) == 1
    assert first.revisions[0].revision.experiment_version == 1
    assert len(revisions.records) == 1
    assert len(first.selections) == 1
    assert first.groups == ()
    assert len(first.findings) == 1
    assert first.findings == second.findings
    assert first.findings[0].paper_contributions == ()
    assert len(analyses.graphs) == 2


async def test_authored_selection_revision_preserves_parent_limits_and_provenance():
    writer, _, _ = _writer()
    original = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_comparison_experiment("paper-a"),),
    )
    revision = await writer.write_selection_finding_revision(
        collection_id="collection-1",
        objective=_objective(),
        analysis=replace(
            _analysis(2),
            origin="human_authored",
            source_analysis_version=1,
            created_by_user_id="researcher-1",
        ),
        revisions=original.revisions,
        selections=original.selections,
        created_by="researcher-1",
        parent_finding_id=original.findings[0].finding_id,
        limitations=("Only the tested preheat conditions are supported.",),
    )
    (finding,) = revision.findings
    assert finding.parent_finding_id == original.findings[0].finding_id
    assert finding.origin == "hybrid"
    assert finding.source_analysis_version == 1
    assert finding.created_by_user_id == "researcher-1"
    assert finding.created_at.tzinfo is not None
    assert "Only the tested preheat conditions are supported." in finding.limitations
    assert revision.selections[0].analysis_version == 2
    assert original.selections[0].analysis_version == 1
    assert original.findings[0].parent_finding_id is None


async def test_abstention_revision_writes_no_placeholder_finding():
    writer, _, analyses = _writer()
    result = await writer.write_selection_finding_revision(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(2),
        revisions=(),
        selections=(),
        created_by="researcher-1",
        limitations=("No comparable measurement was found.",),
    )
    assert result.findings == ()
    assert result.selections == ()
    assert result.groups == ()
    assert len(analyses.graphs) == 1


async def test_researcher_revises_limits_then_abstains_without_changing_source(
    collection_service,
):
    collection = await collection_service.create_collection(
        "316L preheat and elongation",
        owner_user_id="researcher-1",
    )
    collection_id = collection["collection_id"]
    objective = replace(_objective(), collection_id=collection_id)
    repository = MemoryObjectiveRepository()
    await repository.replace(
        collection_id,
        ObjectiveFactSet(research_objectives=(objective,)),
    )
    await repository.queue_analysis(
        collection_id,
        objective.objective_id,
        document_inputs=_analysis().document_inputs,
        pipeline_version="test",
        model_name=None,
        prompt_versions={},
    )
    analysis = await repository.claim_analysis(collection_id, objective.objective_id, 1)
    writer, _, graphs = _writer()
    source = await writer.write_experiment_analysis(
        collection_id=collection_id,
        objective=objective,
        analysis=analysis,
        experiment_outputs=(_comparison_experiment("paper-a"),),
    )
    coverage = tuple(
        PaperContribution.from_mapping(
            {
                "collection_id": collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": 1,
                "document_id": paper,
                "analysis_status": "analyzed" if paper == "paper-a" else "excluded",
                "warnings": (
                    []
                    if paper == "paper-a"
                    else ["No comparable elongation measurement."]
                ),
            }
        )
        for paper in ("paper-a", "paper-b")
    )
    await repository.publish_experiment_analysis(
        collection_id,
        objective.objective_id,
        1,
        contributions=coverage,
    )
    query = SimpleNamespace(read_analysis_bundle=AsyncMock(return_value=source))

    @asynccontextmanager
    async def transaction():
        yield None

    service = FindingAuthoringService(
        collection_service=collection_service,
        objective_repository=repository,
        experiment_query_service=query,
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=SimpleNamespace(begin=transaction),
    )
    revised = await service.create_selection_version(
        collection_id=collection_id,
        objective_id=objective.objective_id,
        source_analysis_version=1,
        selection_ids=tuple(item.selection_id for item in source.selections),
        parent_finding_id=source.findings[0].finding_id,
        limitations=(" Supported only within the tested preheat conditions. ",),
        created_by_user_id="researcher-1",
    )
    assert revised.analysis.status == "succeeded"
    assert revised.finding.parent_finding_id == source.findings[0].finding_id
    assert (
        "Supported only within the tested preheat conditions."
        in revised.finding.limitations
    )
    query.read_analysis_bundle.return_value = SimpleNamespace(
        revisions=source.revisions,
        selections=graphs.graphs[-1].selections,
        groups=graphs.graphs[-1].groups,
        findings=graphs.graphs[-1].findings,
    )
    abstained = await service.create_selection_version(
        collection_id=collection_id,
        objective_id=objective.objective_id,
        source_analysis_version=2,
        selection_ids=(),
        created_by_user_id="researcher-1",
        abstention_reason="no_comparable_evidence",
        limitations=("The second paper lacks a comparable elongation measurement.",),
    )
    assert abstained.analysis.analysis_version == 3
    assert abstained.analysis.abstention_reason == "no_comparable_evidence"
    assert abstained.finding is None
    assert graphs.graphs[-1].findings == ()
    assert await repository.list_contributions(
        collection_id, objective.objective_id, 3
    ) == tuple(replace(item, analysis_version=3) for item in coverage)
    assert (
        await repository.read_analysis(collection_id, objective.objective_id, 1)
    ).status == "succeeded"
    assert source.findings[0].parent_finding_id is None


async def test_writer_keeps_selection_for_exact_partial_protocol() -> None:
    """A concrete protocol may remain partial without blocking this slice."""

    writer, _, _ = _writer()
    base = _draft_output("paper-a")
    payload = deepcopy(base.output.experiments[0].payload)
    payload["test_conditions"][0].update(
        {
            "protocol_completeness": "partial",
            "missing_parameters": ["fixture alignment"],
        }
    )
    experiment = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(
            {
                "document_id": base.output.document_id,
                "source_fingerprint": base.output.source_fingerprint,
                "source_labels": base.output.source_labels,
                "experiments": [payload],
            }
        ),
        accepted_experiment_keys=("series-1",),
    )

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(experiment,),
    )

    assert len(result.revisions) == 1
    assert len(result.selections) == 1
    assert len(result.findings) == 1
    test_condition = result.revisions[0].revision.test_conditions[0]
    assert test_condition.protocol_completeness == "partial"
    assert test_condition.missing_parameters == ("fixture alignment",)


async def test_single_experiment_writer_commits_revision_and_selection_only():
    writer, revisions, analyses = _writer()
    result = await writer.write_single_experiment_revision(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_output=_comparison_experiment("paper-a"),
        create_selection=True,
        created_by="agent-user",
    )

    assert len(result.revisions) == 1
    assert len(result.selections) == 1
    assert result.groups == ()
    assert result.findings == ()
    assert len(revisions.records) == 1
    assert analyses.graphs[0].findings == ()


async def test_writer_passes_one_transaction_to_every_graph_repository():
    writer, revisions, analyses = _writer()
    transaction = object()

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_comparison_experiment("paper-a"),),
        transaction=transaction,
    )

    handles = revisions.transaction_handles + analyses.transaction_handles
    assert handles
    assert all(handle is transaction for handle in handles)


async def test_writer_acquires_multi_draft_identities_in_deterministic_order():
    writer, revisions, _ = _writer()
    drafts = [_draft_output("paper-a"), _draft_output("paper-b")]
    identities = [
        stable_draft_experiment_id(
            document_id=item.output.document_id,
            payload=item.output.experiments[0].payload,
        )
        for item in drafts
    ]
    ordered_inputs = tuple(
        item
        for _, item in sorted(
            zip(identities, drafts, strict=True),
            key=lambda pair: pair[0],
            reverse=True,
        )
    )

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=ordered_inputs,
        allow_finding=False,
        transaction=object(),
    )

    assert revisions.document_lock_calls == sorted(revisions.document_lock_calls)
    assert revisions.latest_revision_calls == sorted(identities)
    assert [item.revision.document_id for item in result.revisions] == [
        item.output.document_id for item in ordered_inputs
    ]


async def test_writer_synthesizes_and_publishes_from_fixed_experiment_records():
    writer, _, analyses = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_comparison_experiment("paper-a"),),
    )

    assert result.groups == ()
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.selection_ids == (result.selections[0].selection_id,)
    assert finding.factors == ("preheat",)
    assert finding.direction == "increase"
    assert finding.synthesis_status == "single_study"
    assert finding.paper_contributions == ()
    assert analyses.graphs[0].findings == (finding,)


async def test_writer_keeps_different_factor_sets_in_separate_selections():
    writer, _, _ = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(variables=("preheat", "scan speed")),
        analysis=_analysis(),
        experiment_outputs=(_multi_factor_comparison_experiment("paper-a"),),
    )

    revision = result.revisions[0].revision
    comparisons = {item.comparison_key: item for item in revision.comparisons}
    selected_factor_sets = {
        tuple(
            variable.name
            for comparison_key in selection.comparison_keys
            for variable in comparisons[comparison_key].changed_variables
        )
        for selection in result.selections
    }
    assert selected_factor_sets == {("preheat",), ("scan speed",)}
    assert all(len(item.comparison_keys) == 1 for item in result.selections)


async def test_writer_keeps_valid_selection_when_another_comparison_is_partial():
    writer, _, _ = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(variables=("preheat", "scan speed")),
        analysis=_analysis(),
        experiment_outputs=(_mixed_valid_invalid_comparison_experiment("paper-a"),),
    )

    revision = result.revisions[0].revision
    comparisons = {item.comparison_key: item for item in revision.comparisons}
    assert comparisons["preheat-comparison"].status == "ready"
    assert comparisons["preheat-comparison"].relation_status == "direct"
    assert comparisons["speed-comparison"].status == "insufficient_context"
    assert comparisons["speed-comparison"].direction == "unknown"
    assert comparisons["speed-comparison"].relation_status == "uncertain"
    assert len(result.selections) == 1
    assert result.selections[0].comparison_keys == ("preheat-comparison",)
    assert len(result.findings) == 1
    assert any(
        "speed-comparison" in message
        for message in result.post_bind_diagnostics["paper-a"]
    )


async def test_writer_creates_conditional_group_for_cross_paper_finding():
    writer, _, analyses = _writer()
    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(
            _comparison_experiment("paper-a"),
            _comparison_experiment("paper-b"),
        ),
    )

    assert len(result.selections) == 2
    assert len(result.groups) == 1
    assert result.groups[0].status == "comparable"
    assert len(result.groups[0].members) == 2
    assert result.findings[0].comparison_group_ids == (result.groups[0].group_id,)
    assert analyses.graphs[0].groups == result.groups


async def test_changed_source_fingerprint_creates_successor_without_overwrite():
    writer, revisions, _ = _writer()
    experiment = _draft_output("paper-a", source_fingerprint="prepared-v1")

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(experiment,),
    )
    revised_experiment = _draft_output("paper-a", source_fingerprint="prepared-v2")
    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(revised_experiment,),
    )

    versions = sorted(
        revision.revision.experiment_version
        for revision in revisions.records.values()
    )
    assert versions == [1, 2]
    assert sorted(
        revision.revision.source_fingerprint
        for revision in revisions.records.values()
    ) == ["prepared-v1", "prepared-v2"]


async def test_parent_identity_stays_stable_when_test_protocol_changes():
    writer, revisions, _ = _writer()

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_draft_output("paper-a"),),
    )
    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(
            _draft_output(
                "paper-a",
                test_method="strain-controlled tensile test",
                test_standard="ISO 6892-1",
            ),
        ),
    )

    stored = tuple(revisions.records.values())
    assert len(stored) == 2
    assert len({item.revision.experiment_id for item in stored}) == 1
    assert sorted(item.revision.experiment_version for item in stored) == [1, 2]


async def test_parent_identity_is_reused_when_reread_adds_variant_context():
    writer, revisions, _ = _writer()

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_draft_output("paper-a", source_fingerprint="prepared-v1"),),
    )

    reread = _draft_output("paper-a", source_fingerprint="prepared-v2")
    reread_payload = deepcopy(reread.output.experiments[0].payload)
    reread_payload["experimental_variants"][0]["state"] = [
        {"name": "build orientation", "value": "vertical"}
    ]
    reread = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(
            {
                "document_id": "paper-a",
                "source_fingerprint": "prepared-v2",
                "source_labels": reread.output.source_labels,
                "experiments": [reread_payload],
            }
        ),
        accepted_experiment_keys=("series-1",),
    )

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(reread,),
    )

    stored = tuple(revisions.records.values())
    assert len(stored) == 2
    assert len({item.revision.experiment_id for item in stored}) == 1
    assert sorted(item.revision.experiment_version for item in stored) == [1, 2]
    assert result.revisions[0].revision.experiment_id == stored[0].revision.experiment_id


async def test_parent_identity_is_reused_for_objective_variant_subset():
    writer, revisions, _ = _writer()

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_draft_output("paper-a"),),
    )

    subset = _draft_output("paper-a")
    subset_payload = deepcopy(subset.output.experiments[0].payload)
    subset_payload["experimental_variants"] = [
        item
        for item in subset_payload["experimental_variants"]
        if item["variant_key"] == "p150"
    ]
    subset_payload["measurements"] = [
        item
        for item in subset_payload["measurements"]
        if item["variant_key"] == "p150"
    ]
    subset_payload["comparisons"] = []
    subset = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(
            {
                "document_id": "paper-a",
                "source_fingerprint": "prepared-paper-a-subset",
                "source_labels": {
                    **subset.output.source_labels,
                    "table": {
                        **subset.output.source_labels["table"],
                        "source_fingerprint": "prepared-paper-a-subset",
                    },
                    "methods": {
                        **subset.output.source_labels["methods"],
                        "source_fingerprint": "prepared-paper-a-subset",
                    },
                },
                "experiments": [subset_payload],
            }
        ),
        accepted_experiment_keys=("series-1",),
    )

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(subset,),
        allow_finding=False,
    )

    stored = tuple(revisions.records.values())
    assert len(stored) == 2
    assert len({item.revision.experiment_id for item in stored}) == 1
    assert sorted(item.revision.experiment_version for item in stored) == [1, 2]


async def test_physical_split_identity_uses_source_backed_boundary_discriminator():
    writer, revisions, _ = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(_physical_split_experiment("paper-a"),),
    )

    assert len(result.revisions) == 2
    assert len({item.revision.experiment_id for item in result.revisions}) == 2
    assert sorted(item.revision.experiment_version for item in revisions.records.values()) == [1, 1]


def test_physical_split_identity_ignores_response_local_source_labels():
    first = _physical_split_experiment("paper-a").output.experiments[0].payload
    second = deepcopy(first)
    second["split_evidence"] = [{"source_label": "S999"}]

    assert stable_draft_experiment_id(document_id="paper-a", payload=first) == stable_draft_experiment_id(
        document_id="paper-a", payload=second
    )


async def test_identical_physical_split_identity_requires_manual_reconciliation():
    writer, _, _ = _writer()

    with pytest.raises(ValueError, match="experiment identity collision"):
        await writer.write_experiment_analysis(
            collection_id="collection-1",
            objective=_objective(),
            analysis=_analysis(),
            experiment_outputs=(
                _physical_split_experiment("paper-a", distinct_boundary=False),
            ),
        )


async def test_writer_does_not_fabricate_finding_without_matching_experiment():
    writer, _, analyses = _writer()
    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(),
    )

    assert result.revisions == ()
    assert result.selections == ()
    assert result.groups == ()
    assert result.findings == ()
    assert analyses.graphs[0].findings == ()


async def test_partial_archive_without_variants_is_retained_without_selection_or_finding():
    writer, revisions, analyses = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(),
        partial_experiment_outputs=(_partial_archive_without_variants("paper-a"),),
    )

    assert len(result.revisions) == 1
    revision = result.revisions[0].revision
    assert revision.experiment_id.startswith("pexp_partial_")
    assert revision.identity_status == "unknown"
    assert revision.binding_status == "partial"
    assert revision.variants == ()
    assert len(revision.measurements) == 1
    assert result.selections == ()
    assert result.groups == ()
    assert result.findings == ()

    # The archive identity is deterministic, so a retry reuses the same
    # immutable revision instead of creating a duplicate partial record.
    second = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiment_outputs=(),
        partial_experiment_outputs=(_partial_archive_without_variants("paper-a"),),
    )
    assert second.revisions[0].revision_id == result.revisions[0].revision_id
    assert len(revisions.records) == 1
    assert analyses.graphs[-1].findings == ()

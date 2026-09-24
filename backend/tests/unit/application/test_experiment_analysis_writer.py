from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
)
from application.repositories.experiment_analysis_repository import (
    ExperimentAnalysisWrite,
    StoredExperimentAnalysis,
)
from application.repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)
from domain.core.research_objective import ObjectiveAnalysis, ResearchObjective
from domain.core.research_process import SourceObservation
from application.core.objectives.analysis.paper_experiment import (
    assemble_paper_experiment,
)


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


def _observation(
    observation_id: str,
    document_id: str,
    value: float,
    label: str,
    *,
    derived_from: tuple[str, ...] = (),
    comparison: dict | None = None,
    changed_variables: tuple[dict, ...] = (),
    direction: str = "increase",
    attribution_scope: str = "association_only",
) -> SourceObservation:
    return SourceObservation.from_mapping(
        {
            "observation_id": observation_id,
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "document_id": document_id,
            "source_kind": "table",
            "source_ref": f"{document_id}-table",
            "observation_role": "direct_result",
            "source_excerpt": f"{label}: elongation {value}%",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": f"{document_id}-table",
                    "source_excerpt": f"{label}: elongation {value}%",
                }
            ],
            "confidence": 0.9,
            "status": "validated",
            "changed_variables": list(changed_variables),
            "comparison": comparison,
            "derived_from_observation_ids": list(derived_from),
            "attribution_scope": attribution_scope,
            "scientific_context": {
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "group", "value": label}],
                "process": [{"name": "preheat", "value": label}],
                "test": [{"name": "method", "value": "tensile"}],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": value,
                "unit": "%",
                "direction": direction,
                "result_text": f"{label}: elongation {value}%",
            },
        }
    )


def _comparison_experiment(document_id: str):
    baseline_id = f"{document_id}-np"
    target_id = f"{document_id}-p150"
    baseline = _observation(baseline_id, document_id, 72, "NP", direction="unknown")
    target = _observation(target_id, document_id, 82, "P150", direction="unknown")
    comparison = _observation(
        f"{document_id}-comparison",
        document_id,
        82,
        "P150",
        derived_from=(baseline_id, target_id),
        comparison={
            "baseline_label": "NP",
            "target_label": "P150",
            "axis_names": ["preheat"],
            "comparable": True,
        },
        changed_variables=(
            {
                "name": "preheat",
                "baseline_value": 0,
                "target_value": 150,
                "unit": "C",
            },
        ),
        direction="increase",
        attribution_scope="isolated_effect",
    )
    return assemble_paper_experiment(
        collection_id="collection-1",
        document_id=document_id,
        source_facts=(baseline, target, comparison),
    )


def _multi_factor_comparison_experiment(document_id: str):
    preheat = _comparison_experiment(document_id)
    speed_baseline_id = f"{document_id}-s800"
    speed_target_id = f"{document_id}-s1000"
    speed_baseline = _observation(
        speed_baseline_id,
        document_id,
        20,
        "S800",
        direction="unknown",
    )
    speed_target = _observation(
        speed_target_id,
        document_id,
        18,
        "S1000",
        direction="unknown",
    )
    speed_comparison = _observation(
        f"{document_id}-speed-comparison",
        document_id,
        18,
        "S1000",
        derived_from=(speed_baseline_id, speed_target_id),
        comparison={
            "baseline_label": "S800",
            "target_label": "S1000",
            "axis_names": ["scan speed"],
            "comparable": True,
        },
        changed_variables=(
            {
                "name": "scan speed",
                "baseline_value": 800,
                "target_value": 1000,
                "unit": "mm/s",
            },
        ),
        direction="decrease",
        attribution_scope="isolated_effect",
    )
    return assemble_paper_experiment(
        collection_id="collection-1",
        document_id=document_id,
        source_facts=(
            *preheat.source_observations,
            speed_baseline,
            speed_target,
            speed_comparison,
        ),
    )


class _RevisionRepository:
    def __init__(self):
        self.records: dict[tuple[str, int], StoredPaperExperimentRevision] = {}
        self.next_id = 1
        self.transaction_handles: list[object | None] = []

    async def read_latest_revision(self, experiment_id, *, transaction=None):
        self.transaction_handles.append(transaction)
        values = [
            record
            for (identity, _), record in self.records.items()
            if identity == experiment_id
        ]
        return max(values, key=lambda item: item.revision.experiment_version) if values else None

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
        experiments=(experiment,),
    )
    second = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
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


async def test_writer_passes_one_transaction_to_every_graph_repository():
    writer, revisions, analyses = _writer()
    transaction = object()

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(_comparison_experiment("paper-a"),),
        transaction=transaction,
    )

    handles = revisions.transaction_handles + analyses.transaction_handles
    assert handles
    assert all(handle is transaction for handle in handles)


async def test_writer_synthesizes_and_publishes_from_fixed_experiment_records():
    writer, _, analyses = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(_comparison_experiment("paper-a"),),
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
        experiments=(_multi_factor_comparison_experiment("paper-a"),),
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


async def test_writer_creates_conditional_group_for_cross_paper_finding():
    writer, _, analyses = _writer()
    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(
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
    experiment = _comparison_experiment("paper-a")

    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        source_fingerprints={"paper-a": "prepared-v1"},
    )
    await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        source_fingerprints={"paper-a": "prepared-v2"},
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


async def test_writer_does_not_fabricate_finding_without_matching_experiment():
    writer, _, analyses = _writer()
    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(),
    )

    assert result.revisions == ()
    assert result.selections == ()
    assert result.groups == ()
    assert result.findings == ()
    assert analyses.graphs[0].findings == ()

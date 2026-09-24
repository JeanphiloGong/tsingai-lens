from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
)
from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
from application.repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)
from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision
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


def _experiment(document_id: str, value: float, label: str):
    observation = _observation(f"{document_id}-result", document_id, value, label)
    return assemble_paper_experiment(
        collection_id="collection-1",
        document_id=document_id,
        source_facts=(observation,),
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


def _finding(
    *,
    documents: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    synthesis_status: str = "insufficient_confirmation",
) -> Finding:
    contributions = [
        {
            "document_id": document_id,
            "analysis_status": "analyzed",
            "supporting_evidence_ids": [evidence_id],
            "contradicting_evidence_ids": [],
            "context_evidence_ids": [],
            "condition_boundary_evidence_ids": [],
        }
        for document_id, evidence_id in zip(documents, evidence_ids)
    ]
    return Finding.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "finding_id": "finding-1" if len(documents) == 1 else "finding-cross",
            "statement": "Preheat was associated with a change in elongation.",
            "factors": ["preheat"],
            "outcome": "elongation",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "association_only",
            "synthesis_status": synthesis_status,
            "certainty": 0.5,
            "display_rank": 0,
            "mechanisms": [],
            "scientific_context": {},
            "limitations": [],
            "paper_contributions": contributions,
        }
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


class _SelectionRepository:
    def __init__(self):
        self.records: dict[str, ObjectiveExperimentSelection] = {}
        self.transaction_handles: list[object | None] = []

    async def add_selection(
        self, collection_id, selection, *, revision_id, transaction=None
    ):
        self.transaction_handles.append(transaction)
        existing = self.records.get(selection.selection_id)
        if existing is not None and existing != selection:
            raise ValueError("selection conflict")
        self.records[selection.selection_id] = selection
        return selection

    async def read_selection(self, collection_id, selection_id, *, transaction=None):
        self.transaction_handles.append(transaction)
        return self.records.get(selection_id)

    async def list_selections(self, collection_id, objective_id, analysis_version):
        return tuple(
            item
            for item in self.records.values()
            if item.objective_id == objective_id and item.analysis_version == analysis_version
        )


class _GroupRepository:
    def __init__(self):
        self.records: dict[str, ComparisonGroup] = {}
        self.transaction_handles: list[object | None] = []

    async def add_group(self, collection_id, group, *, transaction=None):
        self.transaction_handles.append(transaction)
        existing = self.records.get(group.group_id)
        if existing is not None and existing != group:
            raise ValueError("group conflict")
        self.records[group.group_id] = group
        return group

    async def read_group(self, collection_id, group_id, *, transaction=None):
        self.transaction_handles.append(transaction)
        return self.records.get(group_id)

    async def list_groups(self, collection_id, objective_id, analysis_version):
        return tuple(
            item
            for item in self.records.values()
            if item.objective_id == objective_id and item.analysis_version == analysis_version
        )


class _FindingRepository:
    def __init__(self):
        self.records: dict[str, Finding] = {}
        self.transaction_handles: list[object | None] = []

    async def add_finding(self, finding, *, transaction=None):
        self.transaction_handles.append(transaction)
        existing = self.records.get(finding.finding_id)
        if existing is not None:
            if existing == finding:
                return existing
            raise ValueError("finding conflict")
        self.records[finding.finding_id] = finding
        return finding

    async def read_finding(self, collection_id, finding_id):
        return self.records.get(finding_id)

    async def list_findings(self, collection_id, objective_id, analysis_version):
        return tuple(
            item
            for item in self.records.values()
            if item.objective_id == objective_id and item.analysis_version == analysis_version
        )


def _writer():
    revisions = _RevisionRepository()
    selections = _SelectionRepository()
    groups = _GroupRepository()
    findings = _FindingRepository()
    writer = ExperimentAnalysisWriter(
        paper_experiment_repository=revisions,
        selection_repository=selections,
        group_repository=groups,
        finding_publisher=ExperimentFindingPublisher(selections, groups, findings),
        finding_repository=findings,
    )
    return writer, revisions, selections, groups, findings


async def test_writer_creates_revision_selection_and_finding_idempotently():
    writer, revisions, selections, groups, findings = _writer()
    experiment = _experiment("paper-a", 72, "NP")
    source_facts = ("paper-a-result",)
    finding = _finding(documents=("paper-a",), evidence_ids=source_facts)

    first = await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        findings=(finding,),
    )
    second = await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        findings=(finding,),
    )

    assert len(first.revisions) == len(second.revisions) == 1
    assert first.revisions[0].revision.experiment_version == 1
    assert len(selections.records) == 1
    assert len(groups.records) == 0
    assert len(findings.records) == 1
    assert findings.records["finding-1"].selection_ids
    assert findings.records["finding-1"].paper_contributions == ()


async def test_writer_passes_one_transaction_to_every_graph_repository():
    writer, revisions, selections, groups, findings = _writer()
    transaction = object()

    await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(_experiment("paper-a", 72, "NP"),),
        findings=(_finding(documents=("paper-a",), evidence_ids=("paper-a-result",)),),
        transaction=transaction,
    )

    handles = (
        revisions.transaction_handles
        + selections.transaction_handles
        + groups.transaction_handles
        + findings.transaction_handles
    )
    assert handles
    assert all(handle is transaction for handle in handles)


async def test_writer_can_fix_experiment_selections_before_finding_synthesis():
    writer, revisions, selections, groups, findings = _writer()

    result = await writer.write_experiment_selections(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(_experiment("paper-a", 72, "NP"),),
    )

    assert len(result.revisions) == 1
    assert result.revisions[0].revision.document_id == "paper-a"
    assert len(result.selections) == 1
    assert result.selections[0].outcome == "elongation"
    assert len(revisions.records) == 1
    assert len(selections.records) == 1
    assert groups.records == {}
    assert findings.records == {}


async def test_writer_synthesizes_and_publishes_from_fixed_experiment_records():
    writer, _, _, groups, findings = _writer()

    result = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(_comparison_experiment("paper-a"),),
    )

    assert result.groups == ()
    assert groups.records == {}
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.selection_ids == (result.selections[0].selection_id,)
    assert finding.factors == ("preheat",)
    assert finding.direction == "increase"
    assert finding.synthesis_status == "single_study"
    assert finding.paper_contributions == ()
    assert findings.records == {finding.finding_id: finding}


async def test_writer_keeps_different_factor_sets_in_separate_selections():
    writer, _, _, _, _ = _writer()

    result = await writer.write_experiment_selections(
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
    writer, _, selections, groups, findings = _writer()
    result = await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(
            _experiment("paper-a", 72, "NP"),
            _experiment("paper-b", 68, "NP"),
        ),
        findings=(
            _finding(
                documents=("paper-a", "paper-b"),
                evidence_ids=("paper-a-result", "paper-b-result"),
                synthesis_status="agreement",
            ),
        ),
    )

    assert len(selections.records) == 2
    assert len(groups.records) == 1
    assert result.groups[0].status == "conditional"
    assert len(result.groups[0].members) == 2
    assert findings.records["finding-cross"].comparison_group_ids


async def test_changed_source_fingerprint_creates_successor_without_overwrite():
    writer, revisions, _, _, _ = _writer()
    experiment = _experiment("paper-a", 72, "NP")
    finding = _finding(documents=("paper-a",), evidence_ids=("paper-a-result",))

    await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        findings=(finding,),
        source_fingerprints={"paper-a": "prepared-v1"},
    )
    await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(experiment,),
        findings=(),
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
    writer, _, _, _, findings = _writer()
    result = await writer.write(
        collection_id="collection-1",
        objective=_objective(),
        analysis=_analysis(),
        experiments=(),
        findings=(_finding(documents=("paper-a",), evidence_ids=("missing",)),),
    )

    assert result.findings == ()
    assert result.skipped_finding_ids == ("finding-1",)
    assert findings.records == {}

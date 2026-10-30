from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest
from application.core.objectives.analysis import experiment_projection
from controllers.schemas.core.research_objectives import (
    FindingResponse,
    ObjectiveEvidenceResponse,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
)
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    SourceReference,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificContext,
    ScientificVariable,
)
from exceptions import ResourceNotFoundException
from repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _revision() -> PaperExperimentRevision:
    source = SourceReference(
        document_id="paper-1",
        source_fingerprint="prepared-1",
        source_kind="table",
        source_ref="table-2",
        quote="NP 72%; P150 82% elongation",
    )
    return PaperExperimentRevision(
        experiment_id="experiment-1",
        document_id="paper-1",
        experiment_version=int(1),
        source_fingerprint="prepared-1",
        label="Preheat series",
        scope_description="NP and P150 tensile results",
        design_type="parallel",
        identity_status="identified",
        binding_status="bound",
        variants=(
            ExperimentalVariant(
                variant_key="np",
                variant_label="NP",
                subject_attributes=(ScientificAttribute(name="alloy", value="316L"),),
                intervention_attributes=(
                    ScientificAttribute(name="preheat", value=0, unit="C"),
                ),
                source_refs=(source,),
                binding_source_refs=(source,),
                binding_status="direct",
            ),
            ExperimentalVariant(
                variant_key="p150",
                variant_label="P150",
                subject_attributes=(ScientificAttribute(name="alloy", value="316L"),),
                intervention_attributes=(
                    ScientificAttribute(name="preheat", value=150, unit="C"),
                ),
                source_refs=(source,),
                binding_source_refs=(source,),
                binding_status="direct",
            ),
        ),
        test_conditions=(
            ExperimentTestCondition(
                test_key="tensile",
                test_type="tensile",
                parameters=(
                    ScientificAttribute(name="temperature", value=25, unit="C"),
                ),
                source_refs=(source,),
                binding_status="direct",
            ),
        ),
        measurements=(
            ExperimentMeasurementResult(
                measurement_key="np-elongation",
                outcome="elongation",
                variant_key="np",
                test_key="tensile",
                value=72,
                unit="%",
                result_text="NP elongation 72%",
                source_refs=(source,),
                binding_source_refs=(source,),
                binding_status="direct",
            ),
            ExperimentMeasurementResult(
                measurement_key="p150-elongation",
                outcome="elongation",
                variant_key="p150",
                test_key="tensile",
                value=82,
                unit="%",
                result_text="P150 elongation 82%",
                source_refs=(source,),
                binding_source_refs=(source,),
                binding_status="direct",
            ),
        ),
        comparisons=(
            ExperimentComparison(
                comparison_key="np-vs-p150",
                baseline_variant_key="np",
                target_variant_key="p150",
                outcome="elongation",
                baseline_measurement_keys=("np-elongation",),
                target_measurement_keys=("p150-elongation",),
                changed_variables=(
                    ScientificVariable(
                        name="preheat", baseline_value=0, target_value=150, unit="C"
                    ),
                ),
                direction="increase",
                attribution_scope="isolated_effect",
                status="ready",
                source_refs=(source,),
                binding_source_refs=(source,),
                relation_status="direct",
            ),
        ),
    )


class _Selections:
    async def list_selections(self, db, collection_id, objective_id, analysis_version):
        return (
            ObjectiveExperimentSelection(
                selection_id="selection-1",
                objective_id=objective_id,
                analysis_version=analysis_version,
                experiment_id="experiment-1",
                experiment_version=1,
                outcome="elongation",
                measurement_keys=("np-elongation", "p150-elongation"),
                comparison_keys=("np-vs-p150",),
            ),
        )


class _Groups:
    async def list_groups(self, db, collection_id, objective_id, analysis_version):
        return ()


class _Findings:
    async def list_findings(self, db, collection_id, objective_id, analysis_version):
        return (
            Finding(
                collection_id=collection_id or "",
                objective_id=objective_id or "",
                analysis_version=analysis_version,
                finding_id="finding-1",
                statement="Preheat was associated with higher elongation.",
                factors=("preheat",),
                outcome="elongation",
                direction="increase",
                assertion_strength="associative",
                attribution_scope="isolated_effect",
                synthesis_status="single_study",
                certainty=0.8,
                display_rank=0,
                mechanisms=(),
                scientific_context=ScientificContext(),
                limitations=(),
                paper_contributions=(),
                selection_ids=("selection-1",),
            ),
        )


class _Experiments:
    async def read_revision(self, db, experiment_id, experiment_version):
        return StoredPaperExperimentRevision(
            revision_id=11,
            revision=_revision(),
            created_at=datetime.now(timezone.utc),
        )


class _ObjectiveRepository:
    async def read_analysis(self, collection_id, objective_id, analysis_version):
        return None if analysis_version == 99 else SimpleNamespace(status="succeeded")

    async def list_contributions(self, collection_id, objective_id, analysis_version):
        return ()


def _service() -> ModuleType:
    experiment_projection.ObjectiveRepo = _ObjectiveRepository()
    experiment_projection.experiment_query_service.ObjectiveRepo = (
        _ObjectiveRepository()
    )
    experiment_projection.experiment_query_service.PaperExperimentRepo = (
        _Experiments()
    )
    experiment_projection.experiment_query_service.ObjectiveExperimentSelectionRepo = (
        _Selections()
    )
    experiment_projection.experiment_query_service.ComparisonGroupRepo = (
        _Groups()
    )
    experiment_projection.experiment_query_service.ExperimentFindingRepo = (
        _Findings()
    )
    return experiment_projection


async def test_projection_preserves_existing_finding_and_evidence_shapes() -> None:
    service = _service()

    findings, total = await service.list_analysis_findings(
        "collection-1", "objective-1", 1, offset=0, limit=50
    )
    evidence, evidence_total = await service.list_analysis_evidence(
        "collection-1", "objective-1", 1, finding_id="finding-1", offset=0, limit=50
    )

    assert total == 1
    assert findings[0].paper_contributions[0].document_id == "paper-1"
    assert findings[0].paper_contributions[0].supporting_evidence_ids
    assert evidence_total == 3
    assert {item.document_id for item in evidence} == {"paper-1"}
    assert {item.source_ref for item in evidence} == {"table-2"}
    assert any(item.reported_result.value == 82 for item in evidence)
    FindingResponse.model_validate(findings[0], from_attributes=True)
    for item in evidence:
        ObjectiveEvidenceResponse.model_validate(item, from_attributes=True)


async def test_projection_returns_no_legacy_evidence_for_unknown_finding() -> None:
    service = _service()

    evidence, total = await service.list_analysis_evidence(
        "collection-1", "objective-1", 1, finding_id="missing", offset=0, limit=50
    )

    assert evidence == ()
    assert total == 0


async def test_projection_rejects_unknown_analysis_snapshot() -> None:
    experiment_projection.experiment_query_service.PaperExperimentRepo = (
        _Experiments()
    )
    experiment_projection.experiment_query_service.ObjectiveExperimentSelectionRepo = (
        _Selections()
    )
    experiment_projection.experiment_query_service.ComparisonGroupRepo = (
        _Groups()
    )
    experiment_projection.experiment_query_service.ExperimentFindingRepo = (
        _Findings()
    )
    experiment_projection.ObjectiveRepo = _ObjectiveRepository()
    experiment_projection.experiment_query_service.ObjectiveRepo = (
        _ObjectiveRepository()
    )
    service = experiment_projection

    with pytest.raises(ResourceNotFoundException, match="Analysis snapshot not found"):
        await service.list_analysis_findings(
            "collection-1", "objective-1", 99, offset=0, limit=50
        )


async def test_projection_builds_the_existing_evidence_map_contract() -> None:
    service = _service()
    objective = SimpleNamespace(
        collection_id="collection-1",
        objective_id="objective-1",
        published_analysis_version=1,
        question="Does preheat change elongation?",
        material_scope=("316L",),
        variables=("preheat",),
        outcomes=("elongation",),
    )
    analysis = SimpleNamespace(analysis_version=1)
    profile = SimpleNamespace(document_id="paper-1", title="Preheat paper")

    payload = await service.build_evidence_map(
        objective=objective,
        analysis=analysis,
        profiles=(profile,),
    )

    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["coverage"]["finding_count"] == 1
    assert any(
        node["type"] == "document" and node["label"] == "Preheat paper"
        for node in payload["nodes"]
    )


async def test_projection_keeps_captured_response_and_typed_review_values(monkeypatch) -> None:
    import json
    from pathlib import Path

    service = _service()
    identity = ("collection-1", "objective-1", 1)
    from unittest.mock import AsyncMock
    from application.core.objectives import analysis_service

    monkeypatch.setattr(analysis_service, "experiment_projection", service)
    monkeypatch.setattr(analysis_service, "collection_service", SimpleNamespace(
        get_collection_for_user=AsyncMock(),
    ))
    monkeypatch.setattr(analysis_service, "_published_version", AsyncMock(return_value=1))
    monkeypatch.setattr(analysis_service, "should_read_experiment_projection", AsyncMock(return_value=True))
    objective = SimpleNamespace(
        objective_id="objective-1", active_analysis_version=None,
        published_analysis_version=1,
    )
    analysis = SimpleNamespace(
        analysis_version=1, origin="system_generated", status="succeeded",
        scientific_record_source="experiment_graph",
    )
    monkeypatch.setattr(analysis_service, "ObjectiveRepo", SimpleNamespace(
        read_objective_record=AsyncMock(return_value=SimpleNamespace(objective=objective)),
        read_analysis=AsyncMock(return_value=analysis),
    ))
    collection_id, objective_id, version = identity
    findings_view = await analysis_service.list_findings(
        collection_id, objective_id, analysis_version=version, user_id="user-1",
    )
    evidence_view = await analysis_service.list_evidence(
        collection_id, objective_id, analysis_version=version, user_id="user-1",
    )
    state = await analysis_service._result(collection_id, objective_id)
    payload = {
        "findings": findings_view["items"],
        "evidence": evidence_view["items"],
        "contributions": state["paper_contributions"],
    }
    baseline = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures"
            / "experiment_projection_response.json"
        ).read_text()
    )
    assert json.loads(json.dumps(payload)) == baseline
    findings, evidence, contributions = await service.read_analysis_records(*identity)
    assert findings[0].synthesis_status == "insufficient_confirmation"
    assert findings[0].selection_ids == ()
    assert set(findings[0].supporting_evidence_ids) == {
        item.evidence_id for item in evidence
    }
    assert (
        contributions[0].document_id == findings[0].paper_contributions[0].document_id
    )


async def test_partial_measurement_keeps_missing_context_in_read_view(monkeypatch) -> None:
    from unittest.mock import AsyncMock
    from application.core.objectives import analysis_service

    class PartialExperiments(_Experiments):
        async def read_revision(self, *args):
            stored = await super().read_revision(*args)
            measurement = replace(
                stored.revision.measurements[0], variant_key=None, test_key=None,
                binding_status="partial",
            )
            return replace(stored, revision=replace(
                stored.revision, measurements=(measurement,), comparisons=(),
                binding_status="partial",
            ))

    class PartialSelections(_Selections):
        async def list_selections(self, *args):
            selection, = await super().list_selections(*args)
            return (replace(selection, measurement_keys=("np-elongation",), comparison_keys=()),)

    projection = _service()
    monkeypatch.setattr(projection.experiment_query_service, "PaperExperimentRepo", PartialExperiments())
    monkeypatch.setattr(projection.experiment_query_service, "ObjectiveExperimentSelectionRepo", PartialSelections())
    records, total = await projection.list_analysis_evidence("collection-1", "objective-1", 1)
    assert total == 1
    assert records[0].resolution_status == "partial"
    assert records[0].reported_result.value == 72
    monkeypatch.setattr(analysis_service, "experiment_projection", projection)
    monkeypatch.setattr(analysis_service, "collection_service", SimpleNamespace(get_collection_for_user=AsyncMock()))
    monkeypatch.setattr(analysis_service, "_published_version", AsyncMock(return_value=1))
    monkeypatch.setattr(analysis_service, "should_read_experiment_projection", AsyncMock(return_value=True))
    response = await analysis_service.list_evidence("collection-1", "objective-1", user_id="user-1")
    item, = response["items"]
    assert item["evidence_status"] == "needs_context"
    assert item["evidence_status_reason"] == "The selected measurement has incomplete binding context."
    assert item["reported_result"]["value"] == 72
    assert item["source_ref"] == "table-2"

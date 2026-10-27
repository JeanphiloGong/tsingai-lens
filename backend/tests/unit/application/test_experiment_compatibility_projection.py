from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from application.core.objectives.analysis.experiment_compatibility_projection import (
    ExperimentCompatibilityProjection,
)
from controllers.schemas.core.research_objectives import (
    FindingResponse,
    ObjectiveEvidenceResponse,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
)
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _positive_int as finding_positive_int
from domain.core.finding import _text as finding_text
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
    async def list_selections(self, collection_id, objective_id, analysis_version):
        return (
            ObjectiveExperimentSelection(
                selection_id='selection-1',
                objective_id=objective_id,
                analysis_version=analysis_version,
                experiment_id='experiment-1',
                experiment_version=1,
                outcome='elongation',
                measurement_keys=('np-elongation', 'p150-elongation'),
                comparison_keys=('np-vs-p150',),
            ),
        )


class _Groups:
    async def list_groups(self, collection_id, objective_id, analysis_version):
        return ()


class _Findings:
    async def list_findings(self, collection_id, objective_id, analysis_version):
        return (
            Finding(
                collection_id=finding_text(collection_id) or "",
                objective_id=finding_text(objective_id) or "",
                analysis_version=finding_positive_int(analysis_version),
                finding_id="finding-1",
                statement="Preheat was associated with higher elongation.",
                factors=("preheat",),
                outcome="elongation",
                direction="increase",
                assertion_strength="associative",
                attribution_scope=finding_choice(
                    "isolated_effect",
                    EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
                    "descriptive_only",
                ),
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
    async def read_revision(self, experiment_id, experiment_version):
        return StoredPaperExperimentRevision(
            revision_id=11,
            revision=_revision(),
            created_at=datetime.now(timezone.utc),
        )


class _ObjectiveRepository:
    async def read_analysis(self, collection_id, objective_id, analysis_version):
        return None


def _service() -> ExperimentCompatibilityProjection:
    return ExperimentCompatibilityProjection(
        paper_experiment_repository=_Experiments(),
        selection_repository=_Selections(),
        group_repository=_Groups(),
        finding_repository=_Findings(),
    )


async def test_projection_preserves_existing_finding_and_evidence_shapes() -> None:
    service = _service()

    findings, total = await service.list_findings(
        "collection-1", "objective-1", 1, offset=0, limit=50
    )
    evidence, evidence_total = await service.list_evidence(
        "collection-1", "objective-1", 1, finding_id="finding-1", offset=0, limit=50
    )

    assert total == 1
    assert findings[0]["paper_contributions"][0]["document_id"] == "paper-1"
    assert findings[0]["paper_contributions"][0]["supporting_evidence_ids"]
    assert evidence_total == 3
    assert {item["document_id"] for item in evidence} == {"paper-1"}
    assert {item["source_ref"] for item in evidence} == {"table-2"}
    assert any(item["reported_result"]["value"] == 82 for item in evidence)
    FindingResponse.model_validate(findings[0])
    for item in evidence:
        ObjectiveEvidenceResponse.model_validate(item)


async def test_projection_returns_no_legacy_evidence_for_unknown_finding() -> None:
    service = _service()

    evidence, total = await service.list_evidence(
        "collection-1", "objective-1", 1, finding_id="missing", offset=0, limit=50
    )

    assert evidence == ()
    assert total == 0


async def test_projection_rejects_unknown_analysis_snapshot() -> None:
    service = ExperimentCompatibilityProjection(
        paper_experiment_repository=_Experiments(),
        selection_repository=_Selections(),
        group_repository=_Groups(),
        finding_repository=_Findings(),
        objective_repository=_ObjectiveRepository(),
    )

    with pytest.raises(FileNotFoundError, match="analysis snapshot not found"):
        await service.list_findings(
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


async def test_projection_keeps_captured_response_and_typed_review_values() -> None:
    import json
    from pathlib import Path

    service = _service()
    identity = ("collection-1", "objective-1", 1)
    payload = {
        "findings": (await service.list_findings(*identity))[0],
        "evidence": (await service.list_evidence(*identity))[0],
        "contributions": await service.list_contributions(*identity),
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

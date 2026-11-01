from __future__ import annotations

from domain.core.finding import Finding, FindingPaperContribution
from domain.core.scientific_fact import ScientificContext
from domain.evaluation import FindingCuration, FindingFeedback
from domain.goal import ExperimentPlanRecord


def test_experiment_plan_record_has_only_objective_identity() -> None:
    plan = ExperimentPlanRecord(
        plan_id="plan-1",
        collection_id="collection-1",
        objective_id="objective-1",
        title="Validation plan",
        content="Compare two processing conditions.",
        status="draft",
        source_message_id=None,
        source_links=(),
        metadata={},
        created_by=None,
        created_at="2026-07-20T00:00:00+00:00",
        updated_at="2026-07-20T00:00:00+00:00",
    )

    assert plan.objective_id == "objective-1"
    assert not hasattr(plan, "goal_id")


def test_review_records_have_only_objective_identity() -> None:
    feedback = FindingFeedback(
        feedback_id="feedback-1",
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
        note=None,
        reviewer=None,
        created_at="2026-07-20T00:00:00+00:00",
    )
    finding = Finding(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        finding_id="finding-1",
        statement="The reviewed finding.",
        factors=("temperature",),
        outcome="strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope="isolated_effect",
        synthesis_status="insufficient_confirmation",
        certainty=0.5,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=("One directly contributing paper.",),
        paper_contributions=(FindingPaperContribution(
            document_id="paper-1",
            analysis_status="analyzed",
            supporting_evidence_ids=("evidence-1",),
        ),),
    )
    curation = FindingCuration(
        curation_id="curation-1",
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        finding_id="finding-1",
        curated_status="supported",
        curated_finding=finding,
        note=None,
        reviewer=None,
        updated_at="2026-07-20T00:00:00+00:00",
    )

    assert curation.curated_finding.key == (
        feedback.collection_id, feedback.objective_id,
        feedback.analysis_version, feedback.finding_id,
    )
    for record in (feedback, curation):
        assert record.objective_id == "objective-1"
        assert not hasattr(record, "scope_type")
        assert not hasattr(record, "scope_id")
        assert not hasattr(record, "claim_id")

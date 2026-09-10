from __future__ import annotations

import pytest

from domain.goal import ExperimentPlanRecord


def _plan_payload(**overrides):
    payload = {
        "plan_id": "plan-v1",
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "title": "Validate laser-power effects",
        "content": "Compare an expert-approved laser-power matrix.",
        "status": "draft",
        "source_message_id": None,
        "source_links": [],
        "metadata": {"source": "manual"},
        "created_by": "researcher-1",
        "created_at": "2026-09-07T00:00:00+00:00",
        "updated_at": "2026-09-07T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_legacy_plan_defaults_to_an_unstructured_first_revision() -> None:
    plan = ExperimentPlanRecord.from_mapping(_plan_payload())

    assert plan.plan_version == 1
    assert plan.parent_plan_id is None
    assert plan.structured_plan is None
    assert plan.updated_by is None


def test_structured_plan_round_trip_preserves_the_approved_payload() -> None:
    structured_plan = {
        "hypothesis": "Higher laser power may reduce porosity.",
        "variables": [
            {
                "name": "laser power",
                "role": "independent",
                "levels": ["expert-selected baseline", "expert-selected increase"],
            }
        ],
        "measurements": [
            {"outcome": "porosity", "method": "image analysis", "unit": "%"}
        ],
        "controls": ["powder batch", "layer thickness"],
        "replicates": 3,
    }
    plan = ExperimentPlanRecord.from_mapping(
        _plan_payload(
            structured_plan=structured_plan,
            updated_by="researcher-1",
        )
    )

    assert plan.structured_plan == structured_plan
    assert plan.to_record()["structured_plan"] == structured_plan
    assert plan.to_record()["updated_by"] == "researcher-1"


def test_later_revision_requires_an_immediate_parent_and_actor() -> None:
    with pytest.raises(ValueError, match="parent_plan_id"):
        ExperimentPlanRecord.from_mapping(_plan_payload(plan_version=2))

    with pytest.raises(ValueError, match="updated_by"):
        ExperimentPlanRecord.from_mapping(
            _plan_payload(
                plan_id="plan-v2",
                plan_version=2,
                parent_plan_id="plan-v1",
            )
        )


def test_first_revision_cannot_point_to_a_parent() -> None:
    with pytest.raises(ValueError, match="first revision"):
        ExperimentPlanRecord.from_mapping(
            _plan_payload(parent_plan_id="another-plan")
        )


def test_plan_version_rejects_non_integral_values() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ExperimentPlanRecord.from_mapping(_plan_payload(plan_version=1.5))


def test_next_revision_is_direct_validated_and_copies_structured_content(monkeypatch) -> None:
    plan = ExperimentPlanRecord.from_mapping(_plan_payload())
    structured = {"variables": [{"name": "laser power", "levels": [100, 200]}]}

    def reject_serialization(_self):
        pytest.fail("revision must not serialize the existing Plan")

    monkeypatch.setattr(ExperimentPlanRecord, "to_record", reject_serialization)
    revision = plan.next_revision(
        plan_id="plan-v2", title=" Reviewed matrix ", content=" Approved levels. ",
        status="ready_for_review", structured_plan=structured,
        updated_by=" researcher-2 ", updated_at="2026-09-09T00:00:00+00:00",
    )
    structured["variables"][0]["levels"].append(300)

    assert revision.plan_version == 2
    assert revision.parent_plan_id == plan.plan_id
    assert revision.updated_by == "researcher-2"
    assert revision.title == "Reviewed matrix"
    assert revision.structured_plan["variables"][0]["levels"] == [100, 200]
    assert plan.plan_version == 1

    with pytest.raises(ValueError, match="updated_by"):
        plan.next_revision(
            plan_id="plan-v2", title="Reviewed", content="Approved", status="draft",
            structured_plan=None, updated_by=None, updated_at=plan.updated_at,
        )
    with pytest.raises(ValueError, match="cannot equal"):
        plan.next_revision(
            plan_id=plan.plan_id, title="Reviewed", content="Approved", status="draft",
            structured_plan=None, updated_by="reviewer", updated_at=plan.updated_at,
        )

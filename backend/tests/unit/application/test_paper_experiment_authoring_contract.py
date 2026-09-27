from __future__ import annotations

from copy import deepcopy

import pytest

from application.core.objectives.analysis.paper_experiment_contract import (
    DraftReadiness,
    PaperExperimentModelOutput,
    assess_draft_readiness,
    bind_model_output,
    prepare_model_output,
    reconcile_model_output,
)
from domain.core.research_objective import ResearchObjective


def _output_payload() -> dict:
    return {
        "document_id": "doc-1",
        "source_fingerprint": "prep-1",
        "source_labels": {
            "methods": {
                "document_id": "doc-1",
                "source_fingerprint": "prep-1",
                "source_kind": "section",
                "source_ref": "methods-1",
                "quote": "All groups were tested by tensile loading.",
            },
            "table": {
                "document_id": "doc-1",
                "source_fingerprint": "prep-1",
                "source_kind": "table",
                "source_ref": "table-2",
                "quote": "NP 72%; P150 82%.",
            },
        },
        "experiments": [
            {
                "label": "Preheat tensile series",
                "scope_description": "NP and P150",
                "design_type": "parallel",
                "variants": [
                    {
                        "variant_key": "np",
                        "variant_label": "NP",
                        "identity_specificity": "exact",
                        "source_labels": ["methods"],
                    },
                    {
                        "variant_key": "p150",
                        "variant_label": "P150",
                        "identity_specificity": "exact",
                        "source_labels": ["methods"],
                    },
                ],
                "test_conditions": [
                    {
                        "test_key": "tensile",
                        "test_type": "tensile",
                        "source_labels": ["methods"],
                    }
                ],
                "measurements": [
                    {
                        "measurement_key": "np-elongation",
                        "outcome": "elongation",
                        "variant_key": "np",
                        "test_key": "tensile",
                        "value": 72,
                        "unit": "%",
                        "source_labels": ["table"],
                    },
                    {
                        "measurement_key": "p150-elongation",
                        "outcome": "elongation",
                        "variant_key": "p150",
                        "test_key": "tensile",
                        "value": 82,
                        "unit": "%",
                        "source_labels": ["table"],
                    },
                ],
            }
        ],
    }


def _raw_model_payload() -> dict:
    payload = _output_payload()
    payload.pop("document_id")
    payload.pop("source_fingerprint")
    payload.pop("source_labels")
    return payload


def _reconciled_output(payload: dict | None = None):
    output = PaperExperimentModelOutput.from_mapping(payload or _output_payload())
    return reconcile_model_output(output, accepted_experiment_keys=("series-1",))


def test_raw_model_output_cannot_receive_formal_identity_directly() -> None:
    output = PaperExperimentModelOutput.from_mapping(_output_payload())

    with pytest.raises(ValueError, match="boundary reconciliation"):
        bind_model_output(
            output,
            experiment_ids=["exp-1"],
            experiment_versions=[1],
            document_id="doc-1",
            source_fingerprint="prep-1",
        )


def test_raw_boundary_envelope_cannot_be_marked_as_reconciled() -> None:
    payload = _output_payload()
    payload["experiments"][0]["boundary_proposals"] = [{"series_key": "raw-1"}]
    output = PaperExperimentModelOutput.from_mapping(payload)

    with pytest.raises(ValueError, match="raw boundary proposals"):
        reconcile_model_output(output, accepted_experiment_keys=("series-1",))


def test_selected_scope_requires_parent_and_source_backed_selector() -> None:
    payload = _output_payload()
    payload["experiments"][0]["scope_kind"] = "selected_stratum"
    output = PaperExperimentModelOutput.from_mapping(payload)

    with pytest.raises(ValueError, match="scope_selector"):
        reconcile_model_output(output, accepted_experiment_keys=("series-1",))


@pytest.mark.parametrize(
    ("scope_kind", "scope_selector"),
    [
        (
            "selected_stratum",
            {"selected_levels": [{"name": "preheat", "value": 150, "unit": "C"}]},
        ),
        ("follow_up", {"test_scope_labels": ["tensile"]}),
    ],
)
def test_reconciled_scoped_experiment_with_parent_can_bind(
    scope_kind: str, scope_selector: dict[str, object]
) -> None:
    payload = _output_payload()
    payload["experiments"][0].update(
        {
            "scope_kind": scope_kind,
            "parent_series_key": "series-1",
            "scope_selector": scope_selector,
        }
    )

    revisions = bind_model_output(
        reconcile_model_output(
            PaperExperimentModelOutput.from_mapping(payload),
            accepted_experiment_keys=("series-1",),
        ),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )

    assert revisions[0].experiment_id == "exp-1"
    assert revisions[0].label == "Preheat tensile series"


def test_model_output_binds_sources_and_service_identity() -> None:
    output = _reconciled_output()

    revisions = bind_model_output(
        output,
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )

    assert revisions[0].experiment_id == "exp-1"
    assert revisions[0].experiment_version == 1
    assert revisions[0].measurements[0].source_refs[0].source_ref == "table-2"
    assert revisions[0].variants[0].source_refs[0].source_ref == "methods-1"


def test_source_label_binding_accepts_tuple_set_and_scalar_nested_values() -> None:
    payload = _output_payload()
    experiment = payload["experiments"][0]
    experiment["variants"][0]["source_labels"] = {"methods"}
    experiment["test_conditions"][0]["source_labels"] = ("methods",)
    measurement = experiment["measurements"][0]
    measurement["source_labels"] = ("table",)
    measurement["variant_binding_source_labels"] = "methods"
    measurement["test_binding_source_labels"] = {"methods"}

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.variants[0].source_refs[0].source_ref == "methods-1"
    assert revision.test_conditions[0].source_refs[0].source_ref == "methods-1"
    assert revision.measurements[0].source_refs[0].source_ref == "table-2"
    assert revision.measurements[0].binding_source_refs[0].source_ref == "methods-1"

    invalid = _output_payload()
    invalid["experiments"][0]["measurements"][0]["source_labels"] = "missing"
    with pytest.raises(ValueError, match="unknown source label"):
        bind_model_output(
            _reconciled_output(invalid),
            experiment_ids=["exp-1"],
            experiment_versions=[1],
            document_id="doc-1",
            source_fingerprint="prep-1",
        )


def test_broad_measurement_scope_is_preserved_instead_of_being_dropped() -> None:
    payload = _output_payload()
    measurement = payload["experiments"][0]["measurements"][0]
    measurement.update(
        {
            "variant_key": None,
            "test_key": None,
            "reported_sample_label": "as-SLM",
            "reported_test_label": "mechanical test",
            "candidate_variant_keys": ["np", "p150"],
            "candidate_test_keys": ["tensile"],
            "binding_status_candidate": "partial",
        }
    )

    output = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("series-1",),
    )
    revision = bind_model_output(
        output,
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    stored = revision.measurements[0]
    assert stored.variant_key is None
    assert stored.test_key is None
    assert stored.measurement_scope["reported_scope"] == {
        "reported_sample_label": "as-SLM",
        "reported_test_label": "mechanical test",
        "candidate_variant_keys": ["np", "p150"],
        "candidate_test_keys": ["tensile"],
        "binding_status_candidate": "partial",
    }
    assert any(
        issue["target_ref"] == "measurements/np-elongation"
        and "binding remains unresolved" in issue["description"]
        for issue in revision.unresolved_issues
    )


def test_prepare_model_output_generates_response_local_series_key() -> None:
    payload = _output_payload()
    payload["experiments"][0].pop("series_key", None)
    prepared = prepare_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        objective=ResearchObjective.from_mapping(
            {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "question": "Does preheating affect elongation?",
                "material_scope": ["316L"],
                "variables": ["preheating"],
                "outcomes": ["elongation"],
                "seed_document_ids": ["doc-1"],
                "confidence": 1.0,
            }
        ),
    )
    assert prepared.output.experiments[0].payload["series_key"].startswith("draft_")


def test_missing_binding_without_labels_still_creates_a_targeted_issue() -> None:
    payload = _output_payload()
    payload["experiments"][0]["measurements"][0].update(
        {"variant_key": None, "test_key": None}
    )
    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert any(
        issue["target_ref"] == "measurements/np-elongation"
        for issue in revision.unresolved_issues
    )


def test_raw_model_payload_gets_context_and_source_catalog_from_service() -> None:
    envelope = PaperExperimentModelOutput.from_model_mapping(
        _raw_model_payload(),
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_labels=_output_payload()["source_labels"],
    )

    revisions = bind_model_output(
        reconcile_model_output(envelope, accepted_experiment_keys=("series-1",)),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )

    assert revisions[0].measurements[0].source_refs[0].source_ref == "table-2"


def test_raw_model_payload_preserves_reported_identifiers_in_population_scope() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["population_scope"] = {
        "kind": "specimen",
        "reported_identifiers": {
            "sample_id": "S-01",
            "batch_id": "B-7",
        },
    }
    envelope = PaperExperimentModelOutput.from_model_mapping(
        payload,
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_labels=_output_payload()["source_labels"],
    )

    revision = bind_model_output(
        reconcile_model_output(envelope, accepted_experiment_keys=("series-1",)),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.variants[0].population_scope == {
        "kind": "specimen",
        "reported_identifiers": {
            "sample_id": "S-01",
            "batch_id": "B-7",
        },
    }


def test_raw_model_payload_preserves_plural_reported_identifiers_in_scope() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["population_scope"] = {
        "kind": "specimen_group",
        "reported_identifiers": {
            "sample_ids": ["S-01", "S-02"],
            "batch_ids": ["B-7", "B-8"],
        },
    }
    envelope = PaperExperimentModelOutput.from_model_mapping(
        payload,
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_labels=_output_payload()["source_labels"],
    )

    revision = bind_model_output(
        reconcile_model_output(envelope, accepted_experiment_keys=("series-1",)),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.variants[0].population_scope == {
        "kind": "specimen_group",
        "reported_identifiers": {
            "sample_ids": ["S-01", "S-02"],
            "batch_ids": ["B-7", "B-8"],
        },
    }


def test_raw_model_payload_preserves_domain_specific_reported_identifiers() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["population_scope"] = {
        "kind": "participant_group",
        "reported_identifiers": {
            "stimulus_id": "face-set-3",
            "condition_id": "dual-task",
        },
    }
    payload["experiments"][0]["measurements"][0]["measurement_scope"] = {
        "reported_identifiers": {
            "task_id": "reaction-time-1",
        },
    }

    envelope = PaperExperimentModelOutput.from_model_mapping(
        payload,
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_labels=_output_payload()["source_labels"],
    )

    revision = bind_model_output(
        reconcile_model_output(envelope, accepted_experiment_keys=("series-1",)),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.variants[0].population_scope == {
        "kind": "participant_group",
        "reported_identifiers": {
            "stimulus_id": "face-set-3",
            "condition_id": "dual-task",
        },
    }
    assert revision.measurements[0].measurement_scope["reported_identifiers"] == {
        "task_id": "reaction-time-1",
    }


def test_raw_model_payload_rejects_formal_identity_inside_reported_identifiers() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["population_scope"] = {
        "reported_identifiers": {
            "experiment_id": "paper-exp-1",
        },
    }

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_model_mapping(
            payload,
            document_id="doc-1",
            source_fingerprint="prep-1",
            source_labels=_output_payload()["source_labels"],
        )


def test_raw_model_payload_rejects_reported_identifier_as_component_field() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["sample_id"] = "S-01"

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_model_mapping(
            payload,
            document_id="doc-1",
            source_fingerprint="prep-1",
            source_labels=_output_payload()["source_labels"],
        )


def test_raw_model_payload_rejects_domain_identifier_outside_scope_map() -> None:
    payload = _raw_model_payload()
    payload["experiments"][0]["variants"][0]["condition_id"] = "dual-task"

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_model_mapping(
            payload,
            document_id="doc-1",
            source_fingerprint="prep-1",
            source_labels=_output_payload()["source_labels"],
        )


def test_raw_model_payload_cannot_echo_request_context() -> None:
    payload = _raw_model_payload()
    payload["document_id"] = "doc-1"

    with pytest.raises(ValueError, match="request context"):
        PaperExperimentModelOutput.from_model_mapping(
            payload,
            document_id="doc-1",
            source_fingerprint="prep-1",
            source_labels=_output_payload()["source_labels"],
        )


def test_raw_model_payload_cannot_invent_source_label_catalog_entry() -> None:
    payload = _raw_model_payload()
    payload["source_labels"] = ["model-invented"]

    with pytest.raises(ValueError, match="unknown source labels"):
        PaperExperimentModelOutput.from_model_mapping(
            payload,
            document_id="doc-1",
            source_fingerprint="prep-1",
            source_labels=_output_payload()["source_labels"],
        )


def test_model_cannot_supply_formal_identity() -> None:
    payload = _output_payload()
    payload["experiments"][0]["experiment_id"] = "model-made-id"

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_mapping(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "measurement_ids",
        "result_ids",
        "comparison_ids",
        "source_ids",
        "arbitrary_record_id",
        "arbitrary_record_ids",
        "collection_id",
        "objective_id",
        "experiment_version",
    ],
)
def test_model_cannot_supply_formal_top_level_fields(field_name: str) -> None:
    payload = _output_payload()
    payload[field_name] = "model-made-value"

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_mapping(payload)


@pytest.mark.parametrize(
    "field_path",
    [
        ("experiments", 0, "identity_status"),
        ("experiments", 0, "variants", 0, "binding_status"),
        ("experiments", 0, "measurements", 0, "measurement_id"),
        ("experiments", 0, "measurements", 0, "source_refs"),
        ("experiments", 0, "measurements", 0, "status"),
        ("experiments", 0, "unresolved_issues", 0, "result_ids"),
    ],
)
def test_model_cannot_supply_nested_identity_or_validation_fields(field_path) -> None:
    payload = _output_payload()
    if "unresolved_issues" in field_path:
        payload["experiments"][0]["unresolved_issues"] = [{}]
    target = payload
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = "model-made-value"

    with pytest.raises(ValueError, match="validation fields"):
        PaperExperimentModelOutput.from_mapping(payload)


def test_unknown_source_label_blocks_binding() -> None:
    payload = _output_payload()
    payload["experiments"][0]["measurements"][0]["source_labels"] = ["missing"]
    output = _reconciled_output(payload)

    with pytest.raises(ValueError, match="unknown source label"):
        bind_model_output(
            output,
            experiment_ids=["exp-1"],
            experiment_versions=[1],
            document_id="doc-1",
            source_fingerprint="prep-1",
        )


def test_zero_experiment_output_is_valid_and_does_not_create_empty_experiment() -> None:
    output = PaperExperimentModelOutput.from_mapping(
        {
            "document_id": "doc-1",
            "source_fingerprint": "prep-1",
            "experiments": [],
            "unresolved_issues": [
                {"target_ref": "document", "description": "only background discussion found"}
            ],
        }
    )

    assert output.experiments == ()
    assert bind_model_output(
        reconcile_model_output(output, accepted_experiment_keys=()),
        experiment_ids=[],
        experiment_versions=[],
        document_id="doc-1",
        source_fingerprint="prep-1",
    ) == ()


def test_trusted_envelope_cannot_hide_formal_ids_in_top_level_unresolved_issues() -> None:
    payload = _output_payload()
    payload["unresolved_issues"] = [{"related_record_id": "model-made-id"}]

    with pytest.raises(ValueError, match="formal identity"):
        PaperExperimentModelOutput.from_mapping(payload)


def test_malformed_experiment_container_is_rejected_instead_of_becoming_zero_experiments() -> None:
    payload = _output_payload()
    payload["experiments"] = {"label": "not-a-list"}

    with pytest.raises(ValueError, match="experiments must be a list"):
        PaperExperimentModelOutput.from_mapping(payload)


def test_draft_level_source_labels_are_resolved_into_revision_sources() -> None:
    payload = _output_payload()
    payload["experiments"][0]["source_labels"] = ["methods"]

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert [item.source_ref for item in revision.source_refs] == ["methods-1"]


def test_selected_scope_selector_must_hit_a_local_variant_or_test() -> None:
    payload = _output_payload()
    payload["experiments"][0].update(
        {
            "scope_kind": "selected_stratum",
            "parent_series_key": "series-1",
            "scope_selector": {
                "selected_levels": [
                    {"name": "preheat", "value": 999, "unit": "C"}
                ]
            },
        }
    )

    with pytest.raises(ValueError, match="does not match"):
        reconcile_model_output(
            PaperExperimentModelOutput.from_mapping(payload),
            accepted_experiment_keys=("series-1",),
        )


def test_unresolved_physical_split_is_collapsed_before_identity_allocation() -> None:
    payload = _output_payload()
    second = {
        **payload["experiments"][0],
        "label": "Same series from another section",
        "series_key": "section-2",
        "scope_kind": "unknown",
    }
    payload["experiments"][0]["series_key"] = "parent"
    payload["experiments"] = [payload["experiments"][0], second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent",),
    )

    assert len(reconciled.output.experiments) == 1
    assert reconciled.accepted_experiment_keys == ("parent",)
    assert any("collapsed" in str(item.get("description")) for item in reconciled.audit_issues)


def test_unknown_only_boundary_candidates_are_not_merged_by_response_order() -> None:
    payload = _output_payload()
    first = deepcopy(payload["experiments"][0])
    first["series_key"] = "unknown-1"
    first["scope_kind"] = "unknown"
    second = deepcopy(payload["experiments"][0])
    second["series_key"] = "unknown-2"
    second["scope_kind"] = "unknown"
    payload["experiments"] = [first, second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("unknown-1", "unknown-2"),
    )

    assert len(reconciled.output.experiments) == 2
    assert reconciled.accepted_experiment_keys == ("unknown-1", "unknown-2")
    assert not reconciled.audit_issues


def test_unknown_candidate_is_not_absorbed_by_selected_scope_without_parent() -> None:
    payload = _output_payload()
    unknown = deepcopy(payload["experiments"][0])
    unknown["series_key"] = "unknown-parent"
    unknown["scope_kind"] = "unknown"
    selected = deepcopy(payload["experiments"][0])
    selected.update(
        {
            "series_key": "selected-p150",
            "scope_kind": "selected_stratum",
            "parent_series_key": "unknown-parent",
            "scope_selector": {"test_scope_labels": ["tensile"]},
        }
    )
    payload["experiments"] = [unknown, selected]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("unknown-parent", "selected-p150"),
    )

    assert len(reconciled.output.experiments) == 2
    assert reconciled.accepted_experiment_keys == (
        "unknown-parent",
        "selected-p150",
    )


def test_explicit_parent_does_not_absorb_incompatible_unknown_scope() -> None:
    payload = _output_payload()
    parent = deepcopy(payload["experiments"][0])
    parent["series_key"] = "parent"
    parent["scope_kind"] = "parent"
    unknown = deepcopy(payload["experiments"][0])
    unknown["series_key"] = "unknown-other-population"
    unknown["scope_kind"] = "unknown"
    unknown["variants"][0]["variant_label"] = "Independent cohort"
    payload["experiments"] = [parent, unknown]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent", "unknown-other-population"),
    )

    assert len(reconciled.output.experiments) == 2
    assert reconciled.accepted_experiment_keys == (
        "parent",
        "unknown-other-population",
    )


def test_positive_split_requires_source_backed_evidence() -> None:
    payload = _output_payload()
    payload["experiments"][0].update(
        {
            "series_key": "split-1",
            "scope_kind": "physical_split",
            "split_reason": "different population",
            "split_evidence": [],
        }
    )

    with pytest.raises(ValueError, match="split evidence"):
        reconcile_model_output(
            PaperExperimentModelOutput.from_mapping(payload),
            accepted_experiment_keys=("split-1",),
        )


def test_split_binding_sources_are_merged_and_mark_exact_revision_bound() -> None:
    payload = _output_payload()
    test_condition = payload["experiments"][0]["test_conditions"][0]
    test_condition.update(
        {
            "method": "ASTM E8",
            "protocol_specificity": "exact",
            "protocol_completeness": "complete",
        }
    )
    for measurement in payload["experiments"][0]["measurements"]:
        measurement.update(
            {
                "variant_binding_source_labels": ["table"],
                "test_binding_source_labels": ["methods"],
            }
        )

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "bound"
    assert {
        item.source_ref for item in revision.measurements[0].binding_source_refs
    } == {"table-2", "methods-1"}
    assert revision.measurements[0].binding_status == "direct"


def test_split_evidence_and_scope_metadata_survive_revision_binding() -> None:
    payload = _output_payload()
    experiment = payload["experiments"][0]
    experiment.update(
        {
            "scope_kind": "physical_split",
            "split_reason": "different population",
            "split_evidence": [
                {"source_label": "methods"},
                {"source_label": "table"},
            ],
            "scope_selector": {"included_states": ["separate cohort"]},
        }
    )

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert {item.source_ref for item in revision.source_refs} == {
        "methods-1",
        "table-2",
    }
    boundary_issues = [
        item
        for item in revision.unresolved_issues
        if item.get("target_ref") == "experiment"
        and "boundary_scope" in item
    ]
    assert len(boundary_issues) == 1
    assert boundary_issues[0]["boundary_scope"]["scope_kind"] == "physical_split"
    assert {
        item["source_ref"] for item in boundary_issues[0]["source_refs"]
    } == {"methods-1", "table-2"}


def test_model_exact_flag_cannot_promote_broad_variant_label_to_exact_binding() -> None:
    payload = _output_payload()
    variants = payload["experiments"][0]["variants"]
    variants[0].update({
        "variant_label": "as-SLM",
        "identity_specificity": "exact",
    })
    variants[1].update({
        "variant_label": "as-SLM (120 W / 100 mm/s)",
        "identity_specificity": "exact",
        "intervention_attributes": [
            {"name": "laser power", "value": 120, "unit": "W"},
            {"name": "scan speed", "value": 100, "unit": "mm/s"},
        ],
    })
    test_condition = payload["experiments"][0]["test_conditions"][0]
    test_condition.update({
        "method": "ASTM E8",
        "protocol_specificity": "exact",
        "protocol_completeness": "complete",
    })
    for measurement in payload["experiments"][0]["measurements"]:
        measurement.update({
            "variant_binding_source_labels": ["table"],
            "test_binding_source_labels": ["methods"],
        })

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "partial"
    assert revision.measurements[0].binding_status != "direct"
    assert revision.measurements[0].measurement_scope["binding_resolution"] in {
        "ambiguous",
        "partial",
    }


def test_complete_flag_cannot_promote_generic_test_category_to_exact_binding() -> None:
    payload = _output_payload()
    test_condition = payload["experiments"][0]["test_conditions"][0]
    test_condition.update({
        "test_type": "mechanical test",
        "protocol_specificity": "exact",
        "protocol_completeness": "complete",
    })
    for measurement in payload["experiments"][0]["measurements"]:
        measurement.update({
            "variant_binding_source_labels": ["table"],
            "test_binding_source_labels": ["methods"],
        })

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "partial"
    assert all(item.binding_status != "direct" for item in revision.measurements)


def test_generic_method_label_cannot_promote_category_to_exact_binding() -> None:
    payload = _output_payload()
    test_condition = payload["experiments"][0]["test_conditions"][0]
    test_condition.update(
        {
            "test_type": "mechanical test",
            "method": "tensile",
            "protocol_specificity": "exact",
            "protocol_completeness": "complete",
        }
    )
    for measurement in payload["experiments"][0]["measurements"]:
        measurement.update(
            {
                "variant_binding_source_labels": ["table"],
                "test_binding_source_labels": ["methods"],
            }
        )

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "partial"
    assert all(item.binding_status != "direct" for item in revision.measurements)


@pytest.mark.parametrize("generic_standard", ["ASTM", "ISO"])
def test_generic_standard_label_cannot_promote_category_to_exact_binding(
    generic_standard: str,
) -> None:
    payload = _output_payload()
    test_condition = payload["experiments"][0]["test_conditions"][0]
    test_condition.update(
        {
            "test_type": "mechanical test",
            "method": "test",
            "standard": generic_standard,
            "protocol_specificity": "exact",
            "protocol_completeness": "complete",
        }
    )
    for measurement in payload["experiments"][0]["measurements"]:
        measurement.update(
            {
                "variant_binding_source_labels": ["table"],
                "test_binding_source_labels": ["methods"],
            }
        )

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "partial"
    assert all(item.binding_status != "direct" for item in revision.measurements)


def test_missing_one_binding_edge_keeps_revision_partial() -> None:
    payload = _output_payload()
    measurement = payload["experiments"][0]["measurements"][0]
    measurement["test_key"] = None
    measurement["variant_binding_source_labels"] = ["table"]
    measurement["reported_test_label"] = "mechanical test"

    revision = bind_model_output(
        _reconciled_output(payload),
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )[0]

    assert revision.binding_status == "partial"
    assert revision.measurements[0].binding_status != "direct"
    assert any(
        issue["target_ref"] == "measurements/np-elongation"
        for issue in revision.unresolved_issues
    )


def test_scope_selector_can_resolve_against_parent_facts_without_repeating_members() -> None:
    payload = _output_payload()
    parent = payload["experiments"][0]
    parent["series_key"] = "parent"
    selected = {
        "series_key": "selected-p150",
        "scope_kind": "selected_stratum",
        "parent_series_key": "parent",
        "scope_selector": {
            "selected_levels": [{"name": "preheat", "value": 150, "unit": "C"}]
        },
        "source_labels": ["table"],
    }
    payload["experiments"] = [parent, selected]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent", "selected-p150"),
    )

    assert len(reconciled.output.experiments) == 1
    assert any("overlapping scope" in str(item.get("description")) for item in reconciled.audit_issues)


def test_missing_parent_gets_a_synthetic_parent_without_losing_scope_selector() -> None:
    payload = _output_payload()
    first = payload["experiments"][0]
    first.update(
        {
            "series_key": "selected-p150",
            "scope_kind": "selected_stratum",
            "parent_series_key": "synthetic-parent",
            "scope_selector": {
                "selected_levels": [{"name": "preheat", "value": 150, "unit": "C"}]
            },
        }
    )
    second = deepcopy(first)
    second["series_key"] = "follow-up"
    second["scope_kind"] = "follow_up"
    second["scope_selector"] = {"test_scope_labels": ["tensile"]}
    payload["experiments"] = [first, second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("synthetic-parent",),
    )

    parent = reconciled.output.experiments[0].payload
    assert parent.get("synthetic_parent") is True
    assert len(parent.get("scope_views") or ()) == 2


def test_boundary_merge_keeps_conflicting_measurement_reports() -> None:
    payload = _output_payload()
    parent = payload["experiments"][0]
    parent["series_key"] = "parent"
    second = deepcopy(parent)
    second["series_key"] = "results-section"
    second["measurements"][0]["value"] = 75
    second["measurements"][0]["source_labels"] = ["table"]
    payload["experiments"] = [parent, second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent",),
    )

    measurements = reconciled.output.experiments[0].payload["measurements"]
    assert {item["value"] for item in measurements if item["outcome"] == "elongation"} >= {72, 75}
    assert any("conflict" in str(item.get("description")) for item in reconciled.audit_issues)


def test_multiple_explicit_parents_are_retained_until_boundary_reconciliation() -> None:
    payload = _output_payload()
    first = payload["experiments"][0]
    first["series_key"] = "parent-a"
    first["scope_kind"] = "parent"
    second = deepcopy(first)
    second["series_key"] = "parent-b"
    second["label"] = "Independent second series"
    payload["experiments"] = [first, second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent-a", "parent-b"),
    )

    assert reconciled.accepted_experiment_keys == ("parent-a", "parent-b")
    assert [
        item.payload.get("series_key") for item in reconciled.output.experiments
    ] == ["parent-a", "parent-b"]
    assert any(
        "Multiple explicit parent experiment scopes" in str(item.get("description"))
        for item in reconciled.audit_issues
    )


def test_boundary_reconciliation_maps_retained_split_to_its_own_accepted_key() -> None:
    payload = _output_payload()
    parent = payload["experiments"][0]
    parent["series_key"] = "parent"
    selected = deepcopy(parent)
    selected.update(
        {
            "series_key": "selected-p150",
            "scope_kind": "selected_stratum",
            "parent_series_key": "parent",
            "scope_selector": {
                "selected_levels": [{"name": "preheat", "value": 150, "unit": "C"}]
            },
            "source_labels": ["table"],
        }
    )
    physical = deepcopy(parent)
    physical.update(
        {
            "series_key": "physical-followup",
            "scope_kind": "physical_split",
            "split_reason": "different population",
            "split_evidence": [{"source_label": "methods"}],
            "source_labels": ["methods"],
        }
    )
    payload["experiments"] = [parent, selected, physical]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("parent", "selected-p150", "physical-followup"),
    )

    assert len(reconciled.output.experiments) == 2
    assert reconciled.accepted_experiment_keys == ("parent", "physical-followup")
    assert [
        item.payload.get("series_key") for item in reconciled.output.experiments
    ] == ["parent", "physical-followup"]


def test_all_physical_splits_are_retained_without_synthesizing_a_parent() -> None:
    payload = _output_payload()
    first = payload["experiments"][0]
    first.update(
        {
            "series_key": "physical-1",
            "scope_kind": "physical_split",
            "split_reason": "different population",
            "split_evidence": [{"source_label": "methods"}],
            "source_labels": ["methods"],
        }
    )
    second = deepcopy(first)
    second.update(
        {
            "series_key": "physical-2",
            "split_evidence": [{"source_label": "table"}],
            "source_labels": ["table"],
        }
    )
    payload["experiments"] = [first, second]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("physical-1", "physical-2"),
    )

    assert reconciled.accepted_experiment_keys == ("physical-1", "physical-2")
    assert [
        item.payload.get("series_key") for item in reconciled.output.experiments
    ] == ["physical-1", "physical-2"]
    assert all(
        item.payload.get("scope_kind") == "physical_split"
        and item.payload.get("synthetic_parent") is not True
        for item in reconciled.output.experiments
    )
    assert [
        item.payload.get("split_evidence") for item in reconciled.output.experiments
    ] == [
        [{"source_label": "methods"}],
        [{"source_label": "table"}],
    ]


def test_physical_split_before_missing_parent_scope_is_not_promoted_to_parent() -> None:
    payload = _output_payload()
    physical = payload["experiments"][0]
    physical.update(
        {
            "series_key": "physical-follow-up",
            "scope_kind": "physical_split",
            "split_reason": "different population",
            "split_evidence": [{"source_label": "methods"}],
            "source_labels": ["methods"],
        }
    )
    selected = {
        "series_key": "selected-p150",
        "scope_kind": "selected_stratum",
        "parent_series_key": "synthetic-parent",
        "scope_selector": {
            "selected_levels": [{"name": "preheat", "value": 150, "unit": "C"}]
        },
        "source_labels": ["table"],
    }
    payload["experiments"] = [physical, selected]

    reconciled = reconcile_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        accepted_experiment_keys=("physical-follow-up", "synthetic-parent"),
    )

    assert reconciled.accepted_experiment_keys == (
        "synthetic-parent",
        "physical-follow-up",
    )
    assert [
        item.payload.get("series_key") for item in reconciled.output.experiments
    ] == ["synthetic-parent", "physical-follow-up"]
    parent, retained_split = reconciled.output.experiments
    assert parent.payload.get("synthetic_parent") is True
    assert retained_split.payload.get("scope_kind") == "physical_split"
    assert retained_split.payload.get("split_reason") == "different population"


def test_prepare_model_output_generates_local_series_key_when_model_omits_it() -> None:
    payload = _output_payload()

    payload["experiments"][0].pop("series_key", None)
    prepared = prepare_model_output(
        PaperExperimentModelOutput.from_mapping(payload),
        objective=ResearchObjective.from_mapping(
            {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "question": "Does preheating affect elongation?",
                "material_scope": ["316L"],
                "variables": ["preheating"],
                "outcomes": ["elongation"],
                "confidence": 1.0,
            }
        ),
    )

    assert prepared.output.experiments[0].payload["series_key"].startswith("draft_")


def test_readiness_is_an_application_value_not_a_model_field() -> None:
    readiness = DraftReadiness(
        ready=False,
        missing_context=("test protocol is incomplete",),
        reason_codes=("unresolved_context",),
    )

    assert not readiness.ready
    assert readiness.selected_measurement_keys == ()

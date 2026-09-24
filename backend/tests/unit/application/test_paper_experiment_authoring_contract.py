from __future__ import annotations

import pytest

from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentModelOutput,
    bind_model_output,
)


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
                        "source_labels": ["methods"],
                    },
                    {
                        "variant_key": "p150",
                        "variant_label": "P150",
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


def test_model_output_binds_sources_and_service_identity() -> None:
    output = PaperExperimentModelOutput.from_mapping(_output_payload())

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


def test_raw_model_payload_gets_context_and_source_catalog_from_service() -> None:
    envelope = PaperExperimentModelOutput.from_model_mapping(
        _raw_model_payload(),
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_labels=_output_payload()["source_labels"],
    )

    revisions = bind_model_output(
        envelope,
        experiment_ids=["exp-1"],
        experiment_versions=[1],
        document_id="doc-1",
        source_fingerprint="prep-1",
    )

    assert revisions[0].measurements[0].source_refs[0].source_ref == "table-2"


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
    output = PaperExperimentModelOutput.from_mapping(payload)

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
        output,
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

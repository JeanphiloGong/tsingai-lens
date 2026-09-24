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
                "identity_status": "identified",
                "binding_status": "bound",
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
                        "binding_status": "direct",
                    },
                    {
                        "measurement_key": "p150-elongation",
                        "outcome": "elongation",
                        "variant_key": "p150",
                        "test_key": "tensile",
                        "value": 82,
                        "unit": "%",
                        "source_labels": ["table"],
                        "binding_status": "direct",
                    },
                ],
            }
        ],
    }


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


def test_model_cannot_supply_formal_identity() -> None:
    payload = _output_payload()
    payload["experiments"][0]["experiment_id"] = "model-made-id"

    with pytest.raises(ValueError, match="formal identity"):
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

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from application.core.objectives.analysis.paper_experiment_extraction import (
    ExtractionBudget,
    PaperExperimentDraftEnvelope,
    PaperExperimentExtractor,
    PaperExperimentSourceBundle,
    PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION,
    _prompt,
    build_bundle_from_routes,
    build_source_bundle,
)
from domain.core.research_objective import ResearchObjective


class FakeStructuredResponseClient:
    model = "fake-model"

    def __init__(self, responses: list[dict | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[PaperExperimentDraftEnvelope],
        **options: object,
    ) -> PaperExperimentDraftEnvelope:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
                "options": options,
            }
        )
        if not self.responses:
            raise AssertionError("fake provider received an unexpected call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response_model.model_validate(response)


def _objective(*, outcome: str = "elongation") -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "Does preheating change elongation?",
            "material_scope": ["316L"],
            "variables": ["preheating"],
            "outcomes": [outcome],
            "seed_document_ids": ["document-1"],
            "confidence": 1.0,
        }
    )


def _bundle(*, omitted: tuple[str, ...] = ()) -> PaperExperimentSourceBundle:
    built = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(
            {
                "source_kind": "text_window",
                "source_ref": "methods-1",
                "text": (
                    "NP and P150 were tested under ASTM E8/E8M; P150 denotes "
                    "150 C preheating."
                ),
            },
            {
                "source_kind": "table",
                "source_ref": "table-2",
                "caption_text": "Reported elongation",
                "column_headers": ["variant", "elongation (%)"],
                "header_row_count": 1,
                "table_matrix": [
                    ["variant", "elongation (%)"],
                    ["NP", "72"],
                    ["P150", "82"],
                ],
                "table_markdown": (
                    "| variant | elongation (%) |\n"
                    "| --- | --- |\n| NP | 72 |\n| P150 | 82 |"
                ),
            },
        ),
    )
    return PaperExperimentSourceBundle(
        document_id=built.document_id,
        source_fingerprint=built.source_fingerprint,
        prompt_sources=built.prompt_sources,
        source_catalog=built.source_catalog,
        omitted_source_refs=omitted,
    )


def test_source_bundle_preserves_scientific_sample_and_batch_ids() -> None:
    bundle = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(
            {
                "source_kind": "table",
                "source_ref": "table-1",
                "quote": "Sample S-01 from batch B-7 measured 72%.",
                "sample_id": "S-01",
                "batch_id": "B-7",
                "document_id": "document-1",
            },
        ),
    )

    assert bundle.prompt_sources[0]["sample_id"] == "S-01"
    assert bundle.prompt_sources[0]["batch_id"] == "B-7"
    assert "document_id" not in bundle.prompt_sources[0]


def test_draft_prompt_exposes_task_schema_process_and_boundary_cases() -> None:
    system_prompt, user_prompt = _prompt(
        objective=_objective(),
        bundle=_bundle(),
        strategy="focused-single-pass",
    )

    for section in (
        "TASK MODEL",
        "INPUT SCHEMA",
        "DECISION PROCESS",
        "HARD RULES",
        "BOUNDARY EXAMPLES",
        "OUTPUT SCHEMA",
    ):
        assert section in system_prompt
    assert "stimulus_id" in system_prompt
    assert "measurement_scope.reported_identifiers" in system_prompt
    payload = json.loads(user_prompt)
    assert payload["draft_schema"]["experiments"][0]["series_key"]
    assert "population_scope" in payload["draft_schema"]["experiments"][0][
        "experimental_variants"
    ][0]
    assert payload["draft_schema_note"].startswith("The draft_schema values")
    assert "unknown" in payload["allowed_scope_kinds"]
    assert "source_labels" in payload["required_top_level_keys"]


def test_draft_prompt_treats_binding_as_optional_when_scope_is_broad() -> None:
    system_prompt, user_prompt = _prompt(
        objective=_objective(),
        bundle=_bundle(),
        strategy="focused-single-pass",
    )

    payload = json.loads(user_prompt)
    experiment_schema = payload["draft_schema"]["experiments"][0]
    measurement_schema = experiment_schema["measurements"][0]
    variant_schema = experiment_schema["experimental_variants"][0]
    test_schema = experiment_schema["test_conditions"][0]

    assert measurement_schema["variant_key"] is None
    assert measurement_schema["test_key"] is None
    assert "reported_sample_label" in measurement_schema
    assert "reported_test_label" in measurement_schema
    assert "candidate_variant_keys" in measurement_schema
    assert "candidate_test_keys" in measurement_schema
    assert variant_schema["variant_key"] is None
    assert test_schema["test_key"] is None
    assert "may be null" in system_prompt
    assert "one experiment per table or outcome" in system_prompt
    assert "retain both observations" in system_prompt


def test_draft_envelope_schema_describes_open_scientific_payload_without_new_ids() -> None:
    schema = PaperExperimentDraftEnvelope.model_json_schema()

    assert schema["additionalProperties"] is False
    assert "response-local" in schema["properties"]["experiments"]["description"]
    assert "supplied Sxxx" in schema["properties"]["source_labels"]["description"]
    # Scientific fields stay open-ended; formal identity is rejected later by
    # PaperExperimentModelOutput rather than silently manufactured here.
    assert schema["properties"]["experiments"]["items"]["additionalProperties"] is True


def test_source_bundle_preserves_plural_scientific_identifiers() -> None:
    bundle = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(
            {
                "source_kind": "table",
                "source_ref": "table-1",
                "quote": "Specimens S-01 and S-02 came from batches B-7 and B-8.",
                "sample_ids": ["S-01", "S-02"],
                "batch_ids": ["B-7", "B-8"],
                "document_id": "document-1",
            },
        ),
    )

    assert bundle.prompt_sources[0]["sample_ids"] == ["S-01", "S-02"]
    assert bundle.prompt_sources[0]["batch_ids"] == ["B-7", "B-8"]
    assert "document_id" not in bundle.prompt_sources[0]


def test_source_bundle_preserves_domain_identifiers_in_scope_maps() -> None:
    bundle = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(
            {
                "source_kind": "table",
                "source_ref": "table-psych-1",
                "quote": "Condition dual-task used stimulus face-set-3.",
                "population_scope": {
                    "reported_identifiers": {
                        "stimulus_id": "face-set-3",
                        "condition_id": "dual-task",
                    }
                },
                "measurement_scope": {
                    "reported_identifiers": {"task_id": "reaction-time-1"}
                },
                "service_row_id": "internal-row-1",
            },
        ),
    )

    prompt_source = bundle.prompt_sources[0]
    assert prompt_source["population_scope"]["reported_identifiers"] == {
        "stimulus_id": "face-set-3",
        "condition_id": "dual-task",
    }
    assert prompt_source["measurement_scope"]["reported_identifiers"] == {
        "task_id": "reaction-time-1",
    }
    assert "service_row_id" not in prompt_source


def test_route_bundle_excludes_non_extractable_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.core.objectives.analysis import source_extraction

    monkeypatch.setattr(
        source_extraction,
        "build_route_source_payload",
        lambda **kwargs: {
            "source_kind": kwargs["route"].source_kind,
            "source_ref": kwargs["route"].source_ref,
            "text": kwargs["route"].source_ref,
        },
    )
    routes = (
        type(
            "Route",
            (),
            {
                "document_id": "document-1",
                "source_kind": "block",
                "source_ref": "results-1",
                "extractable": True,
            },
        )(),
        type(
            "Route",
            (),
            {
                "document_id": "document-1",
                "source_kind": "block",
                "source_ref": "background-1",
                "extractable": False,
            },
        )(),
    )

    bundle = build_bundle_from_routes(
        document_id="document-1",
        source_fingerprint="prepared-1",
        routes=routes,
        blocks=[],
        tables=[],
        figures=[],
        document_tree=None,
        table_cells=[],
    )

    assert tuple(
        (item["source_kind"], item["source_ref"])
        for item in bundle.source_catalog.values()
    ) == (("block", "results-1"),)
    assert len(bundle.prompt_sources) == 1


def _ready_payload(*, outcome: str = "elongation") -> dict:
    return {
        "source_labels": ["S001", "S002"],
        "experiments": [
            {
                "series_key": "series-1",
                "label": "NP and P150 tensile series",
                "scope_description": "Two preheating conditions under one tensile protocol.",
                "design_type": "parallel",
                "scope_kind": "parent",
                "parent_series_key": None,
                "split_evidence": [],
                "experimental_variants": [
                    {
                        "variant_key": "variant-np",
                        "variant_label": "NP",
                        "identity_specificity": "exact",
                        "intervention_attributes": [
                            {"name": "preheating", "value": "none"}
                        ],
                        "source_labels": ["S001"],
                        "binding_source_labels": ["S001"],
                    },
                    {
                        "variant_key": "variant-p150",
                        "variant_label": "P150",
                        "identity_specificity": "exact",
                        "intervention_attributes": [
                            {"name": "preheating", "value": 150, "unit": "C"}
                        ],
                        "source_labels": ["S001"],
                        "binding_source_labels": ["S001"],
                    },
                ],
                "test_conditions": [
                    {
                        "test_key": "test-tensile",
                        "test_type": "tensile test",
                        "method": "uniaxial tensile test",
                        "standard": "ASTM E8/E8M",
                        "protocol_specificity": "exact",
                        "test_identity_status": "identified",
                        "protocol_completeness": "complete",
                        "outcome_scope": [outcome],
                        "source_labels": ["S001"],
                        "binding_source_labels": ["S001"],
                    }
                ],
                "measurements": [
                    {
                        "measurement_key": "measurement-np",
                        "variant_key": "variant-np",
                        "test_key": "test-tensile",
                        "outcome": outcome,
                        "value": 72,
                        "unit": "%",
                        "source_labels": ["S002"],
                        "variant_binding_source_labels": ["S002"],
                        "test_binding_source_labels": ["S001"],
                    },
                    {
                        "measurement_key": "measurement-p150",
                        "variant_key": "variant-p150",
                        "test_key": "test-tensile",
                        "outcome": outcome,
                        "value": 82,
                        "unit": "%",
                        "source_labels": ["S002"],
                        "variant_binding_source_labels": ["S002"],
                        "test_binding_source_labels": ["S001"],
                    },
                ],
                "comparisons": [
                    {
                        "comparison_key": "comparison-preheat",
                        "outcome": outcome,
                        "baseline_variant_key": "variant-np",
                        "target_variant_key": "variant-p150",
                        "baseline_measurement_keys": ["measurement-np"],
                        "target_measurement_keys": ["measurement-p150"],
                        "changed_variables": [{"name": "preheating"}],
                        "matched_conditions": [],
                        "source_labels": ["S002"],
                        "binding_source_labels": ["S002"],
                    }
                ],
                "reported_interpretations": [],
                "source_labels": ["S001", "S002"],
                "unresolved_issues": [],
            }
        ],
        "unresolved_issues": [],
    }


def _extract_once(payload: dict, *, bundle: PaperExperimentSourceBundle | None = None):
    return PaperExperimentExtractor(
        FakeStructuredResponseClient([payload]),
        budget=ExtractionBudget(max_calls=1),
    ).extract(objective=_objective(), bundle=bundle or _bundle())


def test_source_bundle_hides_service_ids_but_keeps_authoritative_catalog() -> None:
    bundle = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(
            {
                "source_kind": "table",
                "source_ref": "table-2",
                "document_id": "document-1",
                "table_cells": [
                    {
                        "cell_id": "cell-1",
                        "table_id": "table-2",
                        "row_index": 1,
                        "cell_text": "72",
                    }
                ],
                "table_markdown": "| variant | elongation |\n| NP | 72 |",
            },
        ),
    )

    serialized = json.dumps(bundle.prompt_sources)
    assert "document_id" not in serialized
    assert "source_ref" not in serialized
    assert "cell_id" not in serialized
    assert "table_id" not in serialized
    assert bundle.prompt_sources[0]["source_label"] == "S001"
    assert bundle.source_catalog["S001"]["source_ref"] == "table-2"


def test_ready_draft_uses_one_call_and_keeps_only_local_keys() -> None:
    client = FakeStructuredResponseClient([_ready_payload()])

    result = PaperExperimentExtractor(client).extract(
        objective=_objective(),
        bundle=_bundle(),
    )

    assert result.status == "ready"
    assert result.readiness is not None and result.readiness.ready
    assert len(client.calls) == 1
    assert result.output is not None
    assert "experiment_id" not in result.output.output.experiments[0].payload
    assert (
        client.calls[0]["options"]["prompt_version"]
        == PAPER_EXPERIMENT_DRAFT_PROMPT_VERSION
    )


def test_valid_multiple_experiments_keep_distinct_local_series() -> None:
    payload = _ready_payload()
    second = deepcopy(payload["experiments"][0])
    second["series_key"] = "series-2"
    second["label"] = "Independent follow-up population"
    second["scope_kind"] = "physical_split"
    second["split_reason"] = "different population and intervention assignment"
    second["split_evidence"] = [{"source_label": "S001"}]
    second["source_labels"] = ["S001"]
    for collection in (
        second["experimental_variants"],
        second["test_conditions"],
        second["measurements"],
        second["comparisons"],
    ):
        for item in collection:
            for key in tuple(item):
                if key.endswith("_key") and isinstance(item[key], str):
                    item[key] += "-follow-up"
                elif key.endswith("_keys") and isinstance(item[key], list):
                    item[key] = [f"{value}-follow-up" for value in item[key]]
    payload["experiments"].append(second)

    result = _extract_once(payload)

    assert result.output is not None
    assert result.output.accepted_experiment_keys == ("series-1", "series-2")


def test_insufficient_first_pass_uses_targeted_repair() -> None:
    incomplete = _ready_payload()
    incomplete["experiments"][0]["comparisons"] = []
    client = FakeStructuredResponseClient([incomplete, _ready_payload()])

    result = PaperExperimentExtractor(client).extract(
        objective=_objective(),
        bundle=_bundle(),
    )

    assert result.status == "ready"
    assert len(client.calls) == 2
    second_prompt = json.loads(str(client.calls[1]["user_prompt"]))
    assert second_prompt["previous_candidate"] == incomplete
    assert any("comparison" in item for item in second_prompt["missing_context"])


def test_valid_but_incomplete_draft_becomes_partial_archive() -> None:
    incomplete = _ready_payload()
    incomplete["experiments"][0]["comparisons"] = []

    result = PaperExperimentExtractor(
        FakeStructuredResponseClient([incomplete]),
        budget=ExtractionBudget(max_calls=1),
    ).extract(objective=_objective(), bundle=_bundle())

    assert result.status == "partial_archive"
    assert result.output is not None
    assert result.readiness is not None and not result.readiness.ready


def test_zero_experiments_is_scientific_abstention() -> None:
    result = _extract_once({"experiments": [], "source_labels": []})

    assert result.status == "abstained"
    assert result.output is None
    assert result.attempts[0].status == "insufficient"


def test_empty_source_bundle_abstains_without_calling_provider() -> None:
    client = FakeStructuredResponseClient([])
    bundle = build_source_bundle(
        document_id="document-1",
        source_fingerprint="prepared-1",
        source_payloads=(),
    )

    result = PaperExperimentExtractor(client).extract(
        objective=_objective(),
        bundle=bundle,
    )

    assert result.status == "abstained"
    assert result.output is None
    assert result.attempts == ()
    assert result.diagnostics == ("no_readable_sources",)
    assert client.calls == []


def test_provider_failure_without_draft_is_technical_failure() -> None:
    client = FakeStructuredResponseClient([RuntimeError("quota")])

    result = PaperExperimentExtractor(client).extract(
        objective=_objective(),
        bundle=_bundle(),
    )

    assert result.status == "technical_failure"
    assert result.output is None
    assert result.attempts[0].status == "technical_failure"
    assert "quota" not in " ".join(result.diagnostics)


def test_provider_failure_after_partial_keeps_archiveable_draft() -> None:
    incomplete = _ready_payload()
    incomplete["experiments"][0]["comparisons"] = []

    result = PaperExperimentExtractor(
        FakeStructuredResponseClient([incomplete, TimeoutError("provider timeout")]),
        budget=ExtractionBudget(max_calls=2),
    ).extract(objective=_objective(), bundle=_bundle())

    assert result.status == "partial_archive"
    assert result.output is not None
    assert "technical_failure_after_partial" in result.diagnostics


def test_completion_budget_stops_before_a_second_provider_call() -> None:
    incomplete = _ready_payload()
    incomplete["experiments"][0]["comparisons"] = []
    client = FakeStructuredResponseClient([incomplete, _ready_payload()])

    result = PaperExperimentExtractor(
        client,
        budget=ExtractionBudget(
            max_calls=2,
            max_completion_tokens_per_call=4,
            max_total_completion_tokens=4,
        ),
    ).extract(objective=_objective(), bundle=_bundle())

    assert result.status == "partial_archive"
    assert len(client.calls) == 1
    assert "completion_token_budget_exhausted" in result.diagnostics


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_source_label",
        "formal_id",
        "final_status",
        "duplicate_variant_key",
        "dangling_variant_key",
        "dangling_test_key",
        "dangling_comparison_measurement",
    ],
)
def test_boundary_violations_are_rejected(mutation: str) -> None:
    payload = _ready_payload()
    experiment = payload["experiments"][0]
    if mutation == "unknown_source_label":
        experiment["measurements"][0]["source_labels"] = ["S999"]
    elif mutation == "formal_id":
        experiment["measurements"][0]["measurement_id"] = "database-id"
    elif mutation == "final_status":
        experiment["status"] = "ready"
    elif mutation == "duplicate_variant_key":
        experiment["experimental_variants"][1]["variant_key"] = "variant-np"
    elif mutation == "dangling_variant_key":
        experiment["measurements"][0]["variant_key"] = "missing-variant"
    elif mutation == "dangling_test_key":
        experiment["measurements"][0]["test_key"] = "missing-test"
    else:
        experiment["comparisons"][0]["baseline_measurement_keys"] = [
            "missing-measurement"
        ]

    result = _extract_once(payload)

    assert result.status == "abstained"
    assert result.output is None
    assert result.attempts[0].status == "rejected"


def test_conflicting_reports_are_retained_and_block_comparison_direction() -> None:
    payload = _ready_payload()
    conflicting = deepcopy(payload["experiments"][0]["measurements"][0])
    conflicting["value"] = 74
    conflicting["source_labels"] = ["S001"]
    payload["experiments"][0]["measurements"].append(conflicting)

    result = _extract_once(payload)

    assert result.output is not None
    experiment = result.output.output.experiments[0].payload
    measurements = experiment["measurements"]
    assert len(measurements) == 3
    assert any(
        item["measurement_key"].startswith("measurement-np__conflict_")
        for item in measurements
    )
    assert experiment["comparisons"][0]["direction_candidate"] == "unknown"
    assert result.status == "partial_archive"


def test_repeated_measurements_are_not_implicitly_averaged() -> None:
    payload = _ready_payload()
    repeated = deepcopy(payload["experiments"][0]["measurements"][0])
    repeated["measurement_key"] = "measurement-np-repeat"
    payload["experiments"][0]["measurements"].append(repeated)
    payload["experiments"][0]["comparisons"][0][
        "baseline_measurement_keys"
    ].append("measurement-np-repeat")

    result = _extract_once(payload)

    assert result.output is not None
    comparison = result.output.output.experiments[0].payload["comparisons"][0]
    assert comparison["direction_candidate"] == "unknown"
    assert result.status == "partial_archive"


def test_numeric_zero_is_not_treated_as_missing() -> None:
    payload = _ready_payload()
    payload["experiments"][0]["measurements"][0]["value"] = 0

    result = _extract_once(payload)

    assert result.status == "ready"
    comparison = result.output.output.experiments[0].payload["comparisons"][0]
    assert comparison["direction_candidate"] == "increase"


def test_non_ascii_outcome_can_pass_readiness() -> None:
    payload = _ready_payload(outcome="延伸率")
    client = FakeStructuredResponseClient([payload])

    result = PaperExperimentExtractor(
        client,
        budget=ExtractionBudget(max_calls=1),
    ).extract(objective=_objective(outcome="延伸率"), bundle=_bundle())

    assert result.status == "ready"


def test_omitted_source_context_prevents_ready_status() -> None:
    result = _extract_once(_ready_payload(), bundle=_bundle(omitted=("methods-2",)))

    assert result.status == "partial_archive"
    assert result.readiness is not None
    assert any("omitted" in item for item in result.readiness.missing_context)

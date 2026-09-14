from __future__ import annotations

from application.core.objectives.analysis.paper_experiment import (
    assemble_paper_experiment,
)
from application.core.objectives.analysis.evidence_materialization import (
    _merge_domain_experiment_inputs,
)
from application.core.objectives.analysis.source_extraction import (
    SourceObservation,
)


def test_assembly_keeps_source_result_and_marks_missing_conditions_incomplete() -> None:
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "ev-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "evidence_role": "direct_result",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-2",
                    "source_excerpt": "Elongation: 82%",
                }
            ],
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation was 82%.",
            },
            "scientific_context": {},
            "confidence": 0.9,
        }
    )

    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(draft,),
    )

    assert experiment.status == "incomplete"
    assert experiment.has_measurements
    assert not experiment.is_ready_for_comparison
    assert "Test conditions remain unresolved" in experiment.uncertainties[0]
    assert experiment.source_observations[0].status == "validated"


def test_materialization_reads_source_facts_from_experiment_first() -> None:
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "ev-2",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "text_window",
            "source_ref": "block-2",
            "evidence_role": "condition_context",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-2",
                    "source_excerpt": "The tensile test used room temperature.",
                    "page": 4,
                }
            ],
            "scientific_context": {
                "test": [{"name": "temperature", "value": 25, "unit": "C"}]
            },
            "confidence": 0.8,
        }
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(draft,),
    )

    merged = _merge_domain_experiment_inputs(
        paper_experiment=experiment,
        drafts=(draft,),
    )

    assert len(merged) == 1
    assert merged[0].source_refs[0]["page"] == 4
    assert merged[0].scientific_context.test[0].name == "temperature"

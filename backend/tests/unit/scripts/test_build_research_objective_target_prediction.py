from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_projection_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "build_research_objective_target_prediction.py"
    )
    spec = importlib.util.spec_from_file_location(
        "build_research_objective_target_prediction",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_target_prediction_projects_bundle_scope_and_contributions() -> None:
    projection = _load_projection_module()

    prediction = projection.build_target_prediction_from_bundle(_prediction_bundle())

    assert prediction["evidence_scope"] == {
        "paper_count": 1,
        "sample_count": 2,
        "test_condition_count": 1,
        "measurement_count": 2,
        "comparison_count": 1,
        "observation_count": 1,
        "uncertainty_count": 1,
    }
    assert prediction["paper_contributions"] == [
        {
            "paper_id": "P001",
            "role": "prediction_bundle_paper",
            "summary": (
                "P001: Energy input study. Goal: Study energy input. "
                "Variables: energy density. Properties: density; strength. "
                "Samples: 2. Measurements: density, yield strength."
            ),
        }
    ]


def test_build_target_prediction_preserves_comparisons_and_limits() -> None:
    projection = _load_projection_module()

    prediction = projection.build_target_prediction_from_bundle(_prediction_bundle())

    assert prediction["controlled_comparisons"] == [
        {
            "paper_id": "P001",
            "comparison_id": "C001",
            "summary": (
                "P001 C001: S002 vs S001 for density. "
                "99 % vs 95 %. Direction: improved. "
                "Notes: Higher density sample performs better."
            ),
        }
    ]
    assert prediction["mechanism_chains"] == [
        {
            "paper_id": "P001",
            "observation_id": "O001",
            "path": (
                "SEM observes pores: fewer pores. "
                "Interpretation: Energy input reduces pores."
            ),
        }
    ]
    assert prediction["limitations"] == [
        "P001 U001: density method limitation. Impact: avoid over-comparison."
    ]


def test_build_target_prediction_aligns_paper_ids_to_target_contributions() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()
    bundle["papers"][0]["paper_id"] = "doc-energy"
    for family in ("samples", "measurement_results"):
        for row in bundle[family]:
            row["paper_id"] = "doc-energy"

    prediction = projection.build_target_prediction_from_bundle(
        bundle,
        target={
            "required_paper_contributions": [
                {
                    "paper_id": "P777",
                    "required_terms": ["energy density", "yield strength"],
                }
            ]
        },
    )

    assert prediction["paper_contributions"] == [
        {
            "paper_id": "P777",
            "role": "prediction_bundle_paper",
            "summary": (
                "P777: Energy input study. Goal: Study energy input. "
                "Variables: energy density. Properties: density; strength. "
                "Samples: 2. Measurements: density, yield strength."
            ),
            "source_paper_id": "doc-energy",
        }
    ]


def test_build_target_prediction_uses_target_objective_context() -> None:
    projection = _load_projection_module()

    prediction = projection.build_target_prediction_from_bundle(
        _prediction_bundle(),
        target={
            "objective": {
                "question": (
                    "How do LPBF process parameters and thermal history "
                    "affect 316L texture?"
                ),
                "material_scope": ["316L stainless steel"],
                "process_scope": ["LPBF"],
                "property_scope": ["texture"],
            }
        },
    )

    assert prediction["objective"] == {
        "question": (
            "How do LPBF process parameters and thermal history "
            "affect 316L texture?"
        ),
        "material_scope": ["316L stainless steel"],
        "process_scope": ["LPBF"],
        "property_scope": ["texture"],
    }
    assert "thermal history" in prediction["collection_conclusion"]["summary"]


def test_build_target_prediction_exposes_measurement_summaries() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["measurement_results"] == [
        {
            "paper_id": "P001",
            "result_id": "R001",
            "sample_id": "S001",
            "metric_name": "density",
            "value": "95%",
            "summary": "P001 R001: S001 density = 95%.",
        },
        {
            "paper_id": "P001",
            "result_id": "R002",
            "sample_id": "S002",
            "metric_name": "yield strength",
            "value": "450 MPa",
            "summary": "P001 R002: S002 yield strength = 450 MPa.",
        },
    ]


def test_build_target_prediction_adds_measurement_value_aliases() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()
    bundle["measurement_results"] = [
        {
            "paper_id": "P001",
            "result_id": "R003",
            "sample_id": "S003",
            "metric_name": "total elongation [%]",
            "value_or_trend": "48.3 +/- 3.2",
            "unit": "",
        },
        {
            "paper_id": "P001",
            "result_id": "R004",
            "sample_id": "S004",
            "metric_name": "passive film resistance",
            "value_or_trend": "1.90x10 5 ohm cm 2",
            "unit": "",
        },
        {
            "paper_id": "P001",
            "result_id": "R005",
            "sample_id": "S005",
            "metric_name": "passive film resistance",
            "value_or_trend": 1.9,
            "unit": "\u03a9 cm 2",
            "value_payload": {
                "pitting_potential": "1.90\u00d710 5 \u03a9 cm 2",
                "value": 1.9,
            },
        },
        {
            "paper_id": "P001",
            "result_id": "R006",
            "sample_id": "S006",
            "metric_name": "el%",
            "value_or_trend": "72",
            "unit": "",
        },
        {
            "paper_id": "P001",
            "result_id": "R007",
            "sample_id": "S007",
            "metric_name": "yield strength",
            "value_or_trend": "321.7 ( ± 3.3)",
            "unit": "MPa",
        },
    ]

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["measurement_results"] == [
        {
            "paper_id": "P001",
            "result_id": "R003",
            "sample_id": "S003",
            "metric_name": "total elongation [%]",
            "value": "48.3 +/- 3.2",
            "summary": (
                "P001 R003: S003 total elongation [%] = 48.3 +/- 3.2. "
                "Aliases: 48.3%."
            ),
            "value_aliases": ["48.3%"],
        },
        {
            "paper_id": "P001",
            "result_id": "R004",
            "sample_id": "S004",
            "metric_name": "passive film resistance",
            "value": "1.90x10 5 ohm cm 2",
            "summary": (
                "P001 R004: S004 passive film resistance = "
                "1.90x10 5 ohm cm 2. Aliases: 1.90e5 ohm cm2."
            ),
            "value_aliases": ["1.90e5 ohm cm2"],
        },
        {
            "paper_id": "P001",
            "result_id": "R005",
            "sample_id": "S005",
            "metric_name": "passive film resistance",
            "value": "1.9 \u03a9 cm 2",
            "summary": (
                "P001 R005: S005 passive film resistance = "
                "1.9 \u03a9 cm 2. Aliases: 1.90e5 ohm cm2."
            ),
            "value_aliases": ["1.90e5 ohm cm2"],
        },
        {
            "paper_id": "P001",
            "result_id": "R006",
            "sample_id": "S006",
            "metric_name": "el%",
            "value": "72",
            "summary": "P001 R006: S006 el% = 72. Aliases: 72%.",
            "value_aliases": ["72%"],
        },
        {
            "paper_id": "P001",
            "result_id": "R007",
            "sample_id": "S007",
            "metric_name": "yield strength",
            "value": "321.7 ( ± 3.3) MPa",
            "summary": (
                "P001 R007: S007 yield strength = 321.7 ( ± 3.3) MPa. "
                "Aliases: 321.7 MPa."
            ),
            "value_aliases": ["321.7 MPa"],
        },
    ]


def test_build_target_prediction_projects_logic_chain_mechanisms() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()
    bundle["observations"] = []
    bundle["objective_logic_chains"] = [
        {
            "logic_chain_id": "LC001",
            "objective_id": "OBJ001",
            "question": "How does energy input affect pores and strength?",
            "evidence_unit_ids": ["U001", "U002", "U003"],
            "chain_payload": {
                "paper_chains": [
                    {
                        "document_id": "P001",
                        "sample_and_process_contexts": [
                            {
                                "evidence_unit_id": "U001",
                                "sample_context": {"sample": "S014"},
                                "process_context": {
                                    "process": "SLM",
                                    "energy input": "high",
                                },
                            }
                        ],
                        "characterization_observations": [
                            {
                                "evidence_unit_id": "U002",
                                "property_normalized": "porosity",
                                "value_payload": {"description": "fewer pores"},
                                "interpretation": "energy input reduces pores",
                            }
                        ],
                        "measurement_results": [
                            {
                                "evidence_unit_id": "U003",
                                "property_normalized": "yield strength",
                                "value_payload": {"value": 462.02},
                                "unit": "MPa",
                            }
                        ],
                        "comparisons": [
                            {
                                "evidence_unit_id": "U004",
                                "property_normalized": "yield strength",
                                "interpretation": (
                                    "lower porosity increases yield strength"
                                ),
                            }
                        ],
                    }
                ],
                "cross_paper": {
                    "measured_properties": ["porosity", "yield strength"],
                    "measurement_value_ranges": [
                        {
                            "property_normalized": "yield strength",
                            "min": {"value": 236.65},
                            "max": {"value": 462.02},
                            "unit": "MPa",
                        }
                    ],
                },
            },
        }
    ]

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["mechanism_chains"] == [
        {
            "logic_chain_id": "LC001",
            "objective_id": "OBJ001",
            "paper_id": "P001",
            "evidence_unit_ids": ["U001", "U002", "U003"],
            "path": (
                "How does energy input affect pores and strength? -> "
                "sample: S014; process: SLM; energy input: high -> "
                "porosity: description: fewer pores; "
                "interpretation: energy input reduces pores -> "
                "yield strength: value: 462.02 MPa -> "
                "yield strength: lower porosity increases yield strength -> "
                "measured properties: porosity, yield strength; "
                "yield strength range 236.65 to 462.02 MPa"
            ),
        }
    ]


def test_build_target_prediction_derives_evidence_limitations() -> None:
    projection = _load_projection_module()
    bundle = {
        "papers": [
            {
                "paper_id": "P001",
                "title": "SLM process parameters and relative density",
                "target_properties": "relative density; mechanical properties",
            },
            {
                "paper_id": "P003",
                "title": "Volumetric energy density and fatigue",
                "target_properties": "fatigue; defect structure",
            },
            {
                "paper_id": "P005",
                "title": "Porosity and corrosion in SLM 316L",
                "target_properties": "corrosion",
            },
            {
                "paper_id": "P006",
                "title": "Texture and yield strength prediction",
                "target_properties": "texture; yield strength prediction",
            },
        ],
        "samples": [
            {"paper_id": "P003", "sample_id": "L-VED"},
            {"paper_id": "P003", "sample_id": "wrought-316L"},
        ],
        "test_conditions": [],
        "measurement_results": [
            {
                "paper_id": "P001",
                "result_id": "R001",
                "sample_id": "scan speed 2100 mm·s -1",
                "metric_name": "relative density",
                "value_or_trend": "99.5",
                "unit": "%",
            },
            {
                "paper_id": "P003",
                "result_id": "R002",
                "sample_id": "wrought-316L",
                "metric_name": "fatigue limit",
                "value_or_trend": "256",
                "unit": "MPa",
            },
            {
                "paper_id": "P005",
                "result_id": "R003",
                "sample_id": "SLM 316L",
                "metric_name": "pitting potential",
                "value_or_trend": "improved",
                "unit": "",
            },
            {
                "paper_id": "P006",
                "result_id": "R004",
                "sample_id": "case 7",
                "metric_name": "yield strength prediction",
                "value_or_trend": "347.14",
                "unit": "MPa",
            },
        ],
        "comparisons": [],
        "observations": [
            {
                "paper_id": "P001",
                "observation_id": "O001",
                "characterization_method": "SEM / ImageJ",
                "observed_object": "relative density",
                "value_or_description": "relative density measured from images",
            },
            {
                "paper_id": "P005",
                "observation_id": "O002",
                "characterization_method": "electrochemical test",
                "observed_object": "corrosion",
                "value_or_description": "room-temperature 3.5 wt.% NaCl testing",
            },
        ],
        "uncertainties": [],
        "evidence": [],
    }

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["limitations"] == [
        (
            "P001 scan-speed units may be uncertain and should be rechecked "
            "before recalculation."
        ),
        (
            "P001 relative density is SEM/ImageJ based and should not be "
            "treated as equivalent to Archimedes or micro-CT density."
        ),
        (
            "P003 printed-vs-wrought comparisons have different processing "
            "histories and cannot be attributed only to VED."
        ),
        (
            "P005 corrosion conclusions are limited to room-temperature "
            "3.5 wt.% NaCl testing."
        ),
        (
            "P006 is primarily a texture and yield-strength prediction paper, "
            "not a porosity-defect paper."
        ),
    ]


def test_build_target_prediction_derives_evidence_mechanism_chains() -> None:
    projection = _load_projection_module()
    bundle = {
        "papers": [
            {
                "paper_id": "P001",
                "title": "Energy input and scan strategy for SLM 316L",
                "target_properties": "density; strength; ductility; hardness",
            },
            {
                "paper_id": "P005",
                "title": "Power and scan speed combination controls corrosion",
                "target_properties": "pitting potential; Rfilm",
            },
            {
                "paper_id": "P006",
                "title": "Scan rotation angle and build orientation",
                "target_properties": "texture; yield strength prediction",
            },
        ],
        "samples": [],
        "test_conditions": [],
        "measurement_results": [
            {
                "paper_id": "P001",
                "metric_name": "hardness",
                "value_or_trend": "higher with density",
            },
            {
                "paper_id": "P005",
                "metric_name": "pitting potential",
                "value_or_trend": "depends on porosity",
            },
            {
                "paper_id": "P006",
                "metric_name": "yield strength prediction",
                "value_or_trend": "Bishop-Hill response",
            },
        ],
        "comparisons": [],
        "observations": [
            {
                "paper_id": "P001",
                "value_or_description": (
                    "Melt-pool stability and thermal accumulation change "
                    "porosity, LoF defects, balling, and cellular or "
                    "dendritic structure."
                ),
            },
            {
                "paper_id": "P005",
                "value_or_description": (
                    "Porosity level and pore type affect pitting initiation "
                    "and passive-film stability in 3.5 wt.% NaCl."
                ),
            },
            {
                "paper_id": "P006",
                "value_or_description": (
                    "Crystallographic texture links scan strategy rotation "
                    "angles and build orientations to Taylor factor."
                ),
            },
        ],
        "uncertainties": [],
        "evidence": [],
    }

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["mechanism_chains"][:3] == [
        {
            "chain_id": "energy_input_defect_mechanical",
            "path": (
                "energy input and scan strategy -> "
                "melt-pool stability and thermal accumulation -> "
                "porosity, LoF defects, balling, cellular or dendritic "
                "structure -> density, strength, ductility, hardness, fatigue"
            ),
        },
        {
            "chain_id": "porosity_passive_film_corrosion",
            "path": (
                "power and scan speed combination -> "
                "porosity level and pore type -> "
                "pitting initiation and passive-film stability -> "
                "pitting potential, passivation interval, Rfilm"
            ),
        },
        {
            "chain_id": "texture_yield_strength",
            "path": (
                "scan rotation angle and build orientation -> "
                "crystallographic texture -> "
                "Taylor factor or Bishop-Hill response -> "
                "yield strength prediction"
            ),
        },
    ]


def test_build_research_objective_target_prediction_writes_prediction_and_report(
    tmp_path: Path,
) -> None:
    projection = _load_projection_module()
    backend_root = Path(__file__).resolve().parents[3]
    target_path = (
        backend_root
        / "tests"
        / "fixtures"
        / "research_objective_targets"
        / "lpbf_slm_316l_collection_target.json"
    )
    bundle_path = tmp_path / "bundle.json"
    prediction_path = tmp_path / "target_prediction.json"
    report_path = tmp_path / "target_report.json"
    bundle_path.write_text(json.dumps(_prediction_bundle()), encoding="utf-8")

    result = projection.build_research_objective_target_prediction(
        prediction_bundle_path=bundle_path,
        output_path=prediction_path,
        target_path=target_path,
        report_path=report_path,
    )

    assert result == prediction_path
    assert json.loads(prediction_path.read_text(encoding="utf-8"))[
        "evidence_scope"
    ]["paper_count"] == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["quality_gate"][
        "status"
    ] == "fail"


def _prediction_bundle() -> dict:
    return {
        "papers": [
            {
                "paper_id": "P001",
                "title": "Energy input study",
                "research_goal": "Study energy input",
                "main_variables": "energy density",
                "target_properties": "density; strength",
            }
        ],
        "samples": [
            {"paper_id": "P001", "sample_id": "S001"},
            {"paper_id": "P001", "sample_id": "S002"},
        ],
        "test_conditions": [
            {"paper_id": "P001", "test_condition_id": "T001"},
        ],
        "measurement_results": [
            {
                "paper_id": "P001",
                "result_id": "R001",
                "sample_id": "S001",
                "metric_name": "density",
                "value_or_trend": "95",
                "unit": "%",
            },
            {
                "paper_id": "P001",
                "result_id": "R002",
                "sample_id": "S002",
                "metric_name": "yield strength",
                "value_or_trend": "450",
                "unit": "MPa",
            },
        ],
        "comparisons": [
            {
                "paper_id": "P001",
                "comparison_id": "C001",
                "current_sample_id": "S002",
                "baseline_reference": "S001",
                "metric_name": "density",
                "current_value": "99",
                "baseline_value": "95",
                "unit": "%",
                "direction": "improved",
                "notes": "Higher density sample performs better.",
            }
        ],
        "observations": [
            {
                "paper_id": "P001",
                "observation_id": "O001",
                "characterization_method": "SEM",
                "observed_object": "pores",
                "value_or_description": "fewer pores",
                "author_interpretation": "Energy input reduces pores.",
            }
        ],
        "uncertainties": [
            {
                "paper_id": "P001",
                "issue_id": "U001",
                "description": "density method limitation",
                "impact": "avoid over-comparison",
            }
        ],
        "evidence": [
            {
                "paper_id": "P001",
                "evidence_id": "E001",
                "figure_or_table": "Table 1",
                "section": "Results",
                "supports": "density",
            }
        ],
    }

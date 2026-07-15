from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError


def _load_goal_findings_check_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "check_goal_findings_projection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_goal_findings_projection",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _paper_level_boundary_fields():
    return {
        "paper_count": 1,
        "expert_use_status": "paper_level_finding",
        "generalization_status": "paper_level_only",
        "generalization_note": (
            "Evidence comes from one paper; use this as a traceable "
            "paper-level finding, not a cross-paper conclusion."
        ),
        "evidence_gap_summary": (
            "Needs independent cross-paper confirmation, support-grade "
            "curation, expert review."
        ),
    }


def _review_candidate_boundary_fields(paper_count: int = 2):
    return {
        "paper_count": paper_count,
        "expert_use_status": "review_candidate",
        "generalization_status": "cross_paper_candidate",
        "generalization_note": (
            f"Evidence spans {paper_count} papers, but support or review is not "
            "final; keep this as a cross-paper review candidate."
        ),
        "evidence_gap_summary": "Needs support-grade curation, expert review.",
        "review_reasons": [
            "cross_paper_evidence",
            "partial_support",
            "missing_mechanism_evidence",
            "needs_expert_review",
        ],
    }


def _paper_level_review_candidate_boundary_fields():
    return {
        "paper_count": 1,
        "expert_use_status": "review_candidate",
        "generalization_status": "paper_level_only",
        "generalization_note": (
            "Evidence comes from one paper; keep this as a traceable "
            "paper-level review candidate."
        ),
        "evidence_gap_summary": (
            "Needs text/mechanism review before expert use; do not treat as a "
            "cross-paper conclusion."
        ),
        "review_reasons": [
            "table_row_needs_text_or_mechanism_review",
            "needs_expert_review",
        ],
    }


def _ved_fatigue_strength_primary_finding():
    return {
        "finding_id": "finding-ved-fatigue-strength",
        "title": "VED -> fatigue strength",
        "statement": (
            "Increasing volumetric energy density (VED) lowered defect fraction, "
            "size, and complexity; from L-VED to M-VED it increased fatigue "
            "strength at 10^4 cycles from 340 MPa to 450 MPa."
        ),
        "variables": ["VED", "volumetric energy density"],
        "mediators": ["defect structure"],
        "outcomes": ["fatigue strength"],
        "evidence_ref_ids": ["ev-1", "ev-fatigue-strength"],
        "evidence_bundle": {"direct_result": ["ev-1", "ev-fatigue-strength"]},
        **_paper_level_boundary_fields(),
    }


def _ved_fatigue_strength_table_evidence(**extra):
    return {
        "evidence_ref_id": "ev-fatigue-strength",
        "source_kind": "table",
        "quote": (
            "At layer thickness 30, volumetric energy density increased from "
            "50.8 to 79.4 and fatigue strength increased from 340 MPa to 450 MPa."
        ),
        "href": "/collections/col-1/documents/doc-1?source_ref=tbl-fatigue",
        "table_audit": {
            "columns": [
                "Printed 316L",
                "VED",
                "FAT at 10^4 cycles [MPa]",
            ],
            "relevant_rows": [
                {
                    "row_index": 1,
                    "cells": ["L-VED", "50.8", "340"],
                },
                {
                    "row_index": 2,
                    "cells": ["M-VED", "79.4", "450"],
                },
            ],
        },
        **extra,
    }


def _goal_3037_axis_summary(
    evidence_count: int = 2,
    primary_finding_count: int = 1,
    review_queue_finding_count: int = 0,
):
    return {
        "evidence_count": evidence_count,
        "primary_finding_count": primary_finding_count,
        "review_queue_finding_count": review_queue_finding_count,
        "review_queue_count": review_queue_finding_count,
        "axis_coverage": {
            "variables": [
                {"axis": "volumetric energy density", "status": "primary"},
                {"axis": "energy density", "status": "primary"},
                {"axis": "laser beam powder bed fusion", "status": "context"},
            ],
            "properties": [
                {"axis": "defect structure", "status": "mechanism"},
                {"axis": "fatigue strength", "status": "primary"},
            ],
        },
    }


def _goal_6bf7_axis_summary(
    evidence_count: int = 2,
    primary_finding_count: int = 1,
    review_queue_finding_count: int = 0,
):
    return {
        "evidence_count": evidence_count,
        "primary_finding_count": primary_finding_count,
        "review_queue_finding_count": review_queue_finding_count,
        "review_queue_count": review_queue_finding_count,
        "axis_coverage": {
            "variables": [
                {"axis": "selective laser melting", "status": "context"},
                {"axis": "scanning strategy", "status": "context"},
                {"axis": "scanning speed", "status": "primary"},
                {"axis": "energy density", "status": "context"},
            ],
            "properties": [
                {"axis": "yield strength", "status": "primary"},
                {"axis": "ultimate tensile strength", "status": "primary"},
                {"axis": "elongation", "status": "primary"},
            ],
        },
    }


def _goal_1a7_axis_summary(
    evidence_count: int = 3,
    primary_finding_count: int = 1,
    review_queue_finding_count: int = 2,
):
    return {
        "evidence_count": evidence_count,
        "primary_finding_count": primary_finding_count,
        "review_queue_finding_count": review_queue_finding_count,
        "review_queue_count": review_queue_finding_count,
        "axis_coverage": {
            "variables": [
                {"axis": "selective laser melting", "status": "context"},
                {"axis": "heat treatment", "status": "primary"},
                {"axis": "laser power", "status": "review_queue"},
                {"axis": "scan speed", "status": "review_queue"},
                {"axis": "heat treatment type", "status": "primary"},
                {"axis": "heat treatment parameters", "status": "primary"},
            ],
            "properties": [
                {"axis": "density", "status": "primary"},
                {"axis": "microstructure", "status": "primary"},
            ],
        },
    }


def _goal_061_axis_summary(
    evidence_count: int = 2,
    primary_finding_count: int = 1,
    review_queue_finding_count: int = 1,
):
    return {
        "evidence_count": evidence_count,
        "primary_finding_count": primary_finding_count,
        "review_queue_finding_count": review_queue_finding_count,
        "review_queue_count": review_queue_finding_count,
        "axis_coverage": {
            "variables": [
                {"axis": "Laser Powder Bed Fusion", "status": "context"},
                {"axis": "scan strategy rotation angle", "status": "primary"},
                {"axis": "build orientation angle", "status": "primary"},
            ],
            "properties": [
                {"axis": "crystallographic texture", "status": "mechanism"},
                {"axis": "yield strength", "status": "primary"},
            ],
        },
    }


def test_evaluate_goal_analysis_payload_passes_expert_ready_projection():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "summary": _goal_3037_axis_summary(),
                    "primary_findings": [
                        {
                            "finding_id": "finding-ved-fatigue-strength",
                            "title": "VED -> fatigue strength",
                            "statement": (
                                "Increasing volumetric energy density (VED) "
                                "lowered defect fraction, size, and complexity; "
                                "from L-VED to M-VED it increased fatigue "
                                "strength at 10^4 cycles from 340 MPa to 450 MPa."
                            ),
                            "variables": ["VED", "volumetric energy density"],
                            "mediators": ["defect structure"],
                            "outcomes": ["fatigue strength"],
                            "evidence_ref_ids": ["ev-1", "ev-fatigue-strength"],
                            "evidence_bundle": {
                                "direct_result": ["ev-1", "ev-fatigue-strength"]
                            },
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Increasing VED reduced defect fraction, size, "
                                "and complexity, but fatigue resistance remained "
                                "below wrought 316L steel."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        _ved_fatigue_strength_table_evidence(),
                    ],
                },
            },
        }
    )

    assert summary["primary_finding_count"] == 1
    assert summary["direct_evidence_count"] == 2
    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_resolves_direct_evidence_to_source_artifacts():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "summary": _goal_3037_axis_summary(),
                    "primary_findings": [
                        {
                            "finding_id": "finding-ved-fatigue-strength",
                            "title": "VED -> fatigue strength",
                            "statement": (
                                "Increasing volumetric energy density (VED) "
                                "lowered defect fraction and increased fatigue "
                                "strength from 340 MPa to 450 MPa."
                            ),
                            "variables": ["VED", "volumetric energy density"],
                            "mediators": ["defect structure"],
                            "outcomes": ["fatigue strength"],
                            "evidence_ref_ids": ["ev-1", "ev-fatigue-strength"],
                            "evidence_bundle": {
                                "direct_result": ["ev-1", "ev-fatigue-strength"]
                            },
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "page": "10",
                            "quote": (
                                "Increasing VED reduced defects and improved fatigue "
                                "resistance, but fatigue resistance remained below "
                                "wrought 316L steel."
                            ),
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=10"
                            ),
                        },
                        _ved_fatigue_strength_table_evidence(
                            document_id="doc-1",
                            source_ref="tbl-fatigue",
                            page="10",
                        ),
                    ],
                },
            },
        },
        source_index={
            "documents": {"doc-1"},
                "sources": {
                    "blk-1": {
                        "kind": "block",
                    "document_id": "doc-1",
                    "page": "10",
                    "text": (
                        "Increasing VED reduced defects and improved fatigue life, "
                            "but fatigue resistance remained below wrought 316L steel."
                        ),
                    },
                    "tbl-fatigue": {
                        "kind": "table",
                        "document_id": "doc-1",
                        "page": "10",
                        "text": (
                            "At layer thickness 30, volumetric energy density "
                            "increased from 50.8 to 79.4 and fatigue strength "
                            "increased from 340 MPa to 450 MPa."
                        ),
                    }
                },
            },
    )

    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_requires_table_evidence_audit_rows():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "summary": _goal_3037_axis_summary(),
                    "primary_findings": [_ved_fatigue_strength_primary_finding()],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "page": "10",
                            "quote": (
                                "Increasing VED reduced defects and improved fatigue "
                                "resistance, but fatigue resistance remained below "
                                "wrought 316L steel."
                            ),
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=10"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-fatigue-strength",
                            "document_id": "doc-1",
                            "source_ref": "tbl-fatigue",
                            "page": "10",
                            "quote": (
                                "At layer thickness 30, volumetric energy density "
                                "increased from 50.8 to 79.4 and fatigue strength "
                                "increased from 340 MPa to 450 MPa."
                            ),
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-fatigue&page=10"
                            ),
                        },
                    ],
                },
            },
        },
        source_index={
            "documents": {"doc-1"},
            "sources": {
                "blk-1": {
                    "kind": "block",
                    "document_id": "doc-1",
                    "page": "10",
                    "text": (
                        "Increasing VED reduced defects and improved fatigue life, "
                        "but fatigue resistance remained below wrought 316L steel."
                    ),
                },
                "tbl-fatigue": {
                    "kind": "table",
                    "document_id": "doc-1",
                    "page": "10",
                    "text": (
                        "At layer thickness 30, volumetric energy density "
                        "increased from 50.8 to 79.4 and fatigue strength "
                        "increased from 340 MPa to 450 MPa."
                    ),
                },
            },
        },
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "table direct evidence exposes relevant rows and columns" in failed_names


def test_evaluate_goal_analysis_payload_requires_table_rows_cover_from_to_endpoints():
    check = _load_goal_findings_check_module()

    evidence = _ved_fatigue_strength_table_evidence()
    evidence["table_audit"]["relevant_rows"] = [
        {
            "row_index": 2,
            "cells": ["M-VED", "79.4", "450"],
        },
    ]
    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "summary": _goal_3037_axis_summary(),
                    "primary_findings": [_ved_fatigue_strength_primary_finding()],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Increasing VED reduced defects and improved fatigue "
                                "resistance, but fatigue resistance remained below "
                                "wrought 316L steel."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        evidence,
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "table direct evidence covers statement numeric endpoints"
        in failed_names
    )


def test_evaluate_goal_analysis_payload_fails_unreferenced_presentation_evidence():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "VED -> fatigue life",
                            "statement": (
                                "Increasing VED lowered defect fraction and "
                                "improved fatigue life."
                            ),
                            "variables": ["VED"],
                            "mediators": ["defect structure"],
                            "outcomes": ["fatigue life"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-energy",
                            "title": "energy density -> yield strength",
                            "statement": (
                                "With scan speed 100, changing energy density "
                                "from 278 to 333 increased yield strength from "
                                "319.0 MPa to 464.8 MPa."
                            ),
                            "variables": ["energy density"],
                            "outcomes": ["yield strength"],
                            "evidence_ref_ids": ["ev-3"],
                            "evidence_bundle": {"direct_result": ["ev-3"]},
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Increasing VED reduced defects and improved fatigue life, "
                                "but fatigue resistance remained below wrought 316L steel."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-background",
                            "quote": "Background paragraph not used by any finding.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-2",
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "presentation evidence only contains referenced finding evidence"
        in failed_names
    )


def test_evaluate_goal_analysis_payload_fails_missing_goal_axis_coverage():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "summary": {"evidence_count": 1},
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "VED -> fatigue life",
                            "statement": (
                                "Increasing VED lowered defect fraction and "
                                "improved fatigue life."
                            ),
                            "variables": ["VED"],
                            "mediators": ["defect structure"],
                            "outcomes": ["fatigue life"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Increasing VED reduced defects and improved fatigue life, "
                                "but fatigue resistance remained below wrought 316L steel."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "goal coverage exposes requested variable axes" in failed_names
    assert "goal coverage exposes requested property axes" in failed_names


def test_evaluate_goal_analysis_payload_fails_domain_mismatched_projection():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_3037e425673a"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "scan speed -> hardness",
                            "statement": "Scan speed changed hardness.",
                            "variables": ["scan speed"],
                            "mediators": ["microstructure"],
                            "outcomes": ["hardness"],
                            "scope_summary": "316L stainless steel",
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": "Higher scan speed refined microstructure and hardness.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "primary findings match goal-specific expert expectations" in failed_names
    assert "direct evidence quotes cover goal-specific source claims" in failed_names


def test_evaluate_goal_analysis_payload_fails_specific_scan_speed_projection_without_table_evidence():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_6bf7d2c1030e"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_6bf7_axis_summary(evidence_count=2),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "scanning speed -> yield strength, ultimate "
                                "tensile strength, and elongation"
                            ),
                            "statement": (
                                "Higher scanning speed improved densification, "
                                "microstructure, and mechanical properties."
                            ),
                            "variables": ["scanning speed"],
                            "mediators": ["microstructure"],
                            "outcomes": [
                                (
                                    "yield strength, ultimate tensile strength, "
                                    "and elongation"
                                )
                            ],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Higher scanning speed exhibited better "
                                "densification, refined microstructure, and "
                                "excellent mechanical properties."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "direct evidence quotes cover goal-specific source claims" in failed_names


def test_evaluate_goal_analysis_payload_accepts_specific_scan_speed_projection_with_table_evidence():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_6bf7d2c1030e"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_6bf7_axis_summary(evidence_count=2),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "scanning speed -> yield strength, ultimate "
                                "tensile strength, and elongation"
                            ),
                            "statement": (
                                "Higher scanning speed improved densification "
                                "and refined microstructure, with mechanical "
                                "property values traceable in the source table."
                            ),
                            "variables": ["scanning speed"],
                            "mediators": ["microstructure", "densification"],
                            "outcomes": [
                                "yield strength",
                                "ultimate tensile strength",
                                "elongation",
                            ],
                            "evidence_ref_ids": ["ev-1", "ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-1", "ev-2"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Higher scanning speed exhibited better "
                                "densification, refined microstructure, and "
                                "excellent mechanical properties."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": (
                                "Mechanical properties include Yield Strength "
                                "(MPa), Ultimate Tensile Strength (MPa), and "
                                "Elongation (%) with values 236.65, "
                                "375.13, and 7.21."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-1",
                        },
                    ],
                },
            },
        }
    )

    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_rejects_scan_speed_confounded_review_rows():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_6bf7d2c1030e"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_6bf7_axis_summary(evidence_count=4),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "scanning speed -> yield strength, ultimate "
                                "tensile strength, and elongation"
                            ),
                            "statement": (
                                "Higher scanning speed improved densification "
                                "and refined microstructure, with mechanical "
                                "property values traceable in the source table."
                            ),
                            "variables": ["scanning speed"],
                            "mediators": ["microstructure", "densification"],
                            "outcomes": [
                                "yield strength",
                                "ultimate tensile strength",
                                "elongation",
                            ],
                            "evidence_ref_ids": ["ev-1", "ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-1", "ev-2"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-energy",
                            "title": "multi-axis table contrast -> yield strength",
                            "statement": (
                                "With scan speed 100, table-row comparison "
                                "changes Density from 98.15 to 98.11, Laser "
                                "energy density from 278 to 333, laser power "
                                "from 100 to 120 and heat treatment type from "
                                "HIP to -; yield strength increased from "
                                "319.0 MPa to 464.8 MPa."
                            ),
                            "variables": ["multi-axis table contrast"],
                            "outcomes": ["yield strength"],
                            "evidence_ref_ids": ["ev-3"],
                            "evidence_bundle": {"direct_result": ["ev-3"]},
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Higher scanning speed exhibited better "
                                "densification, refined microstructure, and "
                                "excellent mechanical properties."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": (
                                "Mechanical properties include Yield Strength "
                                "(MPa), Ultimate Tensile Strength (MPa), and "
                                "Elongation (%) with values 236.65, "
                                "375.13, and 7.21."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-1",
                        },
                        {
                            "evidence_ref_id": "ev-3",
                            "quote": (
                                "With scan speed 100, energy density increased "
                                "from 278 to 333 and yield strength increased "
                                "from 319.0 MPa to 464.8 MPa."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-2",
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "all expert findings avoid goal-specific noise rows" in failed_names


def test_evaluate_goal_analysis_payload_fails_scan_speed_primary_with_table_wide_range():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_6bf7d2c1030e"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_6bf7_axis_summary(evidence_count=3),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "scanning speed -> yield strength, ultimate "
                                "tensile strength, and elongation"
                            ),
                            "statement": (
                                "Higher scanning speed improved densification "
                                "and refined microstructure; the table reports "
                                "Yield Strength 236.65-462.02 MPa, Ultimate "
                                "Tensile Strength 375.13-584.44 MPa, and "
                                "Elongation 7.21-41.9%."
                            ),
                            "variables": ["scanning speed"],
                            "mediators": ["microstructure", "densification"],
                            "outcomes": [
                                "yield strength",
                                "ultimate tensile strength",
                                "elongation",
                            ],
                            "evidence_ref_ids": ["ev-1", "ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-1", "ev-2"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Higher scanning speed exhibited better "
                                "densification, refined microstructure, and "
                                "excellent mechanical properties."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": (
                                "Mechanical properties include Yield Strength "
                                "(MPa), Ultimate Tensile Strength (MPa), and "
                                "Elongation (%) with values 236.65, "
                                "375.13, and 7.21."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-1",
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "primary findings avoid over-specific unsupported terms" in failed_names


def test_evaluate_goal_analysis_payload_fails_missing_primary_goal_axis_titles():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_1a7a26d850b9"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_1a7_axis_summary(),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density and microstructure",
                            "statement": (
                                "Heat treatment increased density and changed "
                                "cellular microstructure."
                            ),
                            "variables": ["heat treatment"],
                            "mediators": ["cellular microstructure"],
                            "outcomes": ["density and microstructure"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Heat treatment increased density and removed "
                                "cellular microstructure and dense dislocation structures."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "review queue preserves goal-specific table axes" in failed_names


def test_evaluate_goal_analysis_payload_accepts_table_axes_in_review_queue():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_1a7a26d850b9"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_1a7_axis_summary(),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density and microstructure",
                            "statement": (
                                "Heat treatment increased density and changed "
                                "cellular microstructure."
                            ),
                            "variables": ["heat treatment"],
                            "mediators": ["cellular microstructure"],
                            "outcomes": ["density and microstructure"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-1",
                            "title": "laser power -> density",
                            "statement": (
                                "With scan speed 200, changing laser power "
                                "from 100 to 120 increased density from "
                                "93.67 % to 96.84 %."
                            ),
                            "variables": ["laser power"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-2"]},
                            **_paper_level_boundary_fields(),
                        },
                        {
                            "finding_id": "finding-review-2",
                            "title": "scan speed -> density",
                            "statement": (
                                "With laser power 100 and heat treatment type "
                                "Furnace HT, changing scan speed from 100 to "
                                "200 decreased density from 98.70 % to 93.67 %."
                            ),
                            "variables": ["scan speed"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-3"],
                            "evidence_bundle": {"direct_result": ["ev-3"]},
                            **_review_candidate_boundary_fields(),
                        },
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Heat treatment increased density and removed "
                                "cellular microstructure and dense dislocation structures."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": "Laser power changed density.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-2",
                        },
                        {
                            "evidence_ref_id": "ev-3",
                            "quote": (
                                "With laser power 100 and scan speed 200, "
                                "density decreased from 98.70 % to 93.67 %."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-3",
                        }
                    ],
                },
            },
        }
    )

    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_rejects_low_magnitude_density_review_row():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_1a7a26d850b9"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_1a7_axis_summary(
                        evidence_count=3,
                        review_queue_finding_count=2,
                    ),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density and microstructure",
                            "statement": (
                                "Heat treatment increased density and changed "
                                "cellular microstructure."
                            ),
                            "variables": ["heat treatment"],
                            "mediators": ["cellular microstructure"],
                            "outcomes": ["density and microstructure"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-1",
                            "title": "scan speed -> density",
                            "statement": (
                                "With laser power 100 and heat treatment type "
                                "Furnace HT, changing scan speed from 100 to "
                                "200 decreased density from 98.70 % to 93.67 %."
                            ),
                            "variables": ["scan speed"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-2"]},
                            **_review_candidate_boundary_fields(),
                        },
                        {
                            "finding_id": "finding-review-low-delta",
                            "title": "laser power -> density",
                            "statement": (
                                "With scan speed 100 and heat treatment type "
                                "Furnace HT, changing laser power from 100 to "
                                "120 decreased density from 98.70 % to 98.45 %."
                            ),
                            "variables": ["laser power"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-3"],
                            "evidence_bundle": {"direct_result": ["ev-3"]},
                            **_paper_level_review_candidate_boundary_fields(),
                        },
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Heat treatment increased density and removed "
                                "cellular microstructure and dense dislocation structures."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": (
                                "With laser power 100 and scan speed 200, "
                                "density decreased from 98.70 % to 93.67 %."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-2",
                        },
                        {
                            "evidence_ref_id": "ev-3",
                            "quote": (
                                "With scan speed 100 and heat treatment type "
                                "Furnace HT, changing laser power from 100 to "
                                "120 decreased density from 98.70 % to 98.45 %."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-3",
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "all expert findings avoid goal-specific noise rows" in failed_names


def test_evaluate_goal_analysis_payload_accepts_single_paper_review_candidate_boundary():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-review-boundary"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": {
                        "evidence_count": 2,
                        "primary_finding_count": 1,
                        "review_queue_finding_count": 1,
                        "review_queue_count": 1,
                        "axis_coverage": {
                            "variables": [
                                {"axis": "heat treatment", "status": "primary"},
                                {"axis": "laser power", "status": "review_queue"},
                            ],
                            "properties": [
                                {"axis": "density", "status": "primary"},
                                {"axis": "microstructure", "status": "primary"},
                            ],
                        },
                    },
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density and microstructure",
                            "statement": (
                                "Heat treatment increased density and changed "
                                "cellular microstructure."
                            ),
                            "variables": ["heat treatment"],
                            "mediators": ["cellular microstructure"],
                            "outcomes": ["density and microstructure"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-1",
                            "title": "laser power -> density",
                            "statement": (
                                "With scan speed 100 and heat treatment type "
                                "Furnace HT, changing laser power from 100 to "
                                "120 decreased density from 98.70 % to 98.45 %."
                            ),
                            "variables": ["laser power"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-2"]},
                            **_paper_level_review_candidate_boundary_fields(),
                        },
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Heat treatment increased density and removed "
                                "cellular microstructure and dense dislocation structures."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": (
                                "With scan speed 100 and heat treatment type "
                                "Furnace HT, changing laser power from 100 to "
                                "120 changed density."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=tbl-2",
                        },
                    ],
                },
            },
        }
    )

    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_fails_stale_review_queue_multi_paper_boundary():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_1a7a26d850b9"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density and microstructure",
                            "statement": (
                                "Heat treatment increased density and changed "
                                "cellular microstructure."
                            ),
                            "variables": ["heat treatment"],
                            "mediators": ["cellular microstructure"],
                            "outcomes": ["density and microstructure"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-1",
                            "title": "scan speed -> density",
                            "paper_count": 2,
                            "expert_use_status": "paper_level_finding",
                            "generalization_status": "paper_level_only",
                            "generalization_note": (
                                "Evidence comes from one paper; use this as a "
                                "traceable paper-level finding, not a cross-paper "
                                "conclusion."
                            ),
                            "evidence_gap_summary": (
                                "Needs independent cross-paper confirmation, "
                                "support-grade curation, expert review."
                            ),
                            "review_reasons": [
                                "single_paper_evidence",
                                "needs_cross_paper_confirmation",
                            ],
                            "upgrade_actions": [
                                "verify_direct_evidence",
                                "add_cross_paper_evidence",
                            ],
                            "evidence_ref_ids": ["ev-2", "ev-3"],
                            "evidence_bundle": {
                                "direct_result": ["ev-2", "ev-3"]
                            },
                        },
                        {"title": "laser power -> density"},
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": (
                                "Heat treatment increased density and removed "
                                "cellular microstructure and dense dislocation structures."
                            ),
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": "Scan speed changed density in paper one.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-2",
                        },
                        {
                            "evidence_ref_id": "ev-3",
                            "quote": "Scan speed changed density in paper two.",
                            "href": "/collections/col-1/documents/doc-2?source_ref=blk-3",
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "multi-paper findings and review targets are labeled as cross-paper"
        in failed_names
    )


def test_evaluate_goal_analysis_payload_accepts_model_validation_primary_target():
    check = _load_goal_findings_check_module()
    result_quote = (
        "The yield strength increased from the 0-0-0 configuration to the "
        "45-22.5-0 condition, with deviations generally less than 5%."
    )
    table_quote = (
        "Table 3: α β θ, Yield Strength Prediction (MPa), Yield Strength "
        "Experiment (MPa). Rows: 0 0 0 310.48 334.2; "
        "0 0 45 328.67 351.9; 45 22.5 0 341.85 363.1."
    )
    table_audit = {
        "columns": [
            "α (°)",
            "β (°)",
            "θ (°)",
            "Yield Strength Prediction (MPa)",
            "Yield Strength Experiment (MPa)",
        ],
        "relevant_rows": [
            {"row_index": 1, "cells": ["0", "0", "0", "310.48", "334.2"]},
            {"row_index": 3, "cells": ["0", "0", "45", "328.67", "351.9"]},
            {
                "row_index": 5,
                "cells": ["45", "22.5", "0", "341.85", "363.1"],
            },
        ],
    }

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_061c9c049e69"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_061_axis_summary(
                        evidence_count=4,
                        primary_finding_count=2,
                        review_queue_finding_count=0,
                    ),
                    "primary_findings": [
                        {
                            "finding_id": "finding-build-orientation",
                            "title": "α and β build orientation angles -> yield strength",
                            "statement": (
                                "At fixed scan strategy rotation angle θ=0°, changing "
                                "build orientation from α=0° and β=0° to α=45° and "
                                "β=22.5° increased experimental yield strength from "
                                "334.2 MPa to 363.1 MPa. The authors describe model "
                                "deviations as generally below 5%, but the Table 3 "
                                "values do not uniformly satisfy that summary."
                            ),
                            "variables": ["α and β build orientation angles"],
                            "mediators": ["crystallographic texture"],
                            "outcomes": ["yield strength"],
                            "scope_summary": (
                                "316L stainless steel, scan strategy rotation angle, "
                                "α build orientation angle, β build orientation angle, "
                                "crystallographic texture, yield strength"
                            ),
                            "evidence_ref_ids": ["ev-build-result", "ev-build-table"],
                            "evidence_bundle": {
                                "direct_result": ["ev-build-result", "ev-build-table"]
                            },
                            "comparison_summary": {
                                "variable": "α and β build orientation angles",
                                "direction": "increases",
                                "outcome": "yield strength",
                                "baseline": {
                                    "label": "α=0°, β=0°",
                                    "value": "334.2 MPa",
                                },
                                "observed": {
                                    "label": "α=45°, β=22.5°",
                                    "value": "363.1 MPa",
                                },
                                "controlled_conditions": [
                                    {
                                        "axis": "scan strategy rotation angle (θ)",
                                        "value": "0°",
                                    }
                                ],
                            },
                            "warnings": [
                                "model_validation_finding",
                                "author_summary_table_mismatch",
                            ],
                            **_paper_level_boundary_fields(),
                        },
                        {
                            "finding_id": "finding-scan-rotation",
                            "title": "scan strategy rotation angle -> yield strength",
                            "statement": (
                                "At fixed build orientation α=0° and β=0°, changing "
                                "scan strategy rotation angle θ from 0° to 45° "
                                "increased experimental yield strength from 334.2 MPa "
                                "to 351.9 MPa. The authors describe model deviations "
                                "as generally below 5%, but the Table 3 values do not "
                                "uniformly satisfy that summary."
                            ),
                            "variables": ["scan strategy rotation angle"],
                            "mediators": ["crystallographic texture"],
                            "outcomes": ["yield strength"],
                            "scope_summary": (
                                "316L stainless steel, scan strategy rotation angle, "
                                "α build orientation angle, β build orientation angle, "
                                "crystallographic texture, yield strength"
                            ),
                            "evidence_ref_ids": ["ev-scan-result", "ev-scan-table"],
                            "evidence_bundle": {
                                "direct_result": ["ev-scan-result", "ev-scan-table"]
                            },
                            "comparison_summary": {
                                "variable": "scan strategy rotation angle (θ)",
                                "direction": "increases",
                                "outcome": "yield strength",
                                "baseline": {"label": "θ=0°", "value": "334.2 MPa"},
                                "observed": {"label": "θ=45°", "value": "351.9 MPa"},
                                "controlled_conditions": [
                                    {"axis": "α build orientation angle", "value": "0°"},
                                    {"axis": "β build orientation angle", "value": "0°"},
                                ],
                            },
                            "warnings": [
                                "model_validation_finding",
                                "author_summary_table_mismatch",
                            ],
                            **_paper_level_boundary_fields(),
                        },
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-build-result",
                            "document_id": "doc-1",
                            "source_ref": "blk-result",
                            "source_kind": "paragraph",
                            "page": "8",
                            "quote": result_quote,
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-result&page=8"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-build-table",
                            "document_id": "doc-1",
                            "source_ref": "tbl-validation",
                            "source_kind": "table",
                            "page": "8",
                            "quote": table_quote,
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-validation&page=8"
                            ),
                            "table_audit": table_audit,
                        },
                        {
                            "evidence_ref_id": "ev-scan-result",
                            "document_id": "doc-1",
                            "source_ref": "blk-result",
                            "source_kind": "paragraph",
                            "page": "8",
                            "quote": result_quote,
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-result&page=8"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-scan-table",
                            "document_id": "doc-1",
                            "source_ref": "tbl-validation",
                            "source_kind": "table",
                            "page": "8",
                            "quote": table_quote,
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-validation&page=8"
                            ),
                            "table_audit": table_audit,
                        },
                    ],
                },
            },
        },
        source_index={
            "documents": {"doc-1"},
            "sources": {
                "blk-result": {
                    "kind": "block",
                    "document_id": "doc-1",
                    "page": "8",
                    "text": result_quote,
                },
                "tbl-validation": {
                    "kind": "table",
                    "document_id": "doc-1",
                    "page": "8",
                    "text": table_quote,
                },
            },
        },
    )

    assert summary["primary_finding_count"] == 2
    assert summary["review_queue_finding_count"] == 0
    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_analysis_payload_rejects_small_prediction_review_row():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal_061c9c049e69"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": _goal_061_axis_summary(
                        evidence_count=2,
                        review_queue_finding_count=1,
                    ),
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "scan strategy rotation angle and build orientation "
                                "-> yield strength"
                            ),
                            "statement": (
                                "Changing scan strategy rotation angle and build "
                                "orientation was experimentally validated against "
                                "crystallographic-texture-based Bishop-Hill yield "
                                "strength predictions; yield strength increased "
                                "from the 0-0-0 configuration to the 45-22.5-0 "
                                "condition with deviations generally below 5%."
                            ),
                            "variables": [
                                "scan strategy rotation angle and build orientation"
                            ],
                            "mediators": ["crystallographic texture"],
                            "outcomes": ["yield strength"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            "comparison_summary": {
                                "variable": (
                                    "scan strategy rotation angle and build "
                                    "orientation"
                                ),
                                "direction": "increases",
                                "outcome": "yield strength",
                            },
                            "warnings": ["model_validation_finding"],
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding-review-1",
                            "title": "β build orientation angle -> yield strength prediction",
                            "statement": (
                                "Under ɵ=0, α=0 and θ=0, β increased yield "
                                "strength prediction from 310.48 MPa to "
                                "314.37 MPa."
                            ),
                            "variables": ["β build orientation angle"],
                            "outcomes": ["yield strength prediction"],
                            "evidence_ref_ids": ["ev-review"],
                            "evidence_bundle": {"direct_result": ["ev-review"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "quote": (
                                "The yield strength increased from the 0-0-0 "
                                "configuration to the 45-22.5-0 condition, "
                                "with deviations generally less than 5%."
                            ),
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=8"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-review",
                            "document_id": "doc-1",
                            "source_ref": "tbl-1",
                            "quote": (
                                "β build orientation angle changed yield "
                                "strength prediction from 310.48 MPa to "
                                "314.37 MPa."
                            ),
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-1&page=9"
                            ),
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "all expert findings avoid goal-specific noise rows" in failed_names


def test_evaluate_goal_analysis_payload_fails_noisy_scope_summary():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "heat treatment -> density",
                            "statement": "Heat treatment increased density.",
                            "variables": ["heat treatment"],
                            "outcomes": ["density"],
                            "scope_summary": (
                                "stainless steel 316L, heat treatment, "
                                "4. Conclusion, as-SLM (100/"
                            ),
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": "Heat treatment increased density.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "finding scope summaries exclude parser and sample-label noise"
        in failed_names
    )


def test_evaluate_goal_analysis_payload_fails_symbol_axis_scope_mismatch():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": (
                                "β build orientation angle -> yield strength "
                                "experiment"
                            ),
                            "statement": (
                                "Under α=0 and θ=0, β decreased yield strength "
                                "experiment."
                            ),
                            "variables": ["β build orientation angle"],
                            "outcomes": ["yield strength experiment"],
                            "scope_summary": (
                                "316L stainless steel, α build orientation angle, "
                                "yield strength experiment"
                            ),
                            "comparison_summary": {
                                "variable": "β build orientation angle",
                                "direction": "decreases",
                                "outcome": "yield strength experiment",
                            },
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": "β decreased yield strength experiment.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "symbol-axis findings keep title and scope aligned" in failed_names


def test_evaluate_goal_analysis_payload_fails_broken_source_artifact_trace():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "scan speed -> strength",
                            "evidence_ref_ids": ["ev-1", "ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-1", "ev-2"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "missing-block",
                            "quote": "The exact direct evidence quote.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=missing-block&page=3"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "quote": "This quote belongs to a different part of the paper.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=3"
                            ),
                        },
                    ],
                },
            },
        },
        source_index={
            "documents": {"doc-1"},
            "sources": {
                "blk-1": {
                    "kind": "block",
                    "document_id": "doc-1",
                    "page": "3",
                    "text": "The resolved source block discusses porosity and density.",
                }
            },
        },
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "direct evidence hrefs resolve to source artifacts" in failed_names
    assert "direct evidence quotes overlap resolved source artifacts" in failed_names


def test_evaluate_goal_analysis_payload_fails_duplicate_source_target_evidence():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "laser power -> density",
                            "statement": "Laser power changes density.",
                            "variables": ["laser power"],
                            "outcomes": ["density"],
                            "evidence_ref_ids": ["ev-1", "ev-2"],
                            "evidence_bundle": {"direct_result": ["ev-1", "ev-2"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "tbl-1",
                            "page": "4",
                            "quote": "Table 1 density values.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-1&page=4"
                            ),
                        },
                        {
                            "evidence_ref_id": "ev-2",
                            "document_id": "doc-1",
                            "source_ref": "tbl-1",
                            "page": "4",
                            "quote": "Table 1 density values.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=tbl-1&page=4"
                            ),
                        },
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "finding evidence does not duplicate source targets" in failed_names


def test_evaluate_goal_analysis_payload_allows_direct_evidence_as_mechanism_ref():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "preheating -> ductility",
                            "statement": "Preheating increased ductility.",
                            "variables": ["preheating"],
                            "outcomes": ["ductility"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {
                                "direct_result": ["ev-1"],
                                "mechanism": ["ev-1"],
                            },
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "quote": "Preheating increased ductility.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=4"
                            ),
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "finding evidence bundles do not repeat ref ids" not in failed_names


def test_evaluate_goal_analysis_payload_fails_duplicate_bundle_ref_ids():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "preheating -> ductility",
                            "statement": "Preheating increased ductility.",
                            "variables": ["preheating"],
                            "outcomes": ["ductility"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {
                                "direct_result": ["ev-1"],
                                "background": ["ev-1"],
                            },
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "quote": "Preheating increased ductility.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=4"
                            ),
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "finding evidence bundles do not repeat ref ids" in failed_names


def test_evaluate_goal_analysis_payload_fails_stale_summary_finding_counts():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "ready",
                "presentation": {
                    "summary": {
                        "primary_finding_count": 1,
                        "review_queue_finding_count": 9,
                        "review_queue_count": 9,
                        "evidence_count": 1,
                    },
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "preheating -> ductility",
                            "statement": "Preheating increased ductility.",
                            "variables": ["preheating"],
                            "outcomes": ["ductility"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "source_ref": "blk-1",
                            "quote": "Preheating increased ductility.",
                            "href": (
                                "/collections/col-1/documents/doc-1"
                                "?view=parsed-paper&source_ref=blk-1&page=4"
                            ),
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "summary finding counts match visible findings" in failed_names


def test_evaluate_goal_analysis_payload_fails_stale_or_untraceable_projection():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "empty",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "scan speed -> strength",
                            "evidence_ref_ids": ["ev-missing"],
                            "evidence_bundle": {"direct_result": ["ev-missing"]},
                            **_paper_level_boundary_fields(),
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-other",
                            "quote": "\ufffd noisy quote",
                            "href": "",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert "understanding state is not empty when findings exist" in failed_names
    assert "direct evidence ids resolve to presentation evidence items" in failed_names
    assert "direct evidence items include quote and href" in failed_names
    assert "presentation evidence text excludes replacement characters" in failed_names


def test_evaluate_goal_analysis_payload_fails_missing_expert_boundary_fields():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "preheating -> ductility",
                            "statement": "Preheating increased ductility.",
                            "variables": ["preheating"],
                            "outcomes": ["ductility"],
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "quote": "Preheating increased ductility.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "expert findings and review targets include expert use status"
        in failed_names
    )
    assert (
        "expert findings and review targets include generalization status"
        in failed_names
    )
    assert (
        "expert findings and review targets include generalization note"
        in failed_names
    )
    assert (
        "expert findings and review targets include evidence gap summary"
        in failed_names
    )


def test_evaluate_goal_analysis_payload_fails_single_paper_cross_paper_status():
    check = _load_goal_findings_check_module()

    summary = check.evaluate_goal_analysis_payload(
        {
            "goal": {"goal_id": "goal-1"},
            "understanding": {
                "state": "limited",
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding-1",
                            "title": "preheating -> ductility",
                            "statement": "Preheating increased ductility.",
                            "variables": ["preheating"],
                            "outcomes": ["ductility"],
                            "paper_count": 1,
                            "expert_use_status": "scoped_expert_finding",
                            "generalization_status": "scoped_cross_paper",
                            "generalization_note": "Cross-paper conclusion.",
                            "evidence_gap_summary": "No gap.",
                            "evidence_ref_ids": ["ev-1"],
                            "evidence_bundle": {"direct_result": ["ev-1"]},
                        }
                    ],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev-1",
                            "document_id": "doc-1",
                            "quote": "Preheating increased ductility.",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                        }
                    ],
                },
            },
        }
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert (
        "single-paper findings and review targets are labeled as paper-level only"
        in failed_names
    )


def test_fetch_goal_analysis_payload_from_api_logs_in_and_reads_goal(monkeypatch):
    check = _load_goal_findings_check_module()
    requests: list[tuple[str, str, dict | None]] = []

    class FakeResponse:
        def __init__(self, payload, headers=None):
            self.payload = payload
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        body = request.data.decode("utf-8") if request.data else None
        payload = json.loads(body) if body else None
        requests.append((request.full_url, request.get_method(), payload))
        if request.full_url.endswith("/api/v1/auth/login"):
            return FakeResponse(
                {"user": {"email": "admin@example.com"}},
                headers={"Set-Cookie": "lens_session=session-1; Path=/"},
            )
        if request.full_url.endswith(
            "/api/v1/collections/col-1/goals/goal-1/analysis"
        ):
            assert request.headers["Cookie"] == "lens_session=session-1"
            return FakeResponse({"goal": {"goal_id": "goal-1"}})
        raise AssertionError(request.full_url)

    monkeypatch.setenv("LENS_CHECK_EMAIL", "admin@example.com")
    monkeypatch.setenv("LENS_CHECK_PASSWORD", "secret")
    monkeypatch.setattr(check.request_url, "urlopen", fake_urlopen)

    payload = check.fetch_goal_analysis_payload_from_api(
        api_base_url="http://127.0.0.1:8000",
        collection_id="col-1",
        goal_id="goal-1",
    )

    assert payload == {"goal": {"goal_id": "goal-1"}}
    assert requests == [
        (
            "http://127.0.0.1:8000/api/v1/auth/login",
            "POST",
            {"email": "admin@example.com", "password": "secret"},
        ),
        (
            "http://127.0.0.1:8000/api/v1/collections/col-1/goals/goal-1/analysis",
            "GET",
            None,
        ),
    ]


def test_fetch_goal_analysis_payload_from_api_reports_http_errors(monkeypatch):
    check = _load_goal_findings_check_module()

    def fake_urlopen(request, timeout):
        del request, timeout
        raise HTTPError(
            "http://127.0.0.1:8000/api/v1/collections/col-1/goals/goal-1/analysis",
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.delenv("LENS_CHECK_EMAIL", raising=False)
    monkeypatch.delenv("LENS_CHECK_PASSWORD", raising=False)
    monkeypatch.setattr(check.request_url, "urlopen", fake_urlopen)

    try:
        check.fetch_goal_analysis_payload_from_api(
            api_base_url="http://127.0.0.1:8000",
            collection_id="col-1",
            goal_id="goal-1",
        )
    except RuntimeError as exc:
        assert "GET /api/v1/collections/col-1/goals/goal-1/analysis failed" in str(exc)
        assert "401 Unauthorized" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

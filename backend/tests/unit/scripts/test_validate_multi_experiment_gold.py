from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_validator_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "validate_multi_experiment_gold.py"
    )
    spec = importlib.util.spec_from_file_location(
        "validate_multi_experiment_gold",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixture(root: Path) -> None:
    source_hash = "a" * 64
    _write(
        root / "manifest.json",
        {
            "schema_version": "multi_experiment_gold.v1",
            "papers": [{"paper_id": "P004", "sha256": source_hash}],
        },
    )
    _write(
        root / "sources.json",
        [
            {
                "source_id": "E001",
                "paper_id": "P004",
                "source_kind": "table",
                "source_ref": "table-2",
                "page": 4,
            },
            {
                "source_id": "E002",
                "paper_id": "P004",
                "source_kind": "text",
                "source_ref": "block-17",
                "page": 3,
            },
        ],
    )
    _write(
        root / "experiments.json",
        {
            "schema_version": "multi_experiment_gold.v1",
            "experiments": [
                {
                    "experiment_id": "P004-AS",
                    "series_id": "P004-AS",
                    "paper_id": "P004",
                    "sample_ids": ["S001"],
                    "condition_ids": ["T001"],
                    "outcome_ids": ["O001"],
                    "samples": [{"sample_id": "S001", "paper_id": "P004"}],
                    "conditions": [{"condition_id": "T001", "paper_id": "P004"}],
                    "outcomes": [{"outcome_id": "O001", "paper_id": "P004"}],
                    "factors": [
                        {"factor_id": "F001", "paper_id": "P004"},
                        {"factor_id": "F002", "paper_id": "P004"},
                    ],
                    "results": [{"result_id": "R001", "paper_id": "P004"}],
                }
            ],
        },
    )
    _write(
        root / "relations.json",
        {
            "schema_version": "multi_experiment_gold.v1",
            "relations": [
                {
                    "relationship_id": "REL001",
                    "paper_id": "P004",
                    "series_id": "P004-AS",
                    "factor_ids": ["F001", "F002"],
                    "result_ids": ["R001"],
                    "attribution_scope": "joint_effect",
                    "status": "resolved",
                    "source_refs": [
                        {"source_id": "E001", "supports": ["factor", "outcome"]},
                        {"source_id": "E002", "supports": ["condition"]},
                    ],
                }
            ],
        },
    )
    _write(
        root / "expected_disposition.json",
        {
            "schema_version": "multi_experiment_gold.v1",
            "papers": [
                {
                    "paper_id": "P004",
                    "evidence_disposition": "comparable_evidence",
                    "coverage": {
                        "routed_source_count": 2,
                        "extracted_source_count": 2,
                        "comparable_evidence_count": 1,
                        "failed_source_count": 0,
                        "uninspected_source_count": 0,
                    },
                }
            ],
        },
    )
    _write(
        root / "revisions.json",
        {
            "schema_version": "multi_experiment_gold.v1",
            "revisions": [
                {
                    "revision_id": "REV001",
                    "paper_id": "P004",
                    "entity_type": "relation",
                    "entity_id": "REL001",
                    "source_ids": ["E001", "E002"],
                    "source_hashes": [source_hash],
                }
            ],
        },
    )


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_valid_multi_experiment_sidecar_is_accepted(tmp_path):
    validator = _load_validator_module()
    _write_fixture(tmp_path)

    report = validator.validate_multi_experiment_gold(tmp_path)

    assert report.ok
    assert report.errors == []
    assert report.file_counts[validator.RELATIONS_FILE] == 1


def test_validator_reports_schema_fk_and_source_support_errors(tmp_path):
    validator = _load_validator_module()
    _write_fixture(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["schema_version"] = "multi_experiment_gold.v0"
    _write(tmp_path / "manifest.json", manifest)
    relations = json.loads((tmp_path / "relations.json").read_text())
    relation = relations["relations"][0]
    relation["series_id"] = "missing-series"
    relation["source_refs"] = [{"source_id": "missing-source", "supports": []}]
    _write(tmp_path / "relations.json", relations)

    report = validator.validate_multi_experiment_gold(tmp_path)
    messages = "\n".join(issue.message for issue in report.errors)

    assert not report.ok
    assert "schema_version" in messages
    assert "unknown series id" in messages
    assert "unknown source id" in messages
    assert "supports" in messages


def test_status_and_coverage_constraints_are_not_silently_downgraded(tmp_path):
    validator = _load_validator_module()
    _write_fixture(tmp_path)
    relations = json.loads((tmp_path / "relations.json").read_text())
    relation = relations["relations"][0]
    relation["status"] = "unknown"
    relation.pop("source_refs")
    _write(tmp_path / "relations.json", relations)
    disposition = json.loads((tmp_path / "expected_disposition.json").read_text())
    coverage = disposition["papers"][0]["coverage"]
    coverage["extracted_source_count"] = 3
    _write(tmp_path / "expected_disposition.json", disposition)

    report = validator.validate_multi_experiment_gold(tmp_path)
    messages = "\n".join(issue.message for issue in report.errors)

    assert not report.ok
    assert "unknown status requires a reason" in messages
    assert "unknown status requires unknown_fields" in messages
    assert "extracted sources cannot exceed routed sources" in messages


def test_revision_must_preserve_scope_and_source_provenance(tmp_path):
    validator = _load_validator_module()
    _write_fixture(tmp_path)
    revisions = json.loads((tmp_path / "revisions.json").read_text())
    revisions["revisions"].extend(
        [
            {
                "revision_id": "REV002",
                "paper_id": "P004",
                "entity_type": "relation",
                "entity_id": "REL001",
                "supersedes": "REV001",
                "source_ids": ["E002"],
            },
            {
                "revision_id": "REV003",
                "paper_id": "P004",
                "entity_type": "relation",
                "entity_id": "REL001",
                "supersedes": "REV002",
                "source_ids": ["E002"],
            },
        ]
    )
    _write(tmp_path / "revisions.json", revisions)

    report = validator.validate_multi_experiment_gold(tmp_path)
    messages = "\n".join(issue.message for issue in report.errors)

    assert not report.ok
    assert "source provenance changed across revision" in messages


def test_committed_p004_multi_experiment_fixture_is_valid():
    validator = _load_validator_module()
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "expert_gold"
        / "p004_multi_experiment"
    )
    report = validator.validate_multi_experiment_gold(fixture)

    assert report.ok, "\n".join(issue.message for issue in report.errors)


def test_p004_gold_keeps_series_boundaries_and_shared_context():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "expert_gold"
        / "p004_multi_experiment"
    )
    experiments = json.loads((fixture / "experiments.json").read_text())
    by_id = {item["series_id"]: item for item in experiments["experiments"]}

    assert set(by_id) == {"P004:X01", "P004:X02", "P004:X03"}
    assert "S002" in by_id["P004:X01"]["sample_ids"]
    assert "S002" not in by_id["P004:X03"]["sample_ids"]
    assert set(by_id["P004:X02"]["condition_ids"]) >= {
        "T004",
        "T005",
    }
    assert set(by_id["P004:X02"]["outcome_ids"]) >= {
        "O006",
        "O007",
        "O008",
        "O009",
    }
    assert set(by_id["P004:X02"]["factor_ids"]) >= {
        "F_POST_PROCESS",
        "F_MANUFACTURING_ROUTE",
    }
    assert set(by_id["P004:X03"]["factor_ids"]) >= {
        "F_POST_PROCESS",
        "F_SCAN_SPEED",
    }
    experiments = json.loads((fixture / "experiments.json").read_text())
    factors = {item["factor_id"]: item for item in experiments["factors"]}
    treatment_levels = {
        item["level"]: item for item in factors["F_POST_PROCESS"]["level_details"]
    }
    assert treatment_levels["furnace_HT"]["temperature_c"] == 1100
    assert treatment_levels["furnace_HT"]["duration_h"] == 0.5
    assert treatment_levels["HIP"]["pressure_mpa"] == 100
    assert "cooling-rate profile" in factors["F_POST_PROCESS"]["unknown_fields"]


def test_p004_gold_preserves_conflict_scope_and_claim_level_abstention():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "expert_gold"
        / "p004_multi_experiment"
    )
    experiments = json.loads((fixture / "experiments.json").read_text())
    measurements = {item["measurement_id"]: item for item in experiments["measurements"]}
    relations = json.loads((fixture / "relations.json").read_text())["relations"]
    dispositions = json.loads((fixture / "expected_disposition.json").read_text())
    sources = json.loads((fixture / "sources.json").read_text())["sources"]

    for measurement_id in ("M016", "M017", "M018"):
        measurement = measurements[measurement_id]
        assert measurement["status"] == "conflict"
        assert measurement["conflict_group"]
        assert "E014" in measurement["source_ids"]
        assert "E021" in measurement["source_ids"]

    joint = next(item for item in relations if item["relationship_id"] == "P004:X01:R01")
    assert joint["attribution_scope"] == "joint_effect"
    assert set(joint["factor_ids"]) >= {"F_LASER_POWER", "F_SCAN_SPEED"}
    assert set(joint["baseline_sample_ids"] + joint["target_sample_ids"]) == {
        "S002",
        "S008",
        "S020",
    }
    wear_source = next(item for item in sources if item["source_id"] == "E017")
    assert "0.56 mm3" in wear_source["quote"]
    assert "E017" in measurements["M025"]["source_ids"]
    elongation_finding = next(
        item for item in dispositions["expected_findings"] if item["finding_id"] == "F001"
    )
    assert "E021" in elongation_finding["source_ids"]

    abstentions = {item["abstention_id"]: item for item in dispositions["abstentions"]}
    assert abstentions["A002"]["finding_ids"] == []
    assert "isolated causal claim" in abstentions["A002"]["reason"]


def test_p004_gold_keeps_technical_failure_separate_from_scientific_absence():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "expert_gold"
        / "p004_multi_experiment"
    )
    disposition = json.loads((fixture / "expected_disposition.json").read_text())
    coverage = disposition["papers"][0]["coverage"]

    assert coverage["failed_source_count"] == 0
    assert coverage["uninspected_source_count"] == 1
    assert coverage["routed_source_count"] == 20
    assert coverage["extracted_source_count"] == 19
    assert coverage["technical_failures"] == []
    assert disposition["technical_failure_guard"]["expected_disposition_when_injected"] == "extraction_failed"

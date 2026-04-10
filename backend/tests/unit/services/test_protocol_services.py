import json

import pandas as pd
import pytest

from services.protocol_extract_service import ProtocolExtractService
from services.protocol_normalize_service import ProtocolNormalizeService
from services.protocol_validate_service import (
    PROTOCOL_STEP_PARQUET_COLUMNS,
    ProtocolValidateService,
)


def test_normalize_conditions_reports_explicit_temperature_and_duration():
    service = ProtocolNormalizeService()
    conditions = service.normalize_conditions("Annealed at 600 °C for 2 h under Ar.")

    assert conditions["temperature"]["status"] == "reported"
    assert conditions["temperature"]["unit"] == "K"
    assert conditions["temperature"]["value"] == pytest.approx(873.15)
    assert conditions["duration"]["status"] == "reported"
    assert conditions["duration"]["unit"] == "s"
    assert conditions["duration"]["value"] == pytest.approx(7200.0)
    assert conditions["atmosphere"]["value"] == "AR"


def test_normalize_conditions_marks_ambiguous_and_not_reported():
    service = ProtocolNormalizeService()
    ambiguous = service.normalize_conditions(
        "The precursor solution was stirred overnight at room temperature."
    )
    missing = service.normalize_conditions("The samples were characterized by SEM.")

    assert ambiguous["temperature"]["status"] == "ambiguous"
    assert ambiguous["duration"]["status"] == "ambiguous"
    assert missing["temperature"]["status"] == "not_reported"
    assert missing["duration"]["status"] == "not_reported"


def test_validate_step_injects_defaults_and_flags_errors():
    validator = ProtocolValidateService()
    step = validator.validate_step(
        {
            "paper_id": "p1",
            "block_id": "b1",
            "order": 0,
            "raw_text": "",
            "conditions": {},
        }
    )

    assert step["validation_status"] == "needs_review"
    assert "missing_action" in step["validation_errors"]
    assert "invalid_order" in step["validation_errors"]
    assert step["conditions"]["temperature"]["status"] == "not_reported"
    assert step["conditions"]["duration"]["status"] == "not_reported"


def test_extract_steps_builds_validated_protocol_steps():
    blocks = pd.DataFrame(
        [
            {
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "block_id": "blk-1",
                "block_type": "synthesis",
                "order": 1,
                "text": (
                    "The precursor solution was stirred overnight to ensure complete dissolution. "
                    "The mixture was annealed at 600 °C for 2 h under Ar."
                ),
            },
            {
                "paper_id": "paper-1",
                "section_id": "sec-2",
                "block_id": "blk-2",
                "block_type": "characterization",
                "order": 2,
                "text": "The samples were characterized by XRD and SEM.",
            },
        ]
    )

    service = ProtocolExtractService()
    steps = service.extract_steps(blocks)

    assert len(steps) == 3
    assert steps[0]["action"] == "stir"
    assert steps[0]["conditions"]["duration"]["status"] == "ambiguous"
    assert steps[1]["action"] == "anneal"
    assert steps[1]["conditions"]["temperature"]["status"] == "reported"
    assert steps[1]["conditions"]["duration"]["value"] == pytest.approx(7200.0)
    assert steps[2]["action"] == "characterize"
    assert steps[2]["characterization"] == [{"method": "XRD"}, {"method": "SEM"}]


def test_build_protocol_steps_table_serializes_json_columns():
    blocks = pd.DataFrame(
        [
            {
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "block_id": "blk-1",
                "block_type": "synthesis",
                "order": 1,
                "text": "The mixture was annealed at 600 °C for 2 h under Ar.",
            }
        ]
    )

    service = ProtocolExtractService()
    frame = service.build_protocol_steps_table(blocks)

    assert list(frame.columns) == PROTOCOL_STEP_PARQUET_COLUMNS
    conditions = json.loads(frame.iloc[0]["conditions_json"])
    assert conditions["temperature"]["status"] == "reported"
    assert frame.iloc[0]["validation_status"] == "valid"


def test_write_protocol_steps_parquet(tmp_path):
    blocks = pd.DataFrame(
        [
            {
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "block_id": "blk-1",
                "block_type": "synthesis",
                "order": 1,
                "text": "The mixture was annealed at 600 °C for 2 h under Ar.",
            }
        ]
    )

    service = ProtocolExtractService()
    output_path = tmp_path / "protocol_steps.parquet"
    try:
        service.write_protocol_steps_parquet(blocks, output_path)
        loaded = pd.read_parquet(output_path)
    except ImportError:
        pytest.skip("parquet engine not installed")

    assert output_path.exists()
    assert loaded.iloc[0]["action"] == "anneal"

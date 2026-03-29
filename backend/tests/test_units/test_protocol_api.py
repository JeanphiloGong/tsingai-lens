import json

import pandas as pd
import pytest

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from main import app


@pytest.fixture()
def protocol_client(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {"id": "paper-1", "title": "Composite Annealing Study"},
            {"id": "paper-2", "title": "Mechanical Validation Report"},
        ]
    )

    sections = pd.DataFrame(
        [
            {
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "section_type": "methods",
                "title": "Experimental Section",
                "text": "The samples were mixed and annealed.",
                "order": 1,
                "language": "en",
            }
        ]
    )
    blocks = pd.DataFrame(
        [
            {
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "block_id": "blk-1",
                "block_type": "synthesis",
                "text": "Mix powders and anneal at 600 C for 2 h under N2.",
                "order": 1,
            }
        ]
    )
    steps = pd.DataFrame(
        [
            {
                "step_id": "step-1",
                "paper_id": "paper-1",
                "section_id": "sec-1",
                "block_id": "blk-1",
                "block_type": "synthesis",
                "order": 1,
                "action": "Anneal mixed powders at 600 C under N2",
                "purpose": "improve crystallinity",
                "expected_output": "annealed composite",
                "materials": json.dumps([
                    {"name": "epoxy", "role": "matrix"},
                    {"name": "SiO2", "role": "filler"},
                ]),
                "conditions": json.dumps(
                    {
                        "temperature_k": 873.15,
                        "duration_s": 7200,
                        "atmosphere": "N2",
                    }
                ),
                "characterization": json.dumps([
                    {"method": "XRD"},
                    {"method": "SEM"},
                ]),
                "controls": json.dumps(["baseline_control"]),
                "evidence_refs": json.dumps([
                    {"paper_id": "paper-1", "snippet_id": "snip-1"}
                ]),
                "confidence_score": 0.91,
            },
            {
                "step_id": "step-2",
                "paper_id": "paper-2",
                "section_id": "sec-2",
                "block_id": "blk-2",
                "block_type": "characterization",
                "order": 2,
                "action": "Measure tensile strength and thermal conductivity",
                "purpose": "validate performance",
                "expected_output": "property metrics",
                "materials": json.dumps([{"name": "sample", "role": "sample"}]),
                "conditions": json.dumps({"temperature_k": 298.15}),
                "characterization": json.dumps([
                    {"method": "tensile"},
                    {"method": "thermal_conductivity"},
                ]),
                "controls": json.dumps([]),
                "evidence_refs": json.dumps([
                    {"paper_id": "paper-2", "snippet_id": "snip-2"}
                ]),
                "confidence_score": 0.85,
            },
        ]
    )

    documents.to_parquet(output_dir / "documents.parquet")
    sections.to_parquet(output_dir / "sections.parquet")
    blocks.to_parquet(output_dir / "procedure_blocks.parquet")
    steps.to_parquet(output_dir / "protocol_steps.parquet")

    client = TestClient(app)
    return client, output_dir


def test_protocol_extract_returns_summary(protocol_client):
    client, output_dir = protocol_client
    resp = client.post(
        "/retrieval/protocol/extract",
        json={"output_path": str(output_dir), "paper_ids": ["paper-1"], "limit": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["sections"] == 1
    assert body["summary"]["procedure_blocks"] == 1
    assert body["summary"]["protocol_steps"] == 1
    assert body["protocol_steps"][0]["paper_id"] == "paper-1"
    assert body["protocol_steps"][0]["paper_title"] == "Composite Annealing Study"


def test_protocol_steps_filters_by_paper(protocol_client):
    client, output_dir = protocol_client
    resp = client.get(
        "/retrieval/protocol/steps",
        params={"output_path": str(output_dir), "paper_id": "paper-2", "limit": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["step_id"] == "step-2"
    assert body["items"][0]["paper_title"] == "Mechanical Validation Report"


def test_protocol_search_returns_ranked_hits(protocol_client):
    client, output_dir = protocol_client
    resp = client.get(
        "/retrieval/protocol/search",
        params={"output_path": str(output_dir), "q": "anneal N2", "limit": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert body["items"][0]["step_id"] == "step-1"
    assert body["items"][0]["paper_title"] == "Composite Annealing Study"
    assert "anneal" in body["items"][0]["matched_terms"]


def test_protocol_sop_returns_structured_draft(protocol_client):
    client, output_dir = protocol_client
    resp = client.post(
        "/retrieval/protocol/sop",
        json={
            "output_path": str(output_dir),
            "goal": "Design a composite protocol for mechanical and thermal optimization",
            "target_properties": ["mechanical", "thermal"],
            "paper_ids": ["paper-1"],
            "max_steps": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    draft = body["sop_draft"]
    assert draft["objective"] == "Design a composite protocol for mechanical and thermal optimization"
    assert draft["steps"][0]["step_id"] == "step-1"
    assert draft["steps"][0]["paper_title"] == "Composite Annealing Study"
    assert any(item["property"] == "mechanical" for item in draft["measurement_plan"])
    assert any(item["property"] == "thermal" for item in draft["measurement_plan"])

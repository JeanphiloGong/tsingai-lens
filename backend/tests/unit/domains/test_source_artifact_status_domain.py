from __future__ import annotations

from domain.source.artifact_status import ArtifactStatusRecord


def test_artifact_status_empty_defaults_all_flags_to_false() -> None:
    record = ArtifactStatusRecord.empty(
        collection_id="col_123",
        output_path="/tmp/output",
        updated_at="2026-04-19T00:00:00+00:00",
    )

    payload = record.to_record()
    assert payload["collection_id"] == "col_123"
    assert payload["output_path"] == "/tmp/output"
    assert payload["documents_generated"] is False
    assert payload["comparison_rows_ready"] is False
    assert payload["graph_generated"] is False
    assert payload["graph_ready"] is False
    assert payload["graphml_ready"] is False


def test_artifact_status_derives_core_graph_flags_from_core_inputs() -> None:
    record = ArtifactStatusRecord.build(
        collection_id="col_demo",
        output_path="/tmp/output",
        document_profiles_generated=True,
        document_profiles_ready=True,
        evidence_cards_generated=True,
        evidence_cards_ready=False,
        comparison_rows_generated=True,
        comparison_rows_ready=False,
        updated_at="2026-04-19T00:00:00+00:00",
    )

    payload = record.to_record()
    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is True


def test_artifact_status_normalizes_legacy_payload_and_recomputes_graph_flags() -> None:
    record = ArtifactStatusRecord.from_mapping(
        {
            "collection_id": "col_demo",
            "output_path": "/tmp/output",
            "document_profiles_generated": True,
            "evidence_cards_generated": True,
            "comparison_rows_generated": True,
            "document_profiles_ready": False,
            "evidence_cards_ready": False,
            "comparison_rows_ready": False,
            "graph_generated": False,
            "graph_ready": True,
            "graphml_generated": True,
            "updated_at": "2026-04-19T00:00:00+00:00",
        },
        collection_id="col_demo",
    )

    payload = record.to_record()
    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is False
    assert payload["graphml_ready"] is True
    assert payload["documents_generated"] is False

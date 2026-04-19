from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from application.derived.protocol import pipeline_service as protocol_pipeline_service


def _write_index_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "text": "\n".join(
                    [
                        "Introduction",
                        "Composite performance was evaluated.",
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-3",
                "text": "XRD and SEM were used to characterize the powders.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _assert_protocol_artifacts(output_dir: Path) -> None:
    sections_path = output_dir / "sections.parquet"
    blocks_path = output_dir / "procedure_blocks.parquet"
    steps_path = output_dir / "protocol_steps.parquet"

    assert sections_path.exists()
    assert blocks_path.exists()
    assert steps_path.exists()

    sections = pd.read_parquet(sections_path)
    blocks = pd.read_parquet(blocks_path)
    steps = pd.read_parquet(steps_path)

    assert not sections.empty
    assert not blocks.empty
    assert not steps.empty
    assert set(sections["section_type"]) >= {"methods", "characterization"}
    assert "synthesis" in set(blocks["block_type"])
    assert "anneal" in set(steps["action"])


def test_build_protocol_artifacts_generates_all_parquet(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)
    output_dir = tmp_path / "output"
    _write_index_outputs(output_dir)

    result = protocol_pipeline_service.build_protocol_artifacts(output_dir)

    assert result.output_dir == output_dir.resolve()
    assert result.section_count >= 2
    assert result.procedure_block_count >= 3
    assert result.protocol_step_count >= 3
    _assert_protocol_artifacts(output_dir)

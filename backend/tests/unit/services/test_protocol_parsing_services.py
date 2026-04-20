from __future__ import annotations

from pathlib import Path

import pandas as pd

from application.derived.protocol import artifact_service as source_service
from application.derived.protocol import block_service
from infra.source.runtime.source_evidence import build_blocks


def test_build_document_records_uses_documents_and_text_units():
    documents = pd.DataFrame(
        [
            {"id": "doc-1", "title": "Paper A", "text": "Experimental Section\nPowders were mixed."},
            {"id": "doc-2", "title": "Paper B", "text": ""},
        ]
    )
    text_units = pd.DataFrame(
        [
            {"id": "tu-1", "text": "Powders were mixed.", "document_ids": ["doc-1"]},
            {"id": "tu-2", "text": "The slurry was stirred for 2 h.", "document_ids": ["doc-2"]},
        ]
    )

    records = source_service.build_document_records(documents, text_units)

    assert records["paper_id"].tolist() == ["doc-1", "doc-2"]
    assert records.loc[0, "text_unit_ids"] == ["tu-1"]
    assert "stirred for 2 h" in records.loc[1, "text"]


def test_persist_protocol_artifacts_uses_parquet_writer(monkeypatch, tmp_path):
    writes: list[tuple[str, list[dict[str, object]]]] = []

    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        writes.append((Path(path).name, self.to_dict(orient="records")))

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)

    blocks = pd.DataFrame([{"block_id": "b-1", "paper_id": "doc-1"}])

    block_path = source_service.persist_procedure_blocks(tmp_path, blocks)

    assert block_path.name == "procedure_blocks.parquet"
    assert [item[0] for item in writes] == ["procedure_blocks.parquet"]


def test_build_procedure_blocks_derives_scope_from_source_headings():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Composite Study",
                "text": "\n".join(
                    [
                        "Introduction",
                        "This work studies composites.",
                        "Experimental Section",
                        "Powders were mixed with epoxy and stirred for 2 h before curing.",
                        "Characterization",
                        "XRD and SEM were used to characterize the samples.",
                        "Results and Discussion",
                        "Mechanical strength increased.",
                    ]
                ),
            }
        ]
    )

    source_blocks = build_blocks(documents)
    blocks = block_service.build_procedure_blocks(source_blocks)

    assert not blocks.empty
    assert set(blocks["section_type"]) >= {"methods", "characterization"}
    assert "Experimental Section" in set(blocks["heading_path"].dropna())
    assert "Characterization" in set(blocks["heading_path"].dropna())


def test_build_procedure_blocks_keeps_extracting_without_headings():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-2",
                "title": "Fallback Paper",
                "text": "",
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor solution was stirred for 12 h at 80 C and then dried.",
                "document_ids": ["doc-2"],
            },
            {
                "id": "tu-2",
                "text": "XRD and SEM were used to characterize the final powders.",
                "document_ids": ["doc-2"],
            },
        ]
    )

    source_blocks = build_blocks(documents, text_units)
    blocks = block_service.build_procedure_blocks(source_blocks)

    assert not blocks.empty
    assert set(blocks["block_type"]) >= {"synthesis", "characterization"}
    assert blocks["heading_path"].isna().all()


def test_build_procedure_blocks_splits_major_method_types():
    source_blocks = pd.DataFrame(
        [
            {
                "block_id": "src-1",
                "document_id": "doc-1",
                "block_type": "paragraph",
                "text": "\n".join(
                    [
                        "Li2CO3 and TiO2 were mixed in ethanol and stirred for 2 h.",
                        "The precipitate was washed, dried at 80 C, and annealed at 700 C.",
                        "XRD and SEM were used to characterize the powders.",
                        "Tensile and thermal conductivity tests were performed on the cured samples.",
                    ]
                ),
                "block_order": 1,
                "heading_path": "Experimental Section",
                "text_unit_ids": ["tu-1"],
            }
        ]
    )

    blocks = block_service.build_procedure_blocks(source_blocks)

    assert blocks["block_type"].tolist() == [
        "synthesis",
        "post_treatment",
        "characterization",
        "property_test",
    ]
    assert blocks["order"].tolist() == [1, 2, 3, 4]
    assert set(blocks["section_type"]) == {"methods"}

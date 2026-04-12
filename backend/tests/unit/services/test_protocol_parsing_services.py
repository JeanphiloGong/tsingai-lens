from __future__ import annotations

from pathlib import Path

import pandas as pd

from application import protocol_block_service as block_service
from application import protocol_section_service as section_service
from application import protocol_source_service as source_service


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

    sections = pd.DataFrame([{"section_id": "s-1", "paper_id": "doc-1"}])
    blocks = pd.DataFrame([{"block_id": "b-1", "paper_id": "doc-1"}])

    section_path = source_service.persist_sections(tmp_path, sections)
    block_path = source_service.persist_procedure_blocks(tmp_path, blocks)

    assert section_path.name == "sections.parquet"
    assert block_path.name == "procedure_blocks.parquet"
    assert [item[0] for item in writes] == ["sections.parquet", "procedure_blocks.parquet"]


def test_build_sections_extracts_headed_methods_and_characterization():
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

    sections = section_service.build_sections(documents)

    assert sections["section_type"].tolist() == ["methods", "characterization"]
    assert sections["heading"].tolist() == ["Experimental Section", "Characterization"]
    assert sections["source_mode"].tolist() == ["heading", "heading"]


def test_build_sections_falls_back_to_text_units_when_no_heading():
    documents = pd.DataFrame(
        [
            {
                "id": "doc-2",
                "title": "Fallback Paper",
                "text": "This paper focuses on the resulting properties and applications.",
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

    sections = section_service.build_sections(documents, text_units)

    assert not sections.empty
    assert set(sections["section_type"]) == {"methods", "characterization"}
    assert set(sections["source_mode"]) == {"text_unit_fallback"}


def test_build_procedure_blocks_splits_major_method_types():
    sections = pd.DataFrame(
        [
            {
                "section_id": "sec-1",
                "paper_id": "doc-1",
                "title": "Composite Study",
                "section_type": "methods",
                "heading": "Experimental Section",
                "text": "\n".join(
                    [
                        "Li2CO3 and TiO2 were mixed in ethanol and stirred for 2 h.",
                        "The precipitate was washed, dried at 80 C, and annealed at 700 C.",
                        "XRD and SEM were used to characterize the powders.",
                        "Tensile and thermal conductivity tests were performed on the cured samples.",
                    ]
                ),
                "order": 1,
                "source_mode": "heading",
                "text_unit_ids": ["tu-1"],
                "confidence": 0.95,
            }
        ]
    )

    blocks = block_service.build_procedure_blocks(sections)

    assert blocks["block_type"].tolist() == [
        "synthesis",
        "post_treatment",
        "characterization",
        "property_test",
    ]
    assert blocks["order"].tolist() == [1, 2, 3, 4]

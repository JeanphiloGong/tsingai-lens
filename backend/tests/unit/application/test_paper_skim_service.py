from types import SimpleNamespace

from application.core.objectives.paper_skim_service import PaperSkimService
from domain.core import PaperSkim


def test_paper_skim_record_keeps_only_the_stable_source_link():
    skim = PaperSkim.from_mapping({"document_id": "paper-1"})

    record = skim.to_record()

    assert record["document_id"] == "paper-1"
    assert "title" not in record
    assert "source_filename" not in record


def test_paper_skim_payload_keeps_full_bounded_text_preview():
    service = PaperSkimService()
    source_text = "A" * 1200

    payload = service._build_paper_skim_payload(
        collection_id="collection-test",
        document=SimpleNamespace(
            document_id="paper-1",
            title="Density study",
            text=source_text,
        ),
        profile=None,
        blocks=[
            SimpleNamespace(
                text=source_text,
                block_type="paragraph",
                block_order=1,
                heading_path="Abstract",
            )
        ],
        tables=[],
        figures=[],
    )

    assert payload["text_preview"] == source_text

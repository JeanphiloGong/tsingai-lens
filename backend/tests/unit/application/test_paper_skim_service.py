from types import SimpleNamespace

from application.core.objectives.paper_skim_service import PaperSkimService


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

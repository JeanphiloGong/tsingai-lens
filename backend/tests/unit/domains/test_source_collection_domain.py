from dataclasses import replace

from domain.source import Collection, Document


def _document(document_id: str = "doc_1") -> Document:
    return Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="stored-paper.pdf",
        storage_key="col_1/input/stored-paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=123,
        created_at="2026-08-27T00:00:00+00:00",
    )


def test_collection_is_created_without_documents() -> None:
    collection = Collection.create(
        collection_id="col_1",
        owner_user_id="user_1",
        name="LPBF papers",
        description="Current evidence set",
        now_iso="2026-08-27T00:00:00+00:00",
    )

    assert collection.documents == ()
    assert collection.paper_count == 0
    assert collection.to_record()["documents"] == []


def test_collection_directly_contains_current_documents() -> None:
    document = _document()
    collection = replace(
        Collection.create(
            collection_id="col_1",
            owner_user_id="user_1",
            name="LPBF papers",
            description=None,
            now_iso="2026-08-27T00:00:00+00:00",
        ),
        status="ready",
        documents=(document,),
    )

    assert collection.paper_count == 1
    assert collection.documents == (document,)
    assert collection.to_record()["documents"] == [document.to_record()]

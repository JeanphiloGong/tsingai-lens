from __future__ import annotations

import base64
from hashlib import sha256
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from tests.support.collection_service import build_test_collection_service
from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.source.document_markdown_service import DocumentMarkdownService
from controllers.core import documents as documents_controller
from domain.core import DocumentProfile
from domain.source import (
    Document,
    source_documents_from_records,
)
from infra.source.ingestion.normalized_import import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    NormalizedImportSourceMetadata,
)
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemorySourceArtifactRepository,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _store_document_profiles(
    document_profile_service: DocumentProfileService,
    collection_id: str,
    profiles: list[dict],
) -> None:
    for row in profiles:
        await document_profile_service.document_profile_repository.replace(
            DocumentProfile.from_mapping(row)
        )


async def _store_source_documents(repository, collection_id, documents) -> None:
    for document in documents:
        await repository.replace_document(collection_id, document)


@pytest.fixture()
def document_services(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    source_repository = MemorySourceArtifactRepository()
    document_profile_service = DocumentProfileService(
        collection_service,
        source_artifact_repository=source_repository,
        document_profile_repository=MemoryDocumentProfileRepository(),
    )
    document_markdown_service = DocumentMarkdownService(
        collection_service,
        source_artifact_repository=source_repository,
    )

    return (
        collection_service,
        document_profile_service,
        document_markdown_service,
    )


def _document_request(document_services):
    (
        collection_service,
        document_profile_service,
        document_markdown_service,
    ) = document_services
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                collection_service=collection_service,
                document_profile_service=document_profile_service,
                document_markdown_service=document_markdown_service,
            )
        )
    )


async def test_documents_route_returns_409_when_profiles_are_not_ready(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.list_collection_document_profiles(
                record["collection_id"],
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_profiles_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


async def test_documents_route_returns_404_for_missing_collection(document_services):
    (
        _collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.list_collection_document_profiles(
                "col_missing",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


async def test_documents_route_forwards_profile_search_and_pagination(document_services):
    (
        collection_service,
        document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Searchable Collection")
    collection_id = record["collection_id"]
    await _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Laser paper one",
                "source_filename": "one.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            },
            {
                "document_id": "paper-2",
                "collection_id": collection_id,
                "title": "Laser paper two",
                "source_filename": "two.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.89,
            },
            {
                "document_id": "paper-3",
                "collection_id": collection_id,
                "title": "Unrelated review",
                "source_filename": "review.pdf",
                "doc_type": "review",
                "parsing_warnings": [],
                "confidence": 0.8,
            },
        ],
    )

    payload = await documents_controller.list_collection_document_profiles(
        collection_id,
        _document_request(document_services),
        limit=1,
        offset=1,
        query="laser",
    )

    assert payload.total == 2
    assert payload.count == 1
    assert payload.items[0].document_id == "paper-2"


async def test_document_profile_route_returns_single_profile(document_services):
    (
        collection_service,
        document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Single Profile Collection"
    )
    collection_id = record["collection_id"]
    await _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    payload = await documents_controller.get_collection_document_profile(
            collection_id,
            "paper-1",
            _document_request(document_services),
        )

    assert payload.document_id == "paper-1"
    assert payload.collection_id == collection_id
    assert payload.title == "Single Paper"


async def test_document_profile_route_normalizes_invalid_profile_status_values(
    document_services,
):
    (
        collection_service,
        document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Invalid Profile Collection"
    )
    collection_id = record["collection_id"]
    await _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "research_article",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    payload = await documents_controller.get_collection_document_profile(
            collection_id,
            "paper-1",
            _document_request(document_services),
        )

    assert payload.doc_type == "experimental"


async def test_document_content_route_uses_stable_block_locator(
    document_services,
):
    (
        collection_service,
        document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Document Locator Collection"
    )
    collection_id = record["collection_id"]
    await _store_source_documents(
        document_profile_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Locator Paper",
                    "source_filename": "paper-1.pdf",
                    "text": "The optimized sample reached 940 MPa. Missing locator paragraph.",
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-result",
                    "block_type": "paragraph",
                    "heading_path": "Results",
                    "heading_level": 1,
                    "block_order": 1,
                    "text": "The optimized sample reached 940 MPa.",
                    "text_unit_ids": [],
                    "page": 6,
                },
            ],
        ),
    )
    await _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Locator Paper",
                "source_filename": "paper-1.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    payload = await documents_controller.get_collection_document_content(
            collection_id,
            "paper-1",
            _document_request(document_services),
        )

    first = payload.blocks[0]
    assert first.block_id == "blk-result"
    assert first.page == 6
    assert set(first.model_dump()) == {
        "block_id",
        "block_type",
        "heading_path",
        "heading_level",
        "order",
        "text",
        "text_unit_ids",
        "page",
    }


async def test_document_markdown_route_returns_markdown_projection(document_services):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Markdown Route Collection"
    )
    collection_id = record["collection_id"]
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Markdown Paper",
                    "text": "Abstract\nThe sample reached 12 mS/cm.",
                    "metadata": {
                        "source_filename": "markdown-paper.pdf",
                        "source_parser": "docling",
                    },
                }
            ],
            blocks=[
                {
                    "document_id": "paper-1",
                    "block_id": "blk-abstract",
                    "block_type": "heading",
                    "heading_level": 1,
                    "block_order": 1,
                    "text": "Abstract",
                    "page": 1,
                },
                {
                    "document_id": "paper-1",
                    "block_id": "blk-result",
                    "block_type": "paragraph",
                    "heading_path": "Abstract",
                    "block_order": 2,
                    "text": "The sample reached 12 mS/cm.",
                    "text_unit_ids": ["tu-result"],
                    "page": 1,
                },
            ],
        ),
    )

    payload = await documents_controller.get_collection_document_markdown(
            collection_id,
            "paper-1",
            _document_request(document_services),
        )

    assert payload.collection_id == collection_id
    assert payload.document_id == "paper-1"
    assert payload.title == "Markdown Paper"
    assert payload.source_filename == "markdown-paper.pdf"
    assert payload.parser == "docling"
    assert "# Markdown Paper" in payload.markdown
    assert "## Abstract" in payload.markdown
    assert "The sample reached 12 mS/cm." in payload.markdown
    source_map = {item.artifact_id: item for item in payload.source_map}
    assert source_map["blk-result"].text_unit_ids == ["tu-result"]


async def test_document_markdown_route_returns_409_when_markdown_is_not_ready(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Markdown Pending Collection"
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_markdown(
                record["collection_id"],
                "paper-1",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_markdown_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


async def test_document_source_route_streams_current_collection_document(document_services):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Source File Collection")
    collection_id = record["collection_id"]
    payload = b"%PDF-1.4\nfixture\n"
    documents = await collection_service.import_normalized_batch(
        collection_id,
        NormalizedImportBatch(
            documents=(
                NormalizedImportDocument(
                    source_document_id="paper-1",
                    origin_channel="upload",
                    original_filename="paper-1.pdf",
                    stored_filename="paper-1.pdf",
                    media_type="application/pdf",
                    storage_payload_base64=base64.b64encode(payload).decode("ascii"),
                ),
            ),
            text_units=(),
            source_metadata=NormalizedImportSourceMetadata(
                channel="upload",
                adapter_name="upload",
                ingested_at="2026-07-19T00:00:00+00:00",
            ),
        ),
    )

    response = await documents_controller.get_collection_document_source(
            collection_id,
            documents[0]["document_id"],
            _document_request(document_services),
        )

    assert response.body == payload
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


async def test_document_source_route_resolves_profile_document_id_by_source_filename(
    document_services,
):
    (
        collection_service,
        document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Profile Source File Collection"
    )
    collection_id = record["collection_id"]
    payload = b"%PDF-1.4\nprofile fixture\n"
    await _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "profile-hash-doc",
                "collection_id": collection_id,
                "title": "Profile Paper",
                "source_filename": "paper.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    await collection_service.import_normalized_batch(
        collection_id,
        NormalizedImportBatch(
            documents=(
                NormalizedImportDocument(
                    source_document_id="srcdoc-from-upload",
                    origin_channel="upload",
                    original_filename="paper.pdf",
                    stored_filename="stored-paper.pdf",
                    media_type="application/pdf",
                    storage_payload_base64=base64.b64encode(payload).decode("ascii"),
                ),
            ),
            text_units=(),
            source_metadata=NormalizedImportSourceMetadata(
                channel="upload",
                adapter_name="upload",
                ingested_at="2026-07-19T00:00:00+00:00",
            ),
        ),
    )

    response = await documents_controller.get_collection_document_source(
            collection_id,
            "profile-hash-doc",
            _document_request(document_services),
        )

    assert response.body == payload
    assert response.media_type == "application/pdf"


async def test_document_source_route_returns_404_when_document_is_missing(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Missing Source Collection")

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_source(
                record["collection_id"],
                "paper-1",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "document_not_found"
    assert exc.detail["document_id"] == "paper-1"


async def test_document_source_route_rejects_path_outside_collection(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Unsafe Source Collection")
    collection_id = record["collection_id"]
    unsafe_document = Document(
        document_id="paper-1",
        original_filename="paper-1.pdf",
        stored_filename="outside.pdf",
        storage_key="../outside.pdf",
        sha256=sha256(b"outside").hexdigest(),
        media_type="application/pdf",
        status="stored",
        size_bytes=len(b"outside"),
        created_at="2026-07-19T00:00:00+00:00",
    )
    await collection_service.repository.add_documents(
        collection_id,
        (unsafe_document,),
        updated_at=unsafe_document.created_at,
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_source(
                collection_id,
                "paper-1",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_source_path_invalid"
    assert "outside.pdf" not in str(exc.detail)


async def test_document_source_route_rejects_another_collections_storage_key(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        _markdown_service,
    ) = document_services
    first = await collection_service.create_collection(name="First source collection")
    second = await collection_service.create_collection(name="Second source collection")
    payload = b"%PDF-1.4\nsecond collection\n"
    storage_key = f"{second['collection_id']}/input/paper-2.pdf"
    digest = sha256(payload).hexdigest()
    collection_service.object_store.write(storage_key, payload, digest)
    foreign_document = Document(
        document_id="paper-1",
        original_filename="paper-2.pdf",
        stored_filename="paper-2.pdf",
        storage_key=storage_key,
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=len(payload),
        created_at="2026-07-19T00:00:00+00:00",
    )
    await collection_service.repository.add_documents(
        first["collection_id"],
        (foreign_document,),
        updated_at=foreign_document.created_at,
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_source(
                first["collection_id"],
                "paper-1",
                _document_request(document_services),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "document_source_path_invalid"


async def test_document_figure_image_route_streams_extracted_asset(document_services):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    record = await collection_service.create_collection(name="Figure Image Collection")
    collection_id = record["collection_id"]
    content = b"\x89PNG\r\n\x1a\nfixture\n"
    asset_sha256 = sha256(content).hexdigest()
    storage_key = collection_service.write_figure_asset(
        collection_id,
        "build-figure",
        "image_assets/fig-1.png",
        content,
        asset_sha256,
    )
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "figure_label": "Fig. 1",
                    "caption_text": "Fig. 1. Microstructure.",
                    "image_path": storage_key,
                    "image_mime_type": "image/png",
                    "asset_sha256": asset_sha256,
                    "image_size_bytes": len(content),
                }
            ],
        ),
    )

    response = await documents_controller.get_collection_document_figure_image(
            collection_id,
            "paper-1",
            "fig-1",
            _document_request(document_services),
        )

    assert response.body == content
    assert response.media_type == "image/png"
    assert response.headers["content-disposition"] == 'inline; filename="fig-1.png"'


async def test_document_figure_image_route_rejects_figure_from_other_document(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Cross Document Figure Collection"
    )
    collection_id = record["collection_id"]
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[
                {"id": "paper-1", "title": "Paper 1", "text": ""},
                {"id": "paper-2", "title": "Paper 2", "text": ""},
            ],
            figures=[
                {
                    "document_id": "paper-2",
                    "figure_id": "fig-2",
                    "figure_order": 1,
                    "image_path": "image_assets/fig-2.png",
                    "image_mime_type": "image/png",
                }
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_figure_image(
                collection_id,
                "paper-1",
                "fig-2",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "figure_not_found"
    assert exc.detail["document_id"] == "paper-1"
    assert exc.detail["figure_id"] == "fig-2"


async def test_document_figure_image_route_rejects_path_outside_collection(
    document_services,
    tmp_path,
):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Unsafe Figure Image Collection"
    )
    collection_id = record["collection_id"]
    outside_path = tmp_path / "outside.png"
    outside_path.write_bytes(b"outside")
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "image_path": str(outside_path),
                    "image_mime_type": "image/png",
                }
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_figure_image(
                collection_id,
                "paper-1",
                "fig-1",
                _document_request(document_services),
            )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "figure_image_path_invalid"
    assert "outside.png" not in str(exc.detail)


async def test_document_figure_image_route_rejects_another_collections_object_key(
    document_services,
):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    first = await collection_service.create_collection(name="First Figure Collection")
    second = await collection_service.create_collection(name="Second Figure Collection")
    content = b"figure"
    digest = sha256(content).hexdigest()
    foreign_key = collection_service.write_figure_asset(
        second["collection_id"],
        "build-figure",
        "image_assets/figure.png",
        content,
        digest,
    )
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        first["collection_id"],
        source_documents_from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "image_path": foreign_key,
                    "image_mime_type": "image/png",
                    "asset_sha256": digest,
                    "image_size_bytes": len(content),
                }
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_figure_image(
                first["collection_id"],
                "paper-1",
                "fig-1",
                _document_request(document_services),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "figure_image_path_invalid"


@pytest.mark.parametrize("failure", ["missing", "hash_mismatch"])
async def test_document_figure_image_route_reports_unavailable_object_bytes(
    document_services,
    failure,
):
    (
        collection_service,
        _document_profile_service,
        markdown_service,
    ) = document_services
    record = await collection_service.create_collection(
        name="Unavailable Figure Collection"
    )
    collection_id = record["collection_id"]
    content = b"figure"
    digest = sha256(content).hexdigest()
    storage_key = collection_service.write_figure_asset(
        collection_id,
        "build-figure",
        "image_assets/figure.png",
        content,
        digest,
    )
    if failure == "missing":
        collection_service.object_store.delete(storage_key)
    else:
        (collection_service.root_dir / storage_key).write_bytes(b"corrupt")
    await _store_source_documents(
        markdown_service.source_artifact_repository,
        collection_id,
        source_documents_from_records(
            documents=[{"id": "paper-1", "title": "Figure Paper", "text": ""}],
            figures=[
                {
                    "document_id": "paper-1",
                    "figure_id": "fig-1",
                    "figure_order": 1,
                    "image_path": storage_key,
                    "image_mime_type": "image/png",
                    "asset_sha256": digest,
                    "image_size_bytes": len(content),
                }
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents_controller.get_collection_document_figure_image(
                collection_id,
                "paper-1",
                "fig-1",
                _document_request(document_services),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "figure_image_unavailable"

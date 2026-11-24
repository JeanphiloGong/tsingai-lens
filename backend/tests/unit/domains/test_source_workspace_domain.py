from dataclasses import fields

from domain.source import Workspace, Document


def test_source_business_models_do_not_own_storage_records() -> None:
    workspace = Workspace(
        workspace_id="col_1",
        owner_user_id="user_1",
        name="LPBF papers",
        description="Current evidence set",
        status="idle",
    )
    document = Document(
        document_id="doc_1",
        original_filename="paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=123,
    )

    assert workspace.owner_user_id == "user_1"
    assert document.sha256 == "a" * 64
    storage_fields = {"stored_filename", "storage_key", "created_at", "updated_at"}
    assert not storage_fields.intersection(field.name for field in fields(workspace))
    assert not storage_fields.intersection(field.name for field in fields(document))

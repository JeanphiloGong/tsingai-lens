import pytest
from controllers.source.collection_routes import CollectionCreateRequest
from pydantic import ValidationError


def test_collection_create_request_normalizes_user_text() -> None:
    request = CollectionCreateRequest(
        name="  LPBF papers  ",
        description="   ",
    )

    assert request.name == "LPBF papers"
    assert request.description is None


def test_collection_create_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        CollectionCreateRequest(name="   ")

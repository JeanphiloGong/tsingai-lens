import pytest
from pydantic import ValidationError

from controllers.schemas.source.collection import CollectionCreateRequest


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

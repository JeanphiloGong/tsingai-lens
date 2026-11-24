import pytest
from controllers.source.workspace_routes import WorkspaceCreateRequest
from pydantic import ValidationError


def test_workspace_create_request_normalizes_user_text() -> None:
    request = WorkspaceCreateRequest(
        name="  LPBF papers  ",
        description="   ",
    )

    assert request.name == "LPBF papers"
    assert request.description is None


def test_workspace_create_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreateRequest(name="   ")

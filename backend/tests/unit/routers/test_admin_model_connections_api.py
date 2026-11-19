import pytest
from pydantic import ValidationError
from controllers.models.admin_connection_routes import CreateConnectionRequest, UpdateConnectionRequest


def test_request_models_distinguish_omitted_null_and_replacement_keys():
    assert "api_key" not in UpdateConnectionRequest(expected_version=1, enabled=True).model_fields_set
    assert UpdateConnectionRequest(expected_version=1, api_key=None).model_dump(exclude_unset=True)["api_key"] is None
    assert UpdateConnectionRequest(expected_version=1, api_key="new").api_key == "new"
    for change in ({"api_key":""},{"api_key":"bad\nkey"},{"enabled":None},{"priority":True},{"base_url":"http://localhost"}):
        with pytest.raises(ValidationError): UpdateConnectionRequest(expected_version=1, **change)
    for address in ("file:///tmp/key","https://name:key@host/v1","https://host/v1?key=secret"):
        with pytest.raises(ValidationError): CreateConnectionRequest(display_name="Lab",model="test",base_url=address)

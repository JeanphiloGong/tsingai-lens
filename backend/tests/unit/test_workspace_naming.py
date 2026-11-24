from infra.persistence.postgres.models.workspace import WorkspaceORM
from domain.source.workspace import Workspace


def test_workspace_is_the_persisted_ownership_boundary() -> None:
    assert WorkspaceORM.__tablename__ == "workspaces"
    assert WorkspaceORM.workspace_id.key == "workspace_id"

    workspace = Workspace(
        workspace_id="workspace_1",
        owner_user_id="user_1",
        name="Research",
        description=None,
        status="idle",
    )
    assert workspace.workspace_id == "workspace_1"

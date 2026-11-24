from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from config import DATA_DIR


@dataclass(frozen=True)
class WorkspacePaths:
    workspace_dir: Path
    input_dir: Path
    output_dir: Path


class FileWorkspace:
    """Filesystem workspace for workspace-local files and outputs."""

    backend_name = "file"

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "workspaces")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get_paths(self, workspace_id: str) -> WorkspacePaths:
        workspace_dir = self.root_dir / workspace_id
        return WorkspacePaths(
            workspace_dir=workspace_dir,
            input_dir=workspace_dir / "input",
            output_dir=workspace_dir / "output",
        )

    def create_workspace_dirs(self, workspace_id: str) -> WorkspacePaths:
        paths = self.get_paths(workspace_id)
        paths.workspace_dir.mkdir(parents=True, exist_ok=True)
        paths.input_dir.mkdir(parents=True, exist_ok=True)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        return paths

    def delete_workspace_dir(self, workspace_id: str) -> None:
        shutil.rmtree(self.get_paths(workspace_id).workspace_dir)


# Initialized by main.lifespan; workers continue to construct their own workspace.
Workspace: FileWorkspace

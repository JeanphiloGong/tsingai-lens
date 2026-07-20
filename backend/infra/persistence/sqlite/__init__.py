"""Legacy SQLite Source persistence used by isolated migration tests."""

from infra.persistence.sqlite.source_artifact_repository import (
    SqliteSourceArtifactRepository,
)

__all__ = [
    "SqliteSourceArtifactRepository",
]

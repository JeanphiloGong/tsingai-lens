"""PostgreSQL ORM model registry."""

from infra.persistence.postgres.models.auth import AuthSession, AuthUser
from infra.persistence.postgres.models.build import (
    ArtifactVersion,
    BuildStage,
    CollectionActiveBuild,
    CollectionBuild,
    Task,
)
from infra.persistence.postgres.models.collection import (
    Collection,
    CollectionFile,
    CollectionHandoff,
    CollectionImport,
    CollectionImportDocument,
    StoredObject,
)
from infra.persistence.postgres.models.document import (
    CollectionDocument,
    Document,
    DocumentVersion,
)
from infra.persistence.postgres.models.source import (
    SourceBlock,
    SourceBlockTextUnit,
    SourceDocument,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    SourceTextUnitDocument,
)

__all__ = [
    "ArtifactVersion",
    "AuthSession",
    "AuthUser",
    "BuildStage",
    "Collection",
    "CollectionActiveBuild",
    "CollectionBuild",
    "CollectionDocument",
    "CollectionFile",
    "CollectionHandoff",
    "CollectionImport",
    "CollectionImportDocument",
    "Document",
    "DocumentVersion",
    "StoredObject",
    "SourceBlock",
    "SourceBlockTextUnit",
    "SourceDocument",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "SourceTextUnitDocument",
    "Task",
]

"""Deprecated import path for the unified document preparation model."""

from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow

DocumentSource = DocumentPreparationRow

__all__ = ["DocumentSource"]

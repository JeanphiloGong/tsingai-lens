"""Deprecated import path for the unified document preparation model."""

from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow

DocumentProfileRow = DocumentPreparationRow

__all__ = ["DocumentProfileRow"]

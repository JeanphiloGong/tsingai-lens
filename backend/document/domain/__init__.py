"""Document domain objects."""

from .document import Document
from .profile import DocumentProfile, DocumentType
from .source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
    assemble_source_documents,
    render_markdown_table,
)

__all__ = [
    "Document",
    "DocumentProfile",
    "DocumentType",
    "SourceBlock",
    "SourceDocument",
    "SourceFigure",
    "SourceTable",
    "assemble_source_documents",
    "render_markdown_table",
]

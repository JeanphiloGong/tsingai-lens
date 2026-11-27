"""Document preparation Pipeline node definition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from document.application.preparation import DocumentPreparation


@dataclass(frozen=True)
class Node:
    name: str
    dependencies: tuple[str, ...]
    run: Callable[..., Awaitable[object]]


def document_preparation_nodes(
    service: DocumentPreparation,
) -> tuple[Node, ...]:
    return (
        Node("source_parsing", (), service.parse_source),
        Node("document_profile", ("source_parsing",), service.save_profile),
    )

"""Reuse and targeted reread rules for PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from inspect import isawaitable
from typing import Awaitable, Callable, Iterable

from application.repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)
from domain.core.paper_experiment import PaperExperimentRevision


@dataclass(frozen=True)
class PaperExperimentReadRequest:
    """The smallest scientific scope needed by one analysis read."""

    document_id: str
    outcomes: tuple[str, ...] = ()
    required_context_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("experiment read requires document_id")
        object.__setattr__(
            self,
            "outcomes",
            _unique_terms(self.outcomes),
        )
        object.__setattr__(
            self,
            "required_context_names",
            _unique_terms(self.required_context_names),
        )


@dataclass(frozen=True)
class PaperExperimentReadResult:
    stored: StoredPaperExperimentRevision
    created_revision: bool
    reread_required: bool


RevisionBuilder = Callable[
    [StoredPaperExperimentRevision | None, int],
    PaperExperimentRevision | Awaitable[PaperExperimentRevision],
]


class PaperExperimentReuseService:
    """Choose a fixed revision, creating only a bounded successor when needed."""

    def __init__(self, repository: PaperExperimentRepository) -> None:
        self.repository = repository

    async def read_or_reread(
        self,
        request: PaperExperimentReadRequest,
        *,
        build_revision: RevisionBuilder,
        created_by: str | None = None,
        created_at: datetime | None = None,
    ) -> PaperExperimentReadResult:
        candidates = await self.repository.list_latest_for_document(request.document_id)
        latest = next(
            (
                item
                for item in candidates
                if item.revision.document_id == request.document_id
                and _has_required_content(item.revision, request)
            ),
            None,
        )
        if latest is not None:
            return PaperExperimentReadResult(
                stored=latest,
                created_revision=False,
                reread_required=False,
            )

        existing = next(
            (
                item
                for item in candidates
                if item.revision.document_id == request.document_id
            ),
            None,
        )
        version = (
            existing.revision.experiment_version + 1 if existing is not None else 1
        )
        revision = build_revision(existing, version)
        if isawaitable(revision):
            revision = await revision
        _validate_successor(existing, revision, request.document_id, version)
        stored = await self.repository.add_revision(
            revision,
            created_by=created_by,
            created_at=created_at,
        )
        return PaperExperimentReadResult(
            stored=stored,
            created_revision=True,
            reread_required=existing is not None,
        )


def _has_required_content(
    revision: PaperExperimentRevision,
    request: PaperExperimentReadRequest,
) -> bool:
    available_outcomes = {
        item.outcome.casefold() for item in revision.measurements
    }
    if not set(request.outcomes).issubset(available_outcomes):
        return False
    if not request.required_context_names:
        return True
    context_names: set[str] = set()
    for variant in revision.variants:
        context_names.update(
            item.name.casefold()
            for item in (*variant.subject_attributes, *variant.intervention_attributes, *variant.state)
        )
    for test in revision.test_conditions:
        context_names.update(item.name.casefold() for item in test.parameters)
    return set(request.required_context_names).issubset(context_names)


def _validate_successor(
    existing: StoredPaperExperimentRevision | None,
    revision: PaperExperimentRevision,
    document_id: str,
    expected_version: int,
) -> None:
    if revision.document_id != document_id:
        raise ValueError("reread revision belongs to another document")
    if revision.experiment_version != expected_version:
        raise ValueError("reread revision must use the next experiment version")
    if existing is not None:
        if revision.experiment_id != existing.revision.experiment_id:
            raise ValueError("reread must preserve experiment identity")
    elif not revision.experiment_id.strip():
        raise ValueError("new experiment requires experiment identity")


def _unique_terms(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value).strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(key)
    return tuple(result)


__all__ = [
    "PaperExperimentReadRequest",
    "PaperExperimentReadResult",
    "PaperExperimentReuseService",
]

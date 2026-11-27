from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ResearchObjective:
    workspace_id: str
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    variables: tuple[str, ...]
    outcomes: tuple[str, ...]
    mechanisms: tuple[str, ...]
    constraints: tuple[str, ...]
    requested_comparator: str | None
    seed_document_ids: tuple[str, ...]
    excluded_document_ids: tuple[str, ...]
    confidence: float
    reason: str | None
    source_relationship_ids: tuple[str, ...] = ()
    parent_objective_id: str | None = None
    parent_analysis_version: int | None = None
    derivation_basis: tuple[dict[str, Any], ...] = ()
    rank: int | None = None
    confirmation_status: str = "candidate"
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    origin: str = "system_discovered"
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("research objective requires workspace_id")
        if not self.objective_id:
            raise ValueError("research objective requires objective_id")
        if not self.question:
            raise ValueError("research objective requires question")
        if not self.variables:
            raise ValueError("research objective requires at least one variable")
        if not self.outcomes:
            raise ValueError("research objective requires at least one outcome")
        if self.rank is not None and self.rank < 1:
            raise ValueError("research objective rank must be a positive integer")
        primary_terms = {
            value.casefold() for value in (*self.variables, *self.outcomes)
        }
        duplicate_mechanisms = primary_terms & {
            value.casefold() for value in self.mechanisms
        }
        if duplicate_mechanisms:
            raise ValueError(
                "objective mechanisms duplicate variables or outcomes: "
                + ", ".join(sorted(duplicate_mechanisms))
            )
        duplicate_constraints = primary_terms & {
            value.casefold() for value in self.constraints
        }
        if duplicate_constraints:
            raise ValueError(
                "objective constraints duplicate variables or outcomes: "
                + ", ".join(sorted(duplicate_constraints))
            )
        creator_values = (
            self.created_by_user_id,
            self.created_by_tool_call_id,
        )
        if self.origin == "chat_assisted" and not all(creator_values):
            raise ValueError(
                "chat-assisted objective requires user and tool-call provenance"
            )
        if self.origin == "system_discovered" and any(creator_values):
            raise ValueError(
                "system-discovered objective cannot have Chat creator provenance"
            )
        parent_objective_id = self.parent_objective_id
        if parent_objective_id is not None and parent_objective_id == self.objective_id:
            raise ValueError("objective cannot derive from itself")
        if (parent_objective_id is None) != (self.parent_analysis_version is None):
            raise ValueError(
                "derived objective requires parent objective and analysis version"
            )
        if self.parent_analysis_version is not None and self.parent_analysis_version < 1:
            raise ValueError("parent_analysis_version must be a positive integer")
        basis = self.derivation_basis
        if basis and parent_objective_id is None:
            raise ValueError("derivation basis requires a parent objective")
        basis_refs = [(item["kind"], item["reference_id"]) for item in basis]
        if len(basis_refs) != len(set(basis_refs)):
            raise ValueError("objective derivation basis references must be unique")
        overlap = set(self.seed_document_ids) & set(self.excluded_document_ids)
        if overlap:
            raise ValueError(
                "objective seed and excluded documents overlap: "
                + ", ".join(sorted(overlap))
            )
        for field_name, version in (
            ("active_analysis_version", self.active_analysis_version),
            ("published_analysis_version", self.published_analysis_version),
        ):
            if version is not None and version < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            self.published_analysis_version is not None
            and self.active_analysis_version is None
        ):
            raise ValueError("published analysis requires an active analysis version")
        if (
            self.published_analysis_version is not None
            and self.active_analysis_version is not None
            and self.published_analysis_version > self.active_analysis_version
        ):
            raise ValueError("published analysis cannot be newer than active analysis")


    def confirm(self) -> "ResearchObjective":
        if self.confirmation_status != "candidate":
            raise ValueError(
                "invalid objective confirmation transition: "
                f"{self.confirmation_status} -> confirmed"
            )
        return replace(self, confirmation_status="confirmed")

    def queue_analysis(self, analysis_version: int) -> "ResearchObjective":
        if self.confirmation_status != "confirmed":
            raise ValueError("objective must be confirmed before analysis")
        if analysis_version < 1:
            raise ValueError("analysis_version must be a positive integer")
        if (
            self.active_analysis_version is not None
            and analysis_version <= self.active_analysis_version
        ):
            raise ValueError("analysis_version must be newer than active version")
        return replace(self, active_analysis_version=analysis_version)

    def publish_analysis(
        self,
        *,
        workspace_id: str,
        objective_id: str,
        analysis_version: int,
        status: str,
    ) -> "ResearchObjective":
        if workspace_id != self.workspace_id:
            raise ValueError("analysis belongs to another workspace")
        if objective_id != self.objective_id:
            raise ValueError("analysis belongs to another objective")
        if analysis_version != self.active_analysis_version:
            raise ValueError("analysis is not the active objective version")
        if status != "succeeded":
            raise ValueError("only succeeded analysis can be published")
        return replace(self, published_analysis_version=analysis_version)

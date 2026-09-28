"""Agent capabilities for proposing and approving PaperExperiment revisions."""

from __future__ import annotations

from hashlib import sha256
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class _PaperExperimentDraftArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    document_id: str = Field(min_length=1, max_length=240)
    experiments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    source_labels: list[str] = Field(default_factory=list, max_length=100)
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    def raw_draft(self) -> dict[str, Any]:
        return {
            "experiments": self.experiments,
            "source_labels": self.source_labels,
            "unresolved_issues": self.unresolved_issues,
        }


class ProposePaperExperimentDraftArguments(_PaperExperimentDraftArguments):
    pass


class CreatePaperExperimentRevisionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=128)
    draft_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


def _draft_id(context: CapabilityExecutionContext, digest: str) -> str:
    return "pexp_draft_" + sha256(
        f"{context.session_id}:{context.tool_call_id}:{digest}".encode("utf-8")
    ).hexdigest()[:24]


_DRAFT_TTL = timedelta(hours=24)


class ProposePaperExperimentDraftCapability:
    spec = ToolSpec(
        name="propose_paper_experiment_draft",
        description=(
            "Validate a source-grounded PaperExperiment draft after reading the "
            "complete Sources for one paper. Use only response-local experiment, "
            "variant, test, measurement and comparison keys plus supplied Sxxx "
            "source labels. This is a review-only draft; do not include formal IDs, "
            "fingerprints, versions, collection IDs, or objective IDs inside the "
            "scientific payload. The draft does not write a PaperExperiment."
        ),
        risk=ToolRisk.DRAFT,
        input_model=ProposePaperExperimentDraftArguments,
    )

    def __init__(self, *, authoring_service: PaperExperimentAuthoringService) -> None:
        self.authoring_service = authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ProposePaperExperimentDraftArguments,
    ) -> ChatToolResult:
        prepared = await self.authoring_service.prepare(
            collection_id=context.collection_id,
            user_id=context.user_id,
            objective_id=arguments.objective_id,
            document_id=arguments.document_id,
            raw_draft=arguments.raw_draft(),
        )
        draft_id = _draft_id(context, prepared.draft_digest)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft_id": draft_id,
                "draft_digest": prepared.draft_digest,
                "draft_created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending_approval",
                "published": False,
                "requires_user_approval": True,
                "experiment_count": len(prepared.output.output.experiments),
                "experiments": [item.payload for item in prepared.output.output.experiments],
                "source_fingerprint": prepared.source_fingerprint,
                "objective_id": arguments.objective_id,
                "document_id": arguments.document_id,
                "draft": arguments.raw_draft(),
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="paper_experiment_draft",
                    resource_id=draft_id,
                    href=(
                        f"/collections/{context.collection_id}/documents/"
                        f"{arguments.document_id}?view=paper-experiment-draft"
                    ),
                ),
            ),
        )


class CreatePaperExperimentRevisionCapability:
    spec = ToolSpec(
        name="create_paper_experiment_revision",
        description=(
            "After the exact PaperExperiment draft has been reviewed and approved, "
            "create one immutable PaperExperiment revision and its Objective "
            "Selection. Submit the stored draft ID and digest. The service "
            "reloads the prepared Source, resolves formal identities, and writes "
            "the revision and selection atomically. This does not create a Finding."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreatePaperExperimentRevisionArguments,
    )

    def __init__(
        self,
        *,
        authoring_service: PaperExperimentAuthoringService,
        chat_repository: Any | None = None,
    ) -> None:
        self.authoring_service = authoring_service
        self.chat_repository = chat_repository

    async def _stored_draft(
        self,
        context: CapabilityExecutionContext,
        arguments: CreatePaperExperimentRevisionArguments,
    ) -> tuple[str, str, dict[str, Any]]:
        if self.chat_repository is None:
            raise ValueError("paper experiment draft store is unavailable")
        messages = await self.chat_repository.read_messages(context.session_id)
        for message in reversed(messages):
            result = getattr(message, "tool_result", None)
            data = getattr(result, "data", None)
            if not isinstance(data, dict) or data.get("draft_id") != arguments.draft_id:
                continue
            if data.get("status") != "pending_approval":
                continue
            created_at = str(data.get("draft_created_at") or "")
            try:
                is_expired = datetime.now(timezone.utc) - datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                ) > _DRAFT_TTL
            except ValueError:
                is_expired = True
            if is_expired:
                raise ValueError("paper experiment draft has expired; propose it again")
            draft = data.get("draft")
            if not isinstance(draft, dict):
                continue
            return (
                str(data.get("objective_id") or ""),
                str(data.get("document_id") or ""),
                draft,
            )
        raise ValueError("paper experiment draft was not found in this session")

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreatePaperExperimentRevisionArguments,
    ) -> ChatToolResult:
        objective_id, document_id, raw_draft = await self._stored_draft(
            context, arguments
        )
        if not objective_id or not document_id:
            raise ValueError("stored paper experiment draft is missing its scope")
        prepared = await self.authoring_service.prepare(
            collection_id=context.collection_id,
            user_id=context.user_id,
            objective_id=objective_id,
            document_id=document_id,
            raw_draft=raw_draft,
        )
        if prepared.draft_digest.casefold() != arguments.draft_digest.casefold():
            raise ValueError("paper experiment draft digest changed; review it again")
        result = await self.authoring_service.write(
            prepared=prepared,
            collection_id=context.collection_id,
            created_by=context.user_id,
        )
        revision = result.revisions[0]
        refs = [
            ChatResourceRef(
                resource_type="paper_experiment",
                resource_id=(
                    f"{revision.revision.experiment_id}:"
                    f"{revision.revision.experiment_version}"
                ),
                href=(
                    f"/collections/{context.collection_id}/documents/"
                    f"{revision.revision.document_id}?view=paper-experiment"
                ),
            )
        ]
        refs.extend(
            ChatResourceRef(
                resource_type="objective_selection",
                resource_id=item.selection_id,
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{objective_id}?selection_id={item.selection_id}"
                ),
            )
            for item in result.selections
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "published": True,
                "revision": revision.revision.to_record(),
                "selection_ids": [item.selection_id for item in result.selections],
                "finding_ids": [],
            },
            resource_refs=tuple(refs),
        )


__all__ = [
    "CreatePaperExperimentRevisionArguments",
    "CreatePaperExperimentRevisionCapability",
    "ProposePaperExperimentDraftArguments",
    "ProposePaperExperimentDraftCapability",
]

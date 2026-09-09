"""Source-traceable transient research-plan proposals."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.goal.research_plan_contract import (
    ResearchPlanStructure,
    ResearchPlanVariable,
)
from application.goal.experiment_plan_service import ExperimentPlanNotFoundError
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class ProposeResearchPlanArguments(ResearchPlanStructure):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective_id: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=400)
    finding_ids: list[str] = Field(
        min_length=1, max_length=8,
        description="Exact published Findings whose inspected evidence supports this plan.",
    )
    evidence_ids: list[str] = Field(
        min_length=1, max_length=32,
        description=(
            "Use only Evidence returned by inspecting one of the selected finding_ids. "
            "Evidence from the collection overview may belong to other Findings and "
            "cannot be attached to this plan without inspecting and selecting its parent."
        ),
    )

    @field_validator(
        "finding_ids",
        "evidence_ids",
    )
    @classmethod
    def _normalize_source_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values)

    @model_validator(mode="after")
    def _validate_variable_evidence_scope(self) -> "ProposeResearchPlanArguments":
        required_lists = {
            "controls": self.controls,
            "fixed_conditions": self.fixed_conditions,
            "measurements": self.measurements,
            "acceptance_criteria": self.acceptance_criteria,
            "feasibility_checks": self.feasibility_checks,
            "safety_considerations": self.safety_considerations,
            "limitations": self.limitations,
            "finding_ids": self.finding_ids,
            "evidence_ids": self.evidence_ids,
        }
        empty_fields = [name for name, values in required_lists.items() if not values]
        if empty_fields:
            raise ValueError(
                "research plan requires non-empty " + ", ".join(empty_fields)
            )
        selected = set(self.evidence_ids)
        outside_scope = sorted(
            {
                evidence_id
                for variable in self.variables
                for evidence_id in variable.basis_evidence_ids
                if evidence_id not in selected
            }
        )
        if outside_scope:
            raise ValueError(
                "variable basis Evidence must be included in evidence_ids: "
                + ", ".join(outside_scope)
            )
        return self


class ResearchPlanSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_id: str = Field(min_length=1, max_length=240)
    analysis_version: int = Field(ge=1)
    finding_fingerprint: str = Field(min_length=1, max_length=240)
    evidence_fingerprint: str = Field(min_length=1, max_length=240)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("evidence_ids")
    @classmethod
    def _normalize_evidence_ids(cls, values: list[str]) -> list[str]:
        normalized = _unique_text(values)
        if not normalized:
            raise ValueError("source snapshot requires at least one Evidence ID")
        return normalized


class CreateResearchPlanArguments(ProposeResearchPlanArguments):
    source_snapshots: list[ResearchPlanSourceSnapshot] = Field(
        min_length=1,
        max_length=8,
    )


class ReviseResearchPlanArguments(CreateResearchPlanArguments):
    parent_plan_id: str = Field(min_length=1, max_length=128)


class InspectResearchPlansArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective_id: str = Field(min_length=1, max_length=240)
    plan_id: str | None = Field(default=None, min_length=1, max_length=128)


class InspectResearchPlansCapability:
    spec = ToolSpec(
        name="inspect_research_plans",
        description=(
            "Read the current saved research-plan revisions for one research question, "
            "or one exact historical revision by ID. The result includes structured "
            "design, provenance, status, and version lineage."
        ),
        risk=ToolRisk.READ,
        input_model=InspectResearchPlansArguments,
    )

    def __init__(self, *, collection_service: Any, experiment_plan_service: Any) -> None:
        self.collection_service = collection_service
        self.experiment_plan_service = experiment_plan_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectResearchPlansArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        if arguments.plan_id is None:
            plans = await self.experiment_plan_service.list_plans(
                context.collection_id,
                arguments.objective_id,
            )
            records = [item.to_record() for item in plans]
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="succeeded",
                data={
                    "objective_id": arguments.objective_id,
                    "plans": records,
                    "plan_count": len(records),
                    "history_scope": "current_revisions",
                },
                resource_refs=tuple(
                    _plan_ref(context.collection_id, arguments.objective_id, item)
                    for item in records
                ),
            )
        try:
            plan = await self.experiment_plan_service.read_plan(
                context.collection_id,
                arguments.objective_id,
                arguments.plan_id,
            )
        except ExperimentPlanNotFoundError:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                data={
                    "objective_id": arguments.objective_id,
                    "plan_id": arguments.plan_id,
                },
                error_code="research_plan_not_found",
                error_message="The requested research-plan revision was not found.",
            )
        record = plan.to_record()
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "objective_id": arguments.objective_id,
                "plan": record,
                "history_scope": "named_revision",
            },
            resource_refs=(
                _plan_ref(context.collection_id, arguments.objective_id, record),
            ),
        )


class ProposeResearchPlanCapability:
    spec = ToolSpec(
        name="propose_research_plan",
        description=(
            "Record a transient, complete research or experiment plan draft for one "
            "published research question. The draft must specify hypothesis, variables, "
            "controls, fixed conditions, measurements, replication, analysis, acceptance, "
            "feasibility, safety, and limitations, and cite exact current Finding and "
            "Evidence IDs. This call does not persist or authorize the plan."
        ),
        risk=ToolRisk.DRAFT,
        input_model=ProposeResearchPlanArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        finding_feedback_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ProposeResearchPlanArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        dataset = await self.finding_feedback_service.export_dataset(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
        )
        items = [
            dict(item)
            for item in dataset.get("items") or ()
            if isinstance(item, Mapping)
        ]
        findings = {
            finding_id: item
            for item in items
            if (finding_id := _text(item.get("finding_id")))
        }
        missing_finding_ids = [
            item for item in arguments.finding_ids if item not in findings
        ]
        selected_findings = [
            findings[item]
            for item in arguments.finding_ids
            if item in findings
        ]
        evidence = _evidence_index(selected_findings)
        missing_evidence_ids = [
            item for item in arguments.evidence_ids if item not in evidence
        ]
        rejected_finding_ids = [
            finding_id
            for finding_id in arguments.finding_ids
            if finding_id in findings
            and _text(findings[finding_id].get("label_status")) == "rejected"
        ]
        failed_evidence_ids = [
            evidence_id
            for evidence_id in arguments.evidence_ids
            if evidence_id in evidence
            and _text(evidence[evidence_id].get("evidence_status"))
            == "extraction_failed"
        ]
        analysis_versions = {
            int(item["analysis_version"])
            for item in selected_findings
            if item.get("analysis_version") is not None
        }
        invalid_versions = len(analysis_versions) != 1
        if (
            missing_finding_ids
            or missing_evidence_ids
            or rejected_finding_ids
            or failed_evidence_ids
            or invalid_versions
        ):
            warnings = []
            if missing_finding_ids:
                warnings.append("Some selected Findings are not in the current dataset.")
            if missing_evidence_ids:
                warnings.append(
                    "Some selected Evidence is not linked to the selected current Findings. "
                    "Correct the selection using available_evidence_ids before proposing again."
                )
            if rejected_finding_ids:
                warnings.append("Rejected Findings cannot support a research plan draft.")
            if failed_evidence_ids:
                warnings.append(
                    "Technical extraction failures cannot support a research plan draft."
                )
            if invalid_versions:
                warnings.append(
                    "The selected Findings do not identify one current analysis version."
                )
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="succeeded",
                data={
                    "objective_id": arguments.objective_id,
                    "draft_status": "abstained",
                    "abstention_reason": "source_basis_not_current",
                    "missing_finding_ids": missing_finding_ids,
                    "missing_evidence_ids": missing_evidence_ids,
                    "available_evidence_ids": sorted(evidence),
                    "rejected_finding_ids": rejected_finding_ids,
                    "failed_evidence_ids": failed_evidence_ids,
                    "persistence": "transient_chat_result",
                    "support_is_evidence": False,
                },
                warnings=tuple(warnings),
            )

        source_analysis_version = next(iter(analysis_versions))
        selected_evidence = [evidence[item] for item in arguments.evidence_ids]
        finding_labels = {
            finding_id: f"Finding {position}"
            for position, finding_id in enumerate(arguments.finding_ids, start=1)
        }
        evidence_labels = {
            evidence_id: f"Evidence {position}"
            for position, evidence_id in enumerate(arguments.evidence_ids, start=1)
        }
        content = _render_plan(
            arguments,
            selected_findings=selected_findings,
            selected_evidence=selected_evidence,
            finding_labels=finding_labels,
            evidence_labels=evidence_labels,
        )
        draft_id = _draft_id(context.tool_call_id, arguments)
        unreviewed_finding_ids = [
            finding_id
            for finding_id in arguments.finding_ids
            if _text(findings[finding_id].get("label_status")) != "gold"
        ]
        draft_status = (
            "needs_finding_review"
            if unreviewed_finding_ids
            else "ready_for_researcher_review"
        )
        source_snapshots = [
            _source_snapshot(item) for item in selected_findings
        ]
        source_links = [
            {
                "kind": "evidence",
                "label": evidence_labels[evidence_id],
                "href": _evidence_href(
                    context.collection_id,
                    evidence[evidence_id],
                ),
            }
            for evidence_id in arguments.evidence_ids
        ]
        refs: list[ChatResourceRef] = [
            ChatResourceRef(
                resource_type="research_plan_draft",
                resource_id=draft_id,
            )
        ]
        refs.extend(
            ChatResourceRef(
                resource_type="finding",
                resource_id=(
                    f"{arguments.objective_id}:{source_analysis_version}:{finding_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}?finding_id={finding_id}"
                ),
            )
            for finding_id in arguments.finding_ids
        )
        for evidence_id in arguments.evidence_ids:
            item = evidence[evidence_id]
            refs.append(
                ChatResourceRef(
                    resource_type="evidence",
                    resource_id=f"{arguments.objective_id}:{evidence_id}",
                    href=_evidence_href(context.collection_id, item),
                )
            )
            document_id = _text(item.get("document_id"))
            source_ref = _text(item.get("source_ref"))
            if document_id and source_ref:
                refs.append(
                    ChatResourceRef(
                        resource_type="source",
                        resource_id=(
                            f"{document_id}:{_text(item.get('source_kind'))}:"
                            f"{source_ref}"
                        ),
                        href=(
                            f"/collections/{context.collection_id}/documents/"
                            f"{document_id}?"
                            + urlencode(
                                {"view": "parsed-paper", "source_ref": source_ref}
                            )
                        ),
                    )
                )
        warnings = (
            (
                "The plan cites one or more Findings that still require researcher "
                "review; treat the draft as provisional."
            ),
        ) if unreviewed_finding_ids else ()
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft_id": draft_id,
                "objective_id": arguments.objective_id,
                "title": arguments.title,
                "content": content,
                "structured_plan": arguments.model_dump(
                    include=set(ResearchPlanStructure.model_fields)
                ),
                "draft_status": draft_status,
                "source_analysis_version": source_analysis_version,
                "source_finding_ids": list(arguments.finding_ids),
                "source_evidence_ids": list(arguments.evidence_ids),
                "source_snapshots": source_snapshots,
                "source_links": source_links,
                "unreviewed_finding_ids": unreviewed_finding_ids,
                "persistence": "transient_chat_result",
                "support_is_evidence": False,
            },
            resource_refs=_deduplicate_refs(refs),
            warnings=warnings,
        )


class CreateResearchPlanCapability:
    spec = ToolSpec(
        name="create_research_plan",
        description=(
            "Persist one reviewed research-plan draft through the canonical "
            "Objective-scoped ExperimentPlan service. The exact structured plan and "
            "current Finding/Evidence fingerprints require explicit user approval. "
            "Changed or stale sources fail without writing a plan."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreateResearchPlanArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        finding_feedback_service: Any,
        experiment_plan_service: Any,
    ) -> None:
        self.experiment_plan_service = experiment_plan_service
        self._draft_capability = ProposeResearchPlanCapability(
            collection_service=collection_service,
            finding_feedback_service=finding_feedback_service,
        )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateResearchPlanArguments,
    ) -> ChatToolResult:
        current, current_snapshots, error = await _approved_plan_draft(
            self._draft_capability,
            context,
            arguments,
        )
        if error is not None:
            return error

        try:
            plan = await self.experiment_plan_service.create_agent_plan(
                collection_id=context.collection_id,
                objective_id=arguments.objective_id,
                title=arguments.title,
                content=str(current.data["content"]),
                source_links=list(current.data["source_links"]),
                source_findings=current_snapshots,
                structured_plan=dict(current.data["structured_plan"]),
                created_by=context.user_id,
                created_by_tool_call_id=context.tool_call_id,
            )
        except ValueError as exc:
            message = str(exc).strip()
            if not message.startswith("research plan sources are stale"):
                raise
            return _stale_plan_write(
                context,
                arguments.objective_id,
                current,
                current_snapshots,
                message,
            )
        return _saved_plan_result(
            context,
            arguments.objective_id,
            current,
            plan,
        )


class ReviseResearchPlanCapability:
    spec = ToolSpec(
        name="revise_research_plan",
        description=(
            "Append one immutable revision to a saved research plan through the same "
            "Objective-scoped plan service used by the researcher interface. The exact "
            "parent revision, structured design, and current Finding/Evidence snapshots "
            "require explicit user approval."
        ),
        risk=ToolRisk.WRITE,
        input_model=ReviseResearchPlanArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        finding_feedback_service: Any,
        experiment_plan_service: Any,
    ) -> None:
        self.experiment_plan_service = experiment_plan_service
        self._draft_capability = ProposeResearchPlanCapability(
            collection_service=collection_service,
            finding_feedback_service=finding_feedback_service,
        )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ReviseResearchPlanArguments,
    ) -> ChatToolResult:
        current, current_snapshots, error = await _approved_plan_draft(
            self._draft_capability,
            context,
            arguments,
        )
        if error is not None:
            return error
        try:
            plan = await self.experiment_plan_service.update_plan(
                collection_id=context.collection_id,
                objective_id=arguments.objective_id,
                plan_id=arguments.parent_plan_id,
                title=arguments.title,
                content=str(current.data["content"]),
                status="draft",
                structured_plan=dict(current.data["structured_plan"]),
                updated_by=context.user_id,
                source_links=list(current.data["source_links"]),
                source_findings=current_snapshots,
                updated_by_tool_call_id=context.tool_call_id,
            )
        except ExperimentPlanNotFoundError:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                data={
                    "objective_id": arguments.objective_id,
                    "plan_id": arguments.parent_plan_id,
                },
                error_code="research_plan_not_found",
                error_message="The parent research-plan revision was not found.",
            )
        except ValueError as exc:
            message = str(exc).strip()
            if not message.startswith("research plan sources are stale"):
                raise
            return _stale_plan_write(
                context,
                arguments.objective_id,
                current,
                current_snapshots,
                message,
            )
        return _saved_plan_result(
            context,
            arguments.objective_id,
            current,
            plan,
        )


async def _approved_plan_draft(
    draft_capability: ProposeResearchPlanCapability,
    context: CapabilityExecutionContext,
    arguments: CreateResearchPlanArguments | ReviseResearchPlanArguments,
) -> tuple[ChatToolResult, list[dict[str, Any]], ChatToolResult | None]:
    # Create/Revise arguments inherit the complete proposal contract. Pass the
    # already validated subtype through directly instead of serializing and
    # validating the same fields a second time.
    current = await draft_capability.execute(context, arguments)
    current_snapshots = list(current.data.get("source_snapshots") or ())
    if current.data.get("draft_status") == "abstained":
        return current, current_snapshots, ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="failed",
            data=dict(current.data),
            resource_refs=current.resource_refs,
            warnings=current.warnings,
            error_code="research_plan_source_stale",
            error_message=(
                "The selected Finding or Evidence is no longer current; inspect "
                "the published analysis and prepare a new plan draft."
            ),
        )
    approved_snapshots = [item.model_dump() for item in arguments.source_snapshots]
    if approved_snapshots != current_snapshots:
        return current, current_snapshots, ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="failed",
            data={
                "objective_id": arguments.objective_id,
                "approved_source_snapshots": approved_snapshots,
                "current_source_snapshots": current_snapshots,
            },
            resource_refs=current.resource_refs,
            error_code="research_plan_source_stale",
            error_message=(
                "The Finding or Evidence changed after the plan was drafted; "
                "review the current sources before saving it."
            ),
        )
    return current, current_snapshots, None


def _stale_plan_write(
    context: CapabilityExecutionContext,
    objective_id: str,
    current: ChatToolResult,
    current_snapshots: list[dict[str, Any]],
    detail: str,
) -> ChatToolResult:
    return ChatToolResult(
        tool_call_id=context.tool_call_id,
        status="failed",
        data={
            "objective_id": objective_id,
            "source_snapshots_current": False,
            "current_source_snapshots": current_snapshots,
            "persistence": "transient_chat_result",
        },
        resource_refs=tuple(
            ref for ref in current.resource_refs if ref.resource_type != "research_plan_draft"
        ),
        error_code="research_plan_source_stale",
        error_message=(
            "The Finding or Evidence changed before saving the plan; review the current "
            "sources before saving it."
            + (f" ({detail})" if detail else "")
        ),
    )


def _saved_plan_result(
    context: CapabilityExecutionContext,
    objective_id: str,
    current: ChatToolResult,
    plan: Any,
) -> ChatToolResult:
    record = plan.to_record()
    refs = [_plan_ref(context.collection_id, objective_id, record)]
    refs.extend(
        ref for ref in current.resource_refs if ref.resource_type != "research_plan_draft"
    )
    return ChatToolResult(
        tool_call_id=context.tool_call_id,
        status="succeeded",
        data={
            "plan": record,
            "source_snapshots_current": True,
            "requires_researcher_review": plan.status == "draft",
        },
        resource_refs=_deduplicate_refs(refs),
        warnings=current.warnings,
    )


def _evidence_index(findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for finding in findings:
        for item in finding.get("evidence") or ():
            if not isinstance(item, Mapping):
                continue
            evidence_id = _text(item.get("evidence_id"))
            if evidence_id:
                result.setdefault(evidence_id, dict(item))
    return result


def _source_snapshot(finding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": _text(finding.get("finding_id")),
        "analysis_version": int(finding.get("analysis_version") or 0),
        "finding_fingerprint": _text(finding.get("finding_fingerprint")),
        "evidence_fingerprint": _text(finding.get("evidence_fingerprint")),
        "evidence_ids": [
            evidence_id
            for item in finding.get("evidence") or ()
            if isinstance(item, Mapping)
            and (evidence_id := _text(item.get("evidence_id")))
        ],
    }


def _render_plan(
    arguments: ProposeResearchPlanArguments,
    *,
    selected_findings: list[dict[str, Any]],
    selected_evidence: list[dict[str, Any]],
    finding_labels: Mapping[str, str],
    evidence_labels: Mapping[str, str],
) -> str:
    lines = [
        f"# {arguments.title}",
        "",
        "## Hypothesis",
        arguments.hypothesis,
        "",
        "## Variable matrix",
        "| Variable | Role | Planned values | Basis | Supporting evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for variable in arguments.variables:
        citations = ", ".join(
            f"[{evidence_labels[item]}]"
            for item in variable.basis_evidence_ids
        ) or "Expert decision"
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(variable.name),
                    variable.role,
                    _cell(", ".join(variable.planned_values)),
                    variable.basis.replace("_", " "),
                    citations,
                )
            )
            + " |"
        )
    lines.extend(_section("Controls", arguments.controls))
    lines.extend(_section("Fixed conditions", arguments.fixed_conditions))
    lines.extend(_section("Measurements", arguments.measurements))
    lines.extend(
        [
            "",
            "## Replication",
            arguments.replication,
            "",
            "## Analysis method",
            arguments.analysis_method,
        ]
    )
    lines.extend(_section("Acceptance criteria", arguments.acceptance_criteria))
    lines.extend(_section("Feasibility checks", arguments.feasibility_checks))
    lines.extend(_section("Safety considerations", arguments.safety_considerations))
    if arguments.limitations:
        lines.extend(_section("Limitations and open decisions", arguments.limitations))
    lines.extend(["", "## Source basis"])
    for finding in selected_findings:
        finding_id = _text(finding.get("finding_id"))
        target = finding.get("training_target")
        target = dict(target) if isinstance(target, Mapping) else {}
        lines.append(
            f"- [{finding_labels[finding_id]}] "
            + (_text(target.get("statement")) or "Published research conclusion.")
        )
    for item in selected_evidence:
        evidence_id = _text(item.get("evidence_id"))
        lines.append(
            f"- [{evidence_labels[evidence_id]}] "
            f"{_text(item.get('source_excerpt')) or 'Source-linked Evidence.'}"
        )
    return "\n".join(lines).strip()


def _section(title: str, items: list[str]) -> list[str]:
    return ["", f"## {title}", *(f"- {item}" for item in items)]


def _cell(value: str) -> str:
    return " ".join(str(value).replace("|", "\\|").split())


def _evidence_href(collection_id: str, evidence: Mapping[str, Any]) -> str:
    return (
        f"/collections/{collection_id}/documents/{_text(evidence.get('document_id'))}"
        f"?evidence_id={_text(evidence.get('evidence_id'))}"
    )


def _plan_ref(
    collection_id: str,
    objective_id: str,
    plan: Mapping[str, Any],
) -> ChatResourceRef:
    plan_id = _text(plan.get("plan_id"))
    return ChatResourceRef(
        resource_type="research_plan",
        resource_id=plan_id,
        href=(
            f"/collections/{collection_id}/objectives/{objective_id}"
            f"?plan_id={plan_id}"
        ),
    )


def _draft_id(
    tool_call_id: str,
    arguments: ProposeResearchPlanArguments,
) -> str:
    identity = json.dumps(
        {
            "tool_call_id": tool_call_id,
            "arguments": arguments.model_dump(),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"plan_draft_{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _deduplicate_refs(refs: list[ChatResourceRef]) -> tuple[ChatResourceRef, ...]:
    result: list[ChatResourceRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        identity = (ref.resource_type, ref.resource_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return tuple(result)


__all__ = [
    "CreateResearchPlanArguments",
    "CreateResearchPlanCapability",
    "InspectResearchPlansArguments",
    "InspectResearchPlansCapability",
    "ProposeResearchPlanArguments",
    "ProposeResearchPlanCapability",
    "ResearchPlanSourceSnapshot",
    "ResearchPlanVariable",
    "ReviseResearchPlanArguments",
    "ReviseResearchPlanCapability",
]

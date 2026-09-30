"""Agent capabilities for proposing and approving PaperExperiment revisions."""

from __future__ import annotations

from hashlib import sha256
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class _ScientificAttributeToolField(BaseModel):
    """A source-reported named value used in variants or test conditions."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        min_length=1,
        description="Source-reported parameter name, such as temperature or strain_rate.",
    )
    value: str | int | float | bool = Field(
        description="The reported value; do not invent a value when the source is silent."
    )
    unit: str | None = Field(
        default=None,
        description="Reported unit, such as C, K, or 1/s; null when not reported.",
    )
    context_scope: str | None = Field(
        default=None,
        description="Optional scope: experimental, simulation, background, or unknown.",
    )
    applies_to_outcomes: list[str] = Field(
        default_factory=list,
        description="Optional outcome labels this parameter applies to.",
    )


class _ScientificVariableToolField(BaseModel):
    """A source-reported factor that differs between comparison sides."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        description="Changed factor name, such as preheating or dose.",
    )
    baseline_value: str | int | float | bool | None = Field(
        default=None,
        description="Source-reported value for the baseline variant, if stated.",
    )
    target_value: str | int | float | bool | None = Field(
        default=None,
        description="Source-reported value for the target variant, if stated.",
    )
    unit: str | None = Field(
        default=None,
        description="Unit shared by the reported baseline and target values, if any.",
    )


class _PaperExperimentVariantToolField(BaseModel):
    """One response-local experimental variant; extra scientific fields are allowed."""

    model_config = ConfigDict(extra="allow")

    variant_key: str = Field(
        min_length=1,
        description="Required response-local key used by measurements and comparisons.",
    )
    variant_label: str = Field(
        min_length=1,
        description="Required paper-reported label for this object or group.",
    )
    subject_attributes: list[_ScientificAttributeToolField] = Field(
        default_factory=list,
        description="Material, specimen, or population attributes reported for this variant.",
    )
    intervention_attributes: list[_ScientificAttributeToolField] = Field(
        default_factory=list,
        description="Treatment or process attributes that distinguish this variant.",
    )
    state: list[_ScientificAttributeToolField] = Field(
        default_factory=list,
        description="Other source-reported state attributes for this variant.",
    )
    population_scope: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional paper-reported population or specimen scope. Keep paper-native "
            "identifiers inside reported_identifiers; do not put Lens IDs here."
        ),
    )
    source_labels: list[str] = Field(
        min_length=1,
        description="Sxxx labels supporting the variant identity or attributes.",
    )
    binding_source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "Sxxx labels that explicitly bind this variant to its experiment scope; "
            "leave empty only when that relationship is not stated."
        ),
    )
    identity_specificity: Literal[
        "exact", "partial", "category", "broad", "unknown"
    ] = Field(
        default="unknown",
        description=(
            "Source-grounded identity detail: exact only when the paper distinguishes "
            "this object/group from its peers; otherwise partial or unknown."
        ),
    )
    missing_dimensions: list[str] = Field(
        default_factory=list,
        description="Identity dimensions the source leaves unresolved.",
    )
    identity_evidence: list[str] = Field(
        default_factory=list,
        description="Short source-grounded notes explaining the identity classification.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Other source-grounded limitations for this variant.",
    )


class _PaperExperimentTestConditionToolField(BaseModel):
    """A test or characterization and the parameters reported for it."""

    model_config = ConfigDict(extra="allow")

    test_key: str = Field(
        min_length=1,
        description="Required response-local key used by measurements.",
    )
    test_type: str = Field(
        min_length=1,
        description="Test or characterization category, such as tensile or microscopy.",
    )
    method: str | None = Field(default=None, description="Reported method or instrument description.")
    standard: str | None = Field(default=None, description="Reported standard, such as ASTM E8.")
    parameters: list[_ScientificAttributeToolField] = Field(
        default_factory=list,
        description=(
            "Structured test parameters reported by the source, such as temperature, "
            "strain_rate, frequency, duration, or n. Use this field rather than "
            "test_attributes."
        ),
    )
    outcome_scope: list[str] = Field(
        default_factory=list,
        description="Outcome labels measured or characterized by this test.",
    )
    population_scope: dict[str, Any] | None = Field(
        default=None,
        description="Optional paper-reported scope of objects to which this protocol applies.",
    )
    source_labels: list[str] = Field(
        min_length=1,
        description="Sxxx labels supporting the test identity, method, or parameters.",
    )
    binding_source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "Sxxx labels that explicitly connect this test protocol to the reported "
            "experiment scope; leave empty when that relationship is not stated."
        ),
    )
    protocol_specificity: Literal[
        "exact", "partial", "category", "broad", "unknown"
    ] = Field(
        description=(
            "Source-grounded protocol identity: exact only for a concrete method or "
            "standard, not a category such as 'mechanical test'."
        ),
    )
    protocol_completeness: Literal["complete", "partial", "unknown"] = Field(
        default="unknown",
        description=(
            "Source coverage for the listed outcomes: complete when the reported "
            "protocol details are sufficient for interpretation, partial when details "
            "are missing, or unknown when coverage cannot be determined. This is "
            "diagnostic metadata; do not invent missing parameters."
        ),
    )
    missing_parameters: list[str] = Field(
        default_factory=list,
        description="Protocol parameters needed for interpretation but absent from the source.",
    )
    protocol_evidence: list[str] = Field(
        default_factory=list,
        description="Short source-grounded notes supporting protocol specificity/completeness.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Other source-grounded limitations for this test condition.",
    )


class _PaperExperimentMeasurementToolField(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    measurement_key: str = Field(
        min_length=1,
        description="Required response-local key used by comparisons and interpretations.",
    )
    variant_key: str | None = Field(default=None, description="Response-local variant key, when known.")
    test_key: str | None = Field(default=None, description="Response-local test key, when known.")
    outcome: str = Field(min_length=1, description="Measured or observed outcome label.")
    value: str | int | float | bool | None = Field(
        description="Reported scalar value; use null when the result is qualitative.",
    )
    unit: str | None = Field(default=None, description="Reported measurement unit.")
    result_text: str | None = Field(
        description="Verbatim qualitative result; use null when value is populated.",
    )
    statistics: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Reported statistics such as error, range, or n. Keep the source's "
            "statistical meaning; do not turn n into a separate measurement."
        ),
    )
    measurement_scope: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Reported scope such as specimen/group, replicate, time, or location. "
            "Keep paper-native identifiers inside reported_identifiers."
        ),
    )
    result_kind: Literal["measured", "observed", "simulated", "predicted", "unknown"] = Field(
        default="measured",
        description="Nature of the reported result; use observed for qualitative observations.",
    )
    reported_sample_label: str | None = Field(
        default=None,
        description="Verbatim sample/row wording when variant_key is unresolved.",
    )
    reported_test_label: str | None = Field(
        default=None,
        description="Verbatim test/method wording when test_key is unresolved.",
    )
    candidate_variant_keys: list[str] = Field(
        default_factory=list,
        description="Possible local variant keys when exact result ownership is unresolved.",
    )
    candidate_test_keys: list[str] = Field(
        default_factory=list,
        description="Possible local test keys when exact protocol ownership is unresolved.",
    )
    source_labels: list[str] = Field(
        min_length=1,
        description="Sxxx labels supporting the reported value or result text.",
    )
    variant_binding_source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "Sxxx labels proving this result belongs to variant_key. Required for "
            "exact binding; leave empty when the source only gives a broad scope."
        ),
    )
    test_binding_source_labels: list[str] = Field(
        default_factory=list,
        description=(
            "Sxxx labels proving this result was obtained under test_key. Required "
            "for exact binding; leave empty when the source does not connect them."
        ),
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Other source-grounded limitations for this measurement.",
    )

    @model_validator(mode="after")
    def _require_reported_result(self) -> "_PaperExperimentMeasurementToolField":
        if self.value is None and not self.result_text:
            raise ValueError("measurement requires value or result_text")
        return self


class _PaperExperimentComparisonToolField(BaseModel):
    """One typed same-paper comparison between two local variants."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    comparison_key: str = Field(
        min_length=1,
        description="Required response-local comparison key.",
    )
    baseline_variant_key: str = Field(
        min_length=1,
        description="Local key of the baseline/control variant.",
    )
    target_variant_key: str = Field(
        min_length=1,
        description="Local key of the target/treated variant.",
    )
    outcome: str = Field(
        min_length=1,
        description="One outcome shared by both comparison sides.",
    )
    baseline_measurement_keys: list[str] = Field(
        min_length=1,
        description="Local measurement keys reported for the baseline side.",
    )
    target_measurement_keys: list[str] = Field(
        min_length=1,
        description="Local measurement keys reported for the target side.",
    )
    changed_variables: list[_ScientificVariableToolField] = Field(
        default_factory=list,
        description=(
            "Factors that differ between the two sides. Include every jointly changed "
            "factor; do not claim isolated causation from one difference alone."
        ),
    )
    matched_conditions: list[_ScientificAttributeToolField] = Field(
        default_factory=list,
        description="Conditions the source explicitly holds equal on both sides.",
    )
    reported_statement: str | None = Field(
        default=None,
        description="Optional verbatim author statement about this comparison.",
    )
    source_labels: list[str] = Field(
        min_length=1,
        description="Sxxx labels supporting the comparison or author statement.",
    )
    binding_source_labels: list[str] = Field(
        min_length=1,
        description=(
            "Sxxx labels proving that the referenced measurements form this comparison; "
            "do not use a model-local key as evidence."
        ),
    )


class _PaperExperimentReportedInterpretationToolField(BaseModel):
    """A paper author's interpretation, kept separate from a Lens Finding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    interpretation_key: str | None = Field(
        default=None,
        description="Optional response-local key for referring to this interpretation.",
    )
    statement: str = Field(
        min_length=1,
        description="The author's source-grounded statement, not a Lens-generated Finding.",
    )
    kind: Literal["result_summary", "mechanism_hypothesis", "limitation"] = Field(
        description=(
            "Interpretation type: result_summary, mechanism_hypothesis, or limitation. "
            "This field is required even when the statement is short."
        ),
    )
    measurement_keys: list[str] = Field(
        default_factory=list,
        description="Local measurements discussed by the author's statement.",
    )
    comparison_keys: list[str] = Field(
        default_factory=list,
        description="Local comparisons discussed by the author's statement.",
    )
    source_labels: list[str] = Field(
        min_length=1,
        description="Sxxx labels containing the author's statement.",
    )


class _PaperExperimentDraftExperimentField(BaseModel):
    """One paper experiment with response-local relationships."""

    model_config = ConfigDict(extra="allow")

    label: str = Field(
        min_length=1,
        description="Required human-readable name for this experiment series.",
    )
    scope_description: str = Field(
        min_length=1,
        description=(
            "Required boundary description: which variants, tests, outcomes, and "
            "paper scope this experiment covers."
        ),
    )
    series_key: str | None = Field(default=None, description="Response-local experiment series key.")
    scope_kind: Literal[
        "parent",
        "matrix",
        "selected_stratum",
        "follow_up",
        "physical_split",
        "split",
        "independent",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Boundary category for this response-local experiment. Use parent for the "
            "main paper series; use unknown when the source does not establish a boundary."
        ),
    )
    parent_series_key: str | None = Field(
        default=None,
        description="Prior response-local parent key for selected_stratum or follow_up scopes.",
    )
    scope_selector: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional source-grounded selector for a selected/follow-up scope, such as "
            "selected_levels, fixed_attributes, or test_scope_labels."
        ),
    )
    split_evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Source-label records supporting an independent physical split.",
    )
    design_type: Literal["parallel", "factorial", "dose_response", "observational", "unknown"] = Field(
        default="unknown",
        description="Paper-supported design shape; use unknown when the design is not stated.",
    )
    experimental_variants: list[_PaperExperimentVariantToolField] = Field(
        default_factory=list,
        description="Variants or groups reconstructed from the paper.",
    )
    variants: list[_PaperExperimentVariantToolField] = Field(
        default_factory=list,
        description="Alias accepted by the contract for experimental_variants.",
    )
    test_conditions: list[_PaperExperimentTestConditionToolField] = Field(
        default_factory=list,
        description="Tests or characterizations and their structured parameters.",
    )
    measurements: list[_PaperExperimentMeasurementToolField] = Field(
        default_factory=list,
        description="Source-reported measurements or qualitative observations.",
    )
    comparisons: list[_PaperExperimentComparisonToolField] = Field(
        default_factory=list,
        description=(
            "Typed within-paper comparisons. Every comparison must name both local "
            "variants, both sides' measurement keys, and source-backed relation labels."
        ),
    )
    reported_interpretations: list[_PaperExperimentReportedInterpretationToolField] = Field(
        default_factory=list,
        description=(
            "Typed paper-author interpretations. Always provide statement, kind, and "
            "source labels; these are not Lens Findings."
        ),
    )
    source_labels: list[str] = Field(default_factory=list, description="Sxxx labels supporting this experiment.")
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list, description="Unknown or unresolved source facts.")


class _PaperExperimentDraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    document_id: str = Field(min_length=1, max_length=240)
    experiments: list[_PaperExperimentDraftExperimentField] = Field(
        default_factory=list,
        max_length=20,
        description="Experiments reconstructed from the source; keep all keys response-local.",
    )
    source_labels: list[str] = Field(default_factory=list, max_length=100)
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    def raw_draft(self) -> dict[str, Any]:
        return {
            "experiments": [item.model_dump(exclude_defaults=True) for item in self.experiments],
            "source_labels": self.source_labels,
            "unresolved_issues": self.unresolved_issues,
        }


class PaperExperimentDraftToolRequest(_PaperExperimentDraftFields):
    pass


class PaperExperimentRevisionToolRequest(BaseModel):
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
            "source labels. Each experiment must provide label and scope_description; "
            "each variant must provide variant_key, variant_label, and source_labels; "
            "each test condition must provide test_key, test_type, source_labels, "
            "and protocol_specificity, and should provide protocol_completeness when "
            "the Source supports that assessment, with temperature, "
            "rate, duration, replication, and other reported protocol values in "
            "parameters. When a Source explicitly binds the test protocol to this "
            "experiment, include binding_source_labels; mark completeness partial "
            "when details are absent and list them in missing_parameters; incomplete "
            "coverage is retained as a limitation and does not by itself prevent "
            "Selection when the protocol identity, outcome scope, and measurement "
            "binding edges are sufficient; "
            "each comparison must provide both variant keys, both measurement-key "
            "lists, outcome, source_labels, and binding_source_labels; each reported "
            "interpretation must provide statement, kind (result_summary, "
            "mechanism_hypothesis, or limitation), and source_labels. "
            "Measurements must provide a local key, outcome, value or result_text, "
            "and source_labels. This is a review-only draft; do not include formal "
            "IDs, fingerprints, versions, collection IDs, or objective IDs inside "
            "the scientific payload. The draft does not write a PaperExperiment."
        ),
        risk=ToolRisk.DRAFT,
        input_model=PaperExperimentDraftToolRequest,
    )

    def __init__(self, *, authoring_service: PaperExperimentAuthoringService) -> None:
        self.authoring_service = authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: PaperExperimentDraftToolRequest,
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
            "the revision and selection atomically. Finding creation is a separate approved action."
        ),
        risk=ToolRisk.WRITE,
        input_model=PaperExperimentRevisionToolRequest,
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
        arguments: PaperExperimentRevisionToolRequest,
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
        arguments: PaperExperimentRevisionToolRequest,
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
            created_by_tool_call_id=context.tool_call_id,
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
    "PaperExperimentRevisionToolRequest",
    "CreatePaperExperimentRevisionCapability",
    "PaperExperimentDraftToolRequest",
    "ProposePaperExperimentDraftCapability",
]

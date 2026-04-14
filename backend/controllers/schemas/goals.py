from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


GoalIntent = Literal["explore", "compare", "design_experiment"]
CoverageLevel = Literal["direct", "indirect", "sparse", "absent"]
EntryMode = Literal["comparison", "exploratory"]
GoalSeedHandoffStatus = Literal["awaiting_source_material"]


class GoalIntakeRequest(BaseModel):
    """Request payload for goal-driven collection seeding."""

    material_system: str | None = Field(default=None, description="目标材料体系")
    target_property: str | None = Field(default=None, description="目标性质")
    intent: GoalIntent = Field(default="explore", description="研究意图")
    constraints: dict[str, Any] = Field(default_factory=dict, description="研究约束")
    context: str | None = Field(default=None, description="补充背景")
    max_seed_documents: int = Field(
        default=30,
        ge=1,
        le=200,
        description="候选文献上限",
    )


class ResearchBriefResponse(BaseModel):
    """Structured goal brief produced by Goal Brief / Intake."""

    material_system: str | None = Field(default=None, description="目标材料体系")
    target_property: str | None = Field(default=None, description="目标性质")
    intent: GoalIntent = Field(..., description="研究意图")
    objective: str = Field(..., description="结构化研究目标")
    constraints: dict[str, Any] = Field(default_factory=dict, description="研究约束")
    context: str | None = Field(default=None, description="补充背景")


class CoverageAssessmentResponse(BaseModel):
    """Coarse intake-side coverage hint before entering Core artifacts."""

    level: CoverageLevel = Field(..., description="证据覆盖等级")
    rationale: str | None = Field(default=None, description="覆盖判断理由")
    direct_evidence_count: int = Field(default=0, ge=0, description="直接证据估计数")
    indirect_evidence_count: int = Field(default=0, ge=0, description="邻近证据估计数")
    warnings: list[str] = Field(default_factory=list, description="覆盖风险提示")


class SeedCollectionResponse(BaseModel):
    """Collection-builder handoff result into Core."""

    collection_id: str = Field(..., description="目标集合 ID")
    name: str = Field(..., description="集合名称")
    created: bool = Field(default=True, description="是否新建集合")
    seeded_document_count: int = Field(default=0, ge=0, description="已注入候选文献数")
    source_channels: list[str] = Field(default_factory=list, description="候选来源通道")
    handoff_id: str = Field(..., description="collection-builder handoff ID")
    handoff_status: GoalSeedHandoffStatus = Field(..., description="handoff 当前状态")


class EntryRecommendationResponse(BaseModel):
    """Next-step recommendation after goal intake."""

    recommended_mode: EntryMode = Field(..., description="推荐入口模式")
    reason: str = Field(..., description="推荐理由")
    next_actions: list[str] = Field(default_factory=list, description="建议下一步动作")
    links: list[str] = Field(default_factory=list, description="建议跳转路径")


class GoalIntakeResponse(BaseModel):
    """Goal Brief / Intake response contract without Core artifact payloads."""

    research_brief: ResearchBriefResponse = Field(..., description="研究摘要")
    coverage_assessment: CoverageAssessmentResponse = Field(..., description="覆盖评估")
    seed_collection: SeedCollectionResponse = Field(..., description="集合播种结果")
    entry_recommendation: EntryRecommendationResponse = Field(..., description="入口建议")

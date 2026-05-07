from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MaterialReviewReportStatus = Literal[
    "generating",
    "ready",
    "ready_with_warnings",
    "failed",
]
MaterialReviewReadiness = Literal[
    "strong",
    "usable",
    "preliminary",
    "insufficient",
]


class MaterialReviewReportRequest(BaseModel):
    """Request body for generating an AI-assisted material review draft."""

    language: Literal["zh", "en"] = Field(default="zh", description="报告语言")
    report_type: Literal["review_draft"] = Field(
        default="review_draft",
        description="报告类型；MVP 仅支持综述论文草稿",
    )
    include_appendix: bool = Field(default=True, description="是否包含证据附录")
    force_regenerate: bool = Field(default=False, description="是否强制重新生成")


class MaterialReviewReportResponse(BaseModel):
    """Status and artifact links for one material review draft."""

    report_id: str = Field(..., description="报告 ID")
    collection_id: str = Field(..., description="集合 ID")
    material_id: str = Field(..., description="材料 ID")
    status: MaterialReviewReportStatus = Field(..., description="报告生成状态")
    stage: str | None = Field(default=None, description="报告生成流水线阶段")
    message: str = Field(..., description="状态说明")
    title: str | None = Field(default=None, description="报告标题")
    language: str = Field(default="zh", description="报告语言")
    report_type: str = Field(default="review_draft", description="报告类型")
    include_appendix: bool = Field(default=True, description="是否包含附录")
    readiness: MaterialReviewReadiness = Field(..., description="综述生成就绪度")
    readiness_reason: str = Field(..., description="就绪度理由")
    data_version: str = Field(..., description="材料档案上下文版本")
    warnings: list[str] = Field(default_factory=list, description="证据引用或生成警告")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    generated_at: str | None = Field(default=None, description="生成完成时间")
    pdf_url: str | None = Field(default=None, description="PDF 下载链接")
    markdown_url: str | None = Field(default=None, description="Markdown 预览链接")

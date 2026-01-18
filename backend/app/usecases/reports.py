"""Report and community summary use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
from fastapi import HTTPException

from app.services import collection_store, graphml_export
from controllers.schemas import (
    ReportCommunityDetailResponse,
    ReportCommunityListResponse,
    ReportCommunitySummary,
    ReportDocumentItem,
    ReportEntityItem,
    ReportPatternItem,
    ReportPatternsResponse,
    ReportRelationshipItem,
)

logger = logging.getLogger(__name__)


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _safe_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, float) and pd.isna(item):
                continue
            items.append(str(item))
        return items
    if isinstance(value, float) and pd.isna(value):
        return []
    return [str(value)]


def _sort_reports(df: pd.DataFrame, sort: str | None) -> pd.DataFrame:
    if df.empty:
        return df
    sort_key = (sort or "rating").lower()
    if sort_key == "size" and "size" in df.columns:
        return df.sort_values(by=["size", "rating"], ascending=False, na_position="last")
    if "rating" in df.columns:
        return df.sort_values(by=["rating", "size"], ascending=False, na_position="last")
    if "size" in df.columns:
        return df.sort_values(by=["size"], ascending=False, na_position="last")
    return df


def _build_summary(row: pd.Series) -> ReportCommunitySummary:
    children_value = row.get("children")
    children = []
    if isinstance(children_value, (list, tuple, set)):
        children = [int(c) for c in children_value]
    elif isinstance(children_value, pd.Series):
        children = [int(c) for c in children_value.tolist()]
    elif _safe_value(children_value) is not None:
        try:
            children = list(children_value)
        except Exception:
            children = []

    return ReportCommunitySummary(
        report_id=str(row.get("id")) if _safe_value(row.get("id")) is not None else None,
        community_id=_safe_int(row.get("community")),
        human_readable_id=_safe_int(row.get("human_readable_id")),
        level=_safe_int(row.get("level")),
        parent=_safe_int(row.get("parent")),
        children=children or None,
        title=_safe_value(row.get("title")),
        summary=_safe_value(row.get("summary")),
        findings=_safe_value(row.get("findings")),
        rating=_safe_float(row.get("rating")),
        size=_safe_int(row.get("size")),
    )


def _find_report_row(
    reports: pd.DataFrame, community_id: str, level: int | None
) -> pd.Series:
    if reports.empty:
        raise HTTPException(status_code=404, detail="社区报告为空")
    mask = (
        (reports["id"].astype(str) == community_id)
        | (reports["human_readable_id"].astype(str) == community_id)
        | (reports["community"].astype(str) == community_id)
    )
    filtered = reports[mask]
    if level is not None and "level" in filtered.columns:
        filtered = filtered[filtered["level"] == level]
    if filtered.empty:
        raise HTTPException(status_code=404, detail="未找到指定社区")
    if "level" in filtered.columns:
        filtered = filtered.sort_values(by=["level"], ascending=False)
    return filtered.iloc[0]


def _find_community_row(
    communities: pd.DataFrame, community_id: str | int | None, level: int | None
) -> pd.Series | None:
    if communities is None or communities.empty:
        return None
    if community_id is None:
        return None
    mask = communities["community"].astype(str) == str(community_id)
    filtered = communities[mask]
    if level is not None and "level" in communities.columns:
        filtered = filtered[filtered["level"] == level]
    if filtered.empty:
        return None
    if "level" in filtered.columns:
        filtered = filtered.sort_values(by=["level"], ascending=False)
    return filtered.iloc[0]


def _load_reports_base_dir(collection_id: str | None):
    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    base_dir = collection_store.collection_output_dir(collection_store.collection_dir(resolved_collection_id))
    return base_dir, resolved_collection_id


def list_community_reports(
    collection_id: str | None,
    level: int | None,
    limit: int,
    offset: int,
    min_size: int,
    sort: str | None,
) -> ReportCommunityListResponse:
    base_dir, resolved_collection_id = _load_reports_base_dir(collection_id)
    reports = graphml_export.read_parquet_or_error(
        base_dir / "community_reports.parquet", "社区报告"
    )

    if level is not None and "level" in reports.columns:
        reports = reports[reports["level"] == level]
    if min_size > 0 and "size" in reports.columns:
        reports = reports[reports["size"].fillna(0) >= min_size]

    total = len(reports)
    reports = _sort_reports(reports, sort)
    paged = reports.iloc[offset : offset + limit]

    items = [_build_summary(row) for _, row in paged.iterrows()]

    return ReportCommunityListResponse(
        collection_id=resolved_collection_id,
        level=level,
        total=total,
        count=len(items),
        items=items,
    )


@dataclass(frozen=True)
class _DetailData:
    summary: ReportCommunitySummary
    entity_ids: list[str]
    relationship_ids: list[str]
    text_unit_ids: list[str]


def _load_detail_context(
    reports: pd.DataFrame,
    communities: pd.DataFrame | None,
    community_id: str,
    level: int | None,
) -> _DetailData:
    report_row = _find_report_row(reports, community_id, level)
    summary = _build_summary(report_row)
    community_value = report_row.get("community")
    community_row = _find_community_row(communities, community_value, summary.level)
    entity_ids = []
    relationship_ids = []
    text_unit_ids = []
    if community_row is not None:
        entity_ids = _listify(community_row.get("entity_ids"))
        relationship_ids = _listify(community_row.get("relationship_ids"))
        text_unit_ids = _listify(community_row.get("text_unit_ids"))
    return _DetailData(
        summary=summary,
        entity_ids=entity_ids,
        relationship_ids=relationship_ids,
        text_unit_ids=text_unit_ids,
    )


def _load_documents_from_text_units(
    base_dir,
    text_unit_ids: list[str],
    document_limit: int,
) -> tuple[list[ReportDocumentItem], int | None, int | None]:
    if not text_unit_ids:
        return [], 0, 0
    text_units = graphml_export.read_parquet_optional(
        base_dir / "text_units.parquet", "文本单元"
    )
    if text_units is None or "id" not in text_units.columns:
        return [], len(text_unit_ids), None
    doc_ids: set[str] = set()
    text_unit_ids_set = set(text_unit_ids)
    for _, row in text_units.iterrows():
        if str(row.get("id")) not in text_unit_ids_set:
            continue
        doc_ids.update(_listify(row.get("document_ids")))
    if not doc_ids:
        return [], len(text_unit_ids), 0

    documents = graphml_export.read_parquet_optional(
        base_dir / "documents.parquet", "文档"
    )
    items: list[ReportDocumentItem] = []
    if documents is not None and {"id", "title"}.issubset(documents.columns):
        subset = documents[documents["id"].astype(str).isin(doc_ids)]
        subset = subset.head(document_limit)
        for _, row in subset.iterrows():
            items.append(
                ReportDocumentItem(
                    id=str(row.get("id")),
                    title=_safe_value(row.get("title")),
                    creation_date=_safe_value(row.get("creation_date")),
                )
            )
    else:
        for doc_id in list(doc_ids)[:document_limit]:
            items.append(ReportDocumentItem(id=str(doc_id), title=None, creation_date=None))

    return items, len(text_unit_ids), len(doc_ids)


def get_community_report_detail(
    collection_id: str | None,
    community_id: str,
    level: int | None,
    entity_limit: int,
    relationship_limit: int,
    document_limit: int,
) -> ReportCommunityDetailResponse:
    base_dir, resolved_collection_id = _load_reports_base_dir(collection_id)
    reports = graphml_export.read_parquet_or_error(
        base_dir / "community_reports.parquet", "社区报告"
    )
    communities = graphml_export.read_parquet_optional(
        base_dir / "communities.parquet", "社区数据"
    )

    detail = _load_detail_context(
        reports,
        communities,
        community_id,
        level,
    )

    entities_payload: list[ReportEntityItem] = []
    relationships_payload: list[ReportRelationshipItem] = []

    if detail.entity_ids:
        entities_df = graphml_export.read_parquet_optional(
            base_dir / "entities.parquet", "实体数据"
        )
        if entities_df is not None:
            subset = entities_df[entities_df["id"].astype(str).isin(detail.entity_ids)]
            subset = subset.sort_values(
                by=["degree", "frequency"], ascending=False, na_position="last"
            ).head(entity_limit)
            for _, row in subset.iterrows():
                entities_payload.append(
                    ReportEntityItem(
                        id=str(row.get("id")),
                        title=_safe_value(row.get("title")) or "",
                        type=_safe_value(row.get("type")),
                        description=_safe_value(row.get("description")),
                        degree=_safe_int(row.get("degree")),
                        frequency=_safe_int(row.get("frequency")),
                    )
                )

    if detail.relationship_ids:
        relationships_df = graphml_export.read_parquet_optional(
            base_dir / "relationships.parquet", "关系数据"
        )
        if relationships_df is not None:
            subset = relationships_df[
                relationships_df["id"].astype(str).isin(detail.relationship_ids)
            ]
            subset = subset.sort_values(
                by=["weight", "combined_degree"], ascending=False, na_position="last"
            ).head(relationship_limit)
            for _, row in subset.iterrows():
                relationships_payload.append(
                    ReportRelationshipItem(
                        id=str(row.get("id")),
                        source=_safe_value(row.get("source")) or "",
                        target=_safe_value(row.get("target")) or "",
                        description=_safe_value(row.get("description")),
                        weight=_safe_float(row.get("weight")),
                        combined_degree=_safe_float(row.get("combined_degree")),
                        text_unit_count=len(_listify(row.get("text_unit_ids")))
                        if row.get("text_unit_ids") is not None
                        else None,
                    )
                )

    documents_payload, text_unit_count, document_count = _load_documents_from_text_units(
        base_dir,
        detail.text_unit_ids,
        document_limit,
    )

    return ReportCommunityDetailResponse(
        collection_id=resolved_collection_id,
        community_id=detail.summary.community_id,
        human_readable_id=detail.summary.human_readable_id,
        level=detail.summary.level,
        parent=detail.summary.parent,
        children=detail.summary.children,
        title=detail.summary.title,
        summary=detail.summary.summary,
        findings=detail.summary.findings,
        rating=detail.summary.rating,
        size=detail.summary.size,
        document_count=document_count,
        text_unit_count=text_unit_count,
        entities=entities_payload,
        relationships=relationships_payload,
        documents=documents_payload,
    )


def list_patterns(
    collection_id: str | None,
    level: int | None,
    limit: int,
    sort: str | None,
) -> ReportPatternsResponse:
    base_dir, resolved_collection_id = _load_reports_base_dir(collection_id)
    reports = graphml_export.read_parquet_or_error(
        base_dir / "community_reports.parquet", "社区报告"
    )
    if level is not None and "level" in reports.columns:
        reports = reports[reports["level"] == level]

    reports = _sort_reports(reports, sort)
    items = []
    for _, row in reports.head(limit).iterrows():
        summary = _build_summary(row)
        items.append(
            ReportPatternItem(
                community_id=summary.community_id,
                title=summary.title,
                summary=summary.summary,
                findings=summary.findings,
                rating=summary.rating,
                size=summary.size,
                level=summary.level,
            )
        )

    entities_df = graphml_export.read_parquet_optional(
        base_dir / "entities.parquet", "实体数据"
    )
    relationships_df = graphml_export.read_parquet_optional(
        base_dir / "relationships.parquet", "关系数据"
    )
    documents_df = graphml_export.read_parquet_optional(
        base_dir / "documents.parquet", "文档"
    )

    return ReportPatternsResponse(
        collection_id=resolved_collection_id,
        level=level,
        total_communities=len(reports),
        total_entities=len(entities_df) if entities_df is not None else None,
        total_relationships=len(relationships_df) if relationships_df is not None else None,
        total_documents=len(documents_df) if documents_df is not None else None,
        count=len(items),
        items=items,
    )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException

from infra.persistence.backbone_codec import restore_frame_from_storage
from application.source.collection_service import CollectionService
from application.source.artifact_registry_service import ArtifactRegistryService
from controllers.schemas.derived.report import (
    ReportCommunityDetailResponse,
    ReportCommunityListResponse,
    ReportCommunitySummary,
    ReportDocumentItem,
    ReportEntityItem,
    ReportPatternItem,
    ReportPatternsResponse,
    ReportRelationshipItem,
)


_DOCUMENT_PROFILE_JSON_COLUMNS = (
    "protocol_extractability_signals",
    "parsing_warnings",
)
_EVIDENCE_CARD_JSON_COLUMNS = (
    "evidence_anchors",
    "material_system",
    "condition_context",
)
_COMPARISON_ROW_JSON_COLUMNS = (
    "supporting_evidence_ids",
    "comparability_warnings",
)

collection_service = CollectionService()
artifact_registry_service = ArtifactRegistryService()


@dataclass(frozen=True)
class _PatternGroup:
    community_id: int
    title: str
    summary: str
    findings: list[str]
    rating: float | None
    size: int
    level: int
    row_ids: list[str]
    evidence_ids: list[str]
    document_ids: list[str]
    text_unit_ids: list[str]


@dataclass(frozen=True)
class _CoreReportProjection:
    collection_id: str
    groups: list[_PatternGroup]
    document_profiles: dict[str, dict[str, Any]]
    evidence_cards: dict[str, dict[str, Any]]
    comparison_rows: dict[str, dict[str, Any]]


def _resolve_output_dir(collection_id: str | None) -> tuple[Path, str]:
    if not collection_id:
        raise HTTPException(status_code=400, detail="collection_id 不能为空")

    collection_service.get_collection(collection_id)
    try:
        artifacts = artifact_registry_service.get(collection_id)
        output_path = artifacts.get("output_path")
        if output_path:
            base_dir = Path(str(output_path)).expanduser().resolve()
            if base_dir.exists():
                return base_dir, collection_id
    except FileNotFoundError:
        pass

    paths = collection_service.get_paths(collection_id)
    base_dir = paths.output_dir.expanduser().resolve()
    if not base_dir.exists():
        raise HTTPException(status_code=404, detail="collection 输出目录不存在")
    return base_dir, collection_id


def _read_profiles(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "document_profiles.parquet"
    if not path.is_file():
        return pd.DataFrame()
    return restore_frame_from_storage(
        pd.read_parquet(path),
        _DOCUMENT_PROFILE_JSON_COLUMNS,
    )


def _read_evidence_cards(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "evidence_cards.parquet"
    if not path.is_file():
        return pd.DataFrame()
    return restore_frame_from_storage(
        pd.read_parquet(path),
        _EVIDENCE_CARD_JSON_COLUMNS,
    )


def _read_comparison_rows(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "comparison_rows.parquet"
    if not path.is_file():
        return pd.DataFrame()
    return restore_frame_from_storage(
        pd.read_parquet(path),
        _COMPARISON_ROW_JSON_COLUMNS,
    )


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except Exception:
        return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            text = _safe_text(item)
            if text:
                items.append(text)
        return items
    text = _safe_text(value)
    return [text] if text else []


def _extract_snippet_ids(anchors: Any) -> list[str]:
    payload = anchors if isinstance(anchors, list) else []
    snippet_ids: list[str] = []
    for anchor in payload:
        if not isinstance(anchor, dict):
            continue
        snippet_id = _safe_text(anchor.get("snippet_id"))
        if snippet_id and snippet_id not in snippet_ids:
            snippet_ids.append(snippet_id)
    return snippet_ids


def _build_group_title(material_name: str | None, property_name: str | None) -> str:
    parts = [part for part in (material_name, property_name) if part]
    if parts:
        return " | ".join(parts)
    return "Unspecified comparison pattern"


def _build_group_summary(size: int, document_count: int, evidence_count: int) -> str:
    return (
        f"{size} comparison rows, {evidence_count} evidence cards, "
        f"{document_count} documents."
    )


def _build_group_findings(
    rows: list[dict[str, Any]],
    comparable_count: int,
    limited_count: int,
    insufficient_count: int,
    not_comparable_count: int,
) -> list[str]:
    findings: list[str] = []
    if comparable_count > 0:
        findings.append(f"{comparable_count} rows are fully comparable.")
    if limited_count > 0:
        findings.append(f"{limited_count} rows remain limited by missing controls or conditions.")
    if insufficient_count > 0:
        findings.append(f"{insufficient_count} rows remain insufficient for direct judgment.")
    if not_comparable_count > 0:
        findings.append(f"{not_comparable_count} rows are not directly comparable.")

    values = [
        _safe_float(row.get("value"))
        for row in rows
        if _safe_float(row.get("value")) is not None
    ]
    if values:
        findings.append(
            f"Observed numeric values span {min(values):.2f} to {max(values):.2f}."
        )
    return findings


def _build_projection(collection_id: str) -> _CoreReportProjection:
    base_dir, resolved_collection_id = _resolve_output_dir(collection_id)
    profiles = _read_profiles(base_dir)
    evidence_cards = _read_evidence_cards(base_dir)
    comparison_rows = _read_comparison_rows(base_dir)

    document_lookup: dict[str, dict[str, Any]] = {}
    for _, row in profiles.iterrows():
        document_id = _safe_text(row.get("document_id"))
        if not document_id:
            continue
        document_lookup[document_id] = dict(row)

    evidence_lookup: dict[str, dict[str, Any]] = {}
    for _, row in evidence_cards.iterrows():
        evidence_id = _safe_text(row.get("evidence_id"))
        if not evidence_id:
            continue
        evidence_lookup[evidence_id] = dict(row)

    comparison_lookup: dict[str, dict[str, Any]] = {}
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for _, row in comparison_rows.iterrows():
        row_id = _safe_text(row.get("row_id"))
        if not row_id:
            continue
        payload = dict(row)
        comparison_lookup[row_id] = payload
        group_key = "||".join(
            [
                _safe_text(payload.get("material_system_normalized")) or "",
                _safe_text(payload.get("property_normalized")) or "",
            ]
        )
        grouped_rows.setdefault(group_key, []).append(payload)

    groups: list[_PatternGroup] = []
    sorted_items = sorted(
        grouped_rows.items(),
        key=lambda item: (
            -len(item[1]),
            _build_group_title(
                _safe_text(item[1][0].get("material_system_normalized")) if item[1] else None,
                _safe_text(item[1][0].get("property_normalized")) if item[1] else None,
            ),
        ),
    )

    for index, (_, rows) in enumerate(sorted_items, start=1):
        first_row = rows[0] if rows else {}
        material_name = _safe_text(first_row.get("material_system_normalized"))
        property_name = _safe_text(first_row.get("property_normalized"))
        evidence_ids: list[str] = []
        document_ids: list[str] = []
        text_unit_ids: list[str] = []
        comparable_count = 0
        limited_count = 0
        insufficient_count = 0
        not_comparable_count = 0

        for row in rows:
            source_document_id = _safe_text(row.get("source_document_id"))
            if source_document_id and source_document_id not in document_ids:
                document_ids.append(source_document_id)

            comparability = _safe_text(row.get("comparability_status")) or "limited"
            if comparability == "comparable":
                comparable_count += 1
            elif comparability == "limited":
                limited_count += 1
            elif comparability == "insufficient":
                insufficient_count += 1
            elif comparability == "not_comparable":
                not_comparable_count += 1

            for evidence_id in _string_list(row.get("supporting_evidence_ids")):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
                evidence = evidence_lookup.get(evidence_id, {})
                evidence_document_id = _safe_text(evidence.get("document_id"))
                if evidence_document_id and evidence_document_id not in document_ids:
                    document_ids.append(evidence_document_id)
                for snippet_id in _extract_snippet_ids(evidence.get("evidence_anchors")):
                    if snippet_id not in text_unit_ids:
                        text_unit_ids.append(snippet_id)

        size = len(rows)
        rating = round(comparable_count / size, 2) if size > 0 else None
        title = _build_group_title(material_name, property_name)
        summary = _build_group_summary(size, len(document_ids), len(evidence_ids))
        findings = _build_group_findings(
            rows,
            comparable_count=comparable_count,
            limited_count=limited_count,
            insufficient_count=insufficient_count,
            not_comparable_count=not_comparable_count,
        )
        groups.append(
            _PatternGroup(
                community_id=index,
                title=title,
                summary=summary,
                findings=findings,
                rating=rating,
                size=size,
                level=1,
                row_ids=[
                    _safe_text(row.get("row_id")) or ""
                    for row in rows
                    if _safe_text(row.get("row_id"))
                ],
                evidence_ids=evidence_ids,
                document_ids=document_ids,
                text_unit_ids=text_unit_ids,
            )
        )

    return _CoreReportProjection(
        collection_id=resolved_collection_id,
        groups=groups,
        document_profiles=document_lookup,
        evidence_cards=evidence_lookup,
        comparison_rows=comparison_lookup,
    )


def _sort_groups(groups: list[_PatternGroup], sort: str | None) -> list[_PatternGroup]:
    sort_key = (sort or "rating").lower()
    if sort_key == "size":
        return sorted(groups, key=lambda item: (-item.size, -(item.rating or 0.0), item.title))
    return sorted(groups, key=lambda item: (-(item.rating or 0.0), -item.size, item.title))


def _summary_from_group(group: _PatternGroup) -> ReportCommunitySummary:
    return ReportCommunitySummary(
        report_id=f"pattern-{group.community_id}",
        community_id=group.community_id,
        human_readable_id=group.community_id,
        level=group.level,
        parent=None,
        children=None,
        title=group.title,
        summary=group.summary,
        findings=group.findings,
        rating=group.rating,
        size=group.size,
    )


def _find_group(groups: list[_PatternGroup], community_id: str, level: int | None) -> _PatternGroup:
    matched = [group for group in groups if str(group.community_id) == str(community_id)]
    if level is not None:
        matched = [group for group in matched if group.level == level]
    if not matched:
        raise HTTPException(status_code=404, detail="未找到指定 pattern group")
    return matched[0]


def _build_detail_entities(
    projection: _CoreReportProjection,
    group: _PatternGroup,
    entity_limit: int,
) -> tuple[list[ReportEntityItem], dict[str, int]]:
    entities: list[tuple[int, int, ReportEntityItem]] = []
    degree_map: dict[str, int] = {}

    for document_id in group.document_ids:
        profile = projection.document_profiles.get(document_id, {})
        title = _safe_text(profile.get("title")) or _safe_text(profile.get("source_filename")) or document_id
        evidence_count = sum(
            1
            for evidence_id in group.evidence_ids
            if _safe_text(projection.evidence_cards.get(evidence_id, {}).get("document_id")) == document_id
        )
        comparison_count = sum(
            1
            for row_id in group.row_ids
            if _safe_text(projection.comparison_rows.get(row_id, {}).get("source_document_id")) == document_id
        )
        degree = evidence_count + comparison_count
        degree_map[f"doc:{document_id}"] = degree
        entities.append(
            (
                degree,
                comparison_count,
                ReportEntityItem(
                    id=f"doc:{document_id}",
                    title=title,
                    type="document",
                    description=_safe_text(profile.get("doc_type")),
                    degree=degree,
                    frequency=comparison_count,
                ),
            )
        )

    for evidence_id in group.evidence_ids:
        evidence = projection.evidence_cards.get(evidence_id, {})
        supported_rows = [
            row_id
            for row_id in group.row_ids
            if evidence_id
            in _string_list(projection.comparison_rows.get(row_id, {}).get("supporting_evidence_ids"))
        ]
        degree = len(supported_rows) + 1
        degree_map[f"evi:{evidence_id}"] = degree
        entities.append(
            (
                degree,
                len(supported_rows),
                ReportEntityItem(
                    id=f"evi:{evidence_id}",
                    title=_safe_text(evidence.get("claim_text")) or evidence_id,
                    type="evidence",
                    description=_safe_text(evidence.get("claim_type")),
                    degree=degree,
                    frequency=len(supported_rows),
                ),
            )
        )

    for row_id in group.row_ids:
        row = projection.comparison_rows.get(row_id, {})
        support_count = len(_string_list(row.get("supporting_evidence_ids")))
        degree_map[f"cmp:{row_id}"] = support_count
        entities.append(
            (
                support_count,
                support_count,
                ReportEntityItem(
                    id=f"cmp:{row_id}",
                    title=_build_group_title(
                        _safe_text(row.get("material_system_normalized")),
                        _safe_text(row.get("property_normalized")),
                    ),
                    type="comparison",
                    description=_safe_text(row.get("comparability_status")),
                    degree=support_count,
                    frequency=support_count,
                ),
            )
        )

    entities.sort(key=lambda item: (-item[0], -item[1], item[2].title))
    return [item[2] for item in entities[:entity_limit]], degree_map


def _build_detail_relationships(
    projection: _CoreReportProjection,
    group: _PatternGroup,
    relationship_limit: int,
    degree_map: dict[str, int],
) -> list[ReportRelationshipItem]:
    relationships: list[tuple[float, ReportRelationshipItem]] = []

    for evidence_id in group.evidence_ids:
        evidence = projection.evidence_cards.get(evidence_id, {})
        document_id = _safe_text(evidence.get("document_id"))
        evidence_title = _safe_text(evidence.get("claim_text")) or evidence_id
        snippet_ids = _extract_snippet_ids(evidence.get("evidence_anchors"))
        if document_id and document_id in group.document_ids:
            profile = projection.document_profiles.get(document_id, {})
            document_title = (
                _safe_text(profile.get("title"))
                or _safe_text(profile.get("source_filename"))
                or document_id
            )
            combined_degree = degree_map.get(f"doc:{document_id}", 0) + degree_map.get(
                f"evi:{evidence_id}", 0
            )
            relationships.append(
                (
                    float(combined_degree),
                    ReportRelationshipItem(
                        id=f"edge:doc:{document_id}:evi:{evidence_id}",
                        source=document_title,
                        target=evidence_title,
                        description="document_to_evidence",
                        weight=1.0,
                        combined_degree=float(combined_degree),
                        text_unit_count=len(snippet_ids) if snippet_ids else None,
                    ),
                )
            )

        for row_id in group.row_ids:
            row = projection.comparison_rows.get(row_id, {})
            if evidence_id not in _string_list(row.get("supporting_evidence_ids")):
                continue
            comparison_title = _build_group_title(
                _safe_text(row.get("material_system_normalized")),
                _safe_text(row.get("property_normalized")),
            )
            combined_degree = degree_map.get(f"evi:{evidence_id}", 0) + degree_map.get(
                f"cmp:{row_id}", 0
            )
            relationships.append(
                (
                    float(combined_degree),
                    ReportRelationshipItem(
                        id=f"edge:evi:{evidence_id}:cmp:{row_id}",
                        source=evidence_title,
                        target=comparison_title,
                        description="evidence_to_comparison",
                        weight=1.0,
                        combined_degree=float(combined_degree),
                        text_unit_count=len(snippet_ids) if snippet_ids else None,
                    ),
                )
            )

    relationships.sort(key=lambda item: (-item[0], item[1].id))
    return [item[1] for item in relationships[:relationship_limit]]


def _build_detail_documents(
    projection: _CoreReportProjection,
    group: _PatternGroup,
    document_limit: int,
) -> list[ReportDocumentItem]:
    items: list[ReportDocumentItem] = []
    for document_id in group.document_ids[:document_limit]:
        profile = projection.document_profiles.get(document_id, {})
        items.append(
            ReportDocumentItem(
                id=document_id,
                title=_safe_text(profile.get("title")) or _safe_text(profile.get("source_filename")),
                creation_date=None,
            )
        )
    return items


def list_community_reports(
    collection_id: str | None,
    level: int | None,
    limit: int,
    offset: int,
    min_size: int,
    sort: str | None,
) -> ReportCommunityListResponse:
    projection = _build_projection(collection_id or "")
    groups = projection.groups
    if level is not None:
        groups = [group for group in groups if group.level == level]
    if min_size > 0:
        groups = [group for group in groups if group.size >= min_size]
    groups = _sort_groups(groups, sort)
    total = len(groups)
    paged = groups[offset : offset + limit]

    return ReportCommunityListResponse(
        collection_id=projection.collection_id,
        level=level,
        total=total,
        count=len(paged),
        items=[_summary_from_group(group) for group in paged],
    )


def get_community_report_detail(
    collection_id: str | None,
    community_id: str,
    level: int | None,
    entity_limit: int,
    relationship_limit: int,
    document_limit: int,
) -> ReportCommunityDetailResponse:
    projection = _build_projection(collection_id or "")
    group = _find_group(projection.groups, community_id, level)
    summary = _summary_from_group(group)
    entities_payload, degree_map = _build_detail_entities(
        projection,
        group,
        entity_limit,
    )
    relationships_payload = _build_detail_relationships(
        projection,
        group,
        relationship_limit,
        degree_map,
    )
    documents_payload = _build_detail_documents(projection, group, document_limit)

    return ReportCommunityDetailResponse(
        collection_id=projection.collection_id,
        community_id=summary.community_id,
        human_readable_id=summary.human_readable_id,
        level=summary.level,
        parent=summary.parent,
        children=summary.children,
        title=summary.title,
        summary=summary.summary,
        findings=summary.findings,
        rating=summary.rating,
        size=summary.size,
        document_count=len(group.document_ids),
        text_unit_count=len(group.text_unit_ids),
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
    projection = _build_projection(collection_id or "")
    groups = projection.groups
    if level is not None:
        groups = [group for group in groups if group.level == level]
    groups = _sort_groups(groups, sort)

    items = [
        ReportPatternItem(
            community_id=group.community_id,
            title=group.title,
            summary=group.summary,
            findings=group.findings,
            rating=group.rating,
            size=group.size,
            level=group.level,
        )
        for group in groups[:limit]
    ]

    total_relationships = sum(
        len(group.evidence_ids) + sum(len(_string_list(projection.comparison_rows[row_id].get("supporting_evidence_ids"))) for row_id in group.row_ids)
        for group in groups
    )

    return ReportPatternsResponse(
        collection_id=projection.collection_id,
        level=level,
        total_communities=len(groups),
        total_entities=(
            len(projection.document_profiles)
            + len(projection.evidence_cards)
            + len(projection.comparison_rows)
        ),
        total_relationships=total_relationships,
        total_documents=len(projection.document_profiles),
        count=len(items),
        items=items,
    )


__all__ = [
    "get_community_report_detail",
    "list_community_reports",
    "list_patterns",
]

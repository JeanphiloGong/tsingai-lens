#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTION_ID = "col_c19de13a69c5"
DEFAULT_MATERIAL_ID = "mat-316l-stainless-steel"
DEFAULT_MAX_PROCESS_AXES = 6
DEFAULT_FORBIDDEN_TERMS = ("135 W-750",)
DEFAULT_FORBIDDEN_OBJECTIVE_DETAIL_TERMS = (
    "ductility of the 135 W-750",
    "increase the ductility by about 10%",
    "increased by about 10%",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check the real service projection used by collection objective and "
            "material frontend pages."
        )
    )
    parser.add_argument(
        "--collection-id",
        default=DEFAULT_COLLECTION_ID,
        help="Collection id to check.",
    )
    parser.add_argument(
        "--material-id",
        default=DEFAULT_MATERIAL_ID,
        help="Material id to check.",
    )
    parser.add_argument(
        "--max-process-axes",
        type=int,
        default=DEFAULT_MAX_PROCESS_AXES,
        help="Maximum display process-axis count allowed per objective.",
    )
    parser.add_argument(
        "--forbidden-term",
        action="append",
        dest="forbidden_terms",
        help="Forbidden text in the material research-view payload. May repeat.",
    )
    parser.add_argument(
        "--forbidden-objective-detail-term",
        action="append",
        dest="forbidden_objective_detail_terms",
        help="Forbidden text in every objective detail payload. May repeat.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_collection_frontend_projection(
        collection_id=args.collection_id,
        material_id=args.material_id,
        max_process_axes=args.max_process_axes,
        forbidden_terms=tuple(args.forbidden_terms or DEFAULT_FORBIDDEN_TERMS),
        forbidden_objective_detail_terms=tuple(
            args.forbidden_objective_detail_terms
            or DEFAULT_FORBIDDEN_OBJECTIVE_DETAIL_TERMS
        ),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_collection_frontend_projection(
    *,
    collection_id: str,
    material_id: str,
    max_process_axes: int = DEFAULT_MAX_PROCESS_AXES,
    forbidden_terms: tuple[str, ...] = DEFAULT_FORBIDDEN_TERMS,
    forbidden_objective_detail_terms: tuple[str, ...] = (
        DEFAULT_FORBIDDEN_OBJECTIVE_DETAIL_TERMS
    ),
) -> dict[str, Any]:
    backend_root = DEFAULT_BACKEND_ROOT
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from application.core.research_view_aggregation_service import (  # noqa: PLC0415
        ResearchViewAggregationService,
    )
    from application.core.semantic_build.research_objective_service import (  # noqa: PLC0415
        ResearchObjectiveService,
    )
    from application.source.collection_service import CollectionService  # noqa: PLC0415
    from infra.persistence.database import (  # noqa: PLC0415
        DatabaseSettings,
        build_database_engine,
        build_session_factory,
    )
    from infra.persistence.file import FileCollectionWorkspace  # noqa: PLC0415
    from infra.persistence.postgres.collection_repository import (  # noqa: PLC0415
        PostgresCollectionRepository,
    )
    from infra.persistence.postgres.source_artifact_repository import (  # noqa: PLC0415
        PostgresSourceArtifactRepository,
    )
    from infra.persistence.sqlite import (  # noqa: PLC0415
        SqliteSourceArtifactRepository,
    )

    engine = build_database_engine(DatabaseSettings())
    try:
        session_factory = build_session_factory(engine)
        collection_service = CollectionService(
            repository=PostgresCollectionRepository(session_factory),
            workspace=FileCollectionWorkspace(),
        )
        source_artifact_repository = PostgresSourceArtifactRepository(session_factory)
        source_reference_repository = SqliteSourceArtifactRepository(
            backend_root / "data" / "lens.sqlite"
        )
        objective_service = ResearchObjectiveService(
            collection_service=collection_service,
            source_artifact_repository=source_artifact_repository,
            source_reference_repository=source_reference_repository,
        )
        objectives = objective_service.list_objective_workspaces(collection_id)
        material_profile = (
            ResearchViewAggregationService(
                collection_service=collection_service,
                source_artifact_repository=source_artifact_repository,
            ).get_collection_material_research_view(
                collection_id,
                material_id,
            )
        )
        objective_details = [
            objective_service.get_objective_research_view(
                collection_id,
                str(row.get("objective_id") or ""),
            )
            for row in objectives.get("objectives", [])
            if isinstance(row, dict) and row.get("objective_id")
        ]
    finally:
        engine.dispose()
    return evaluate_frontend_projection_payloads(
        collection_id=collection_id,
        material_id=material_id,
        objectives=objectives,
        objective_details=objective_details,
        material_profile=material_profile,
        max_process_axes=max_process_axes,
        forbidden_terms=forbidden_terms,
        forbidden_objective_detail_terms=forbidden_objective_detail_terms,
    )


def evaluate_frontend_projection_payloads(
    *,
    collection_id: str,
    material_id: str,
    objectives: dict[str, Any],
    objective_details: list[dict[str, Any]] | None = None,
    material_profile: dict[str, Any],
    max_process_axes: int = DEFAULT_MAX_PROCESS_AXES,
    forbidden_terms: tuple[str, ...] = DEFAULT_FORBIDDEN_TERMS,
    forbidden_objective_detail_terms: tuple[str, ...] = (
        DEFAULT_FORBIDDEN_OBJECTIVE_DETAIL_TERMS
    ),
) -> dict[str, Any]:
    objective_rows = [
        row for row in objectives.get("objectives", []) if isinstance(row, dict)
    ]
    detail_rows = objective_details or []
    material_json = json.dumps(material_profile, ensure_ascii=False, sort_keys=True)
    measured_properties = [
        row
        for row in material_profile.get("measured_properties", [])
        if isinstance(row, dict)
    ]
    sample_matrix = material_profile.get("sample_matrix", {})
    sample_rows = (
        sample_matrix.get("rows", []) if isinstance(sample_matrix, dict) else []
    )

    checks = [
        _check(
            "objectives are available",
            bool(objective_rows),
            f"count={len(objective_rows)}",
        ),
        _check(
            "objective process axes stay display bounded",
            all(
                len(row.get("process_axes") or []) <= max_process_axes
                for row in objective_rows
            ),
            "max_actual="
            + str(
                max(
                    (len(row.get("process_axes") or []) for row in objective_rows),
                    default=0,
                )
            )
            + f"; max_allowed={max_process_axes}",
        ),
        _check(
            "material profile is ready",
            material_profile.get("state") == "ready",
            f"state={material_profile.get('state')}",
        ),
        _check(
            "material measured properties are available",
            bool(measured_properties),
            f"count={len(measured_properties)}",
        ),
        _check(
            "material sample matrix rows are available",
            bool(sample_rows),
            f"count={len(sample_rows)}",
        ),
        _check(
            "objective detail payloads are available",
            len(detail_rows) == len(objective_rows),
            f"count={len(detail_rows)}; expected={len(objective_rows)}",
        ),
    ]
    for term in forbidden_terms:
        checks.append(
            _check(
                f"material profile excludes forbidden term {term!r}",
                term not in material_json,
                f"present={term in material_json}",
            )
        )
    detail_json_by_objective_id = {
        str((detail.get("objective") or {}).get("objective_id") or index): json.dumps(
            detail,
            ensure_ascii=False,
            sort_keys=True,
        )
        for index, detail in enumerate(detail_rows)
        if isinstance(detail, dict)
    }
    for term in forbidden_objective_detail_terms:
        containing_objectives = [
            objective_id
            for objective_id, detail_json in detail_json_by_objective_id.items()
            if term in detail_json
        ]
        checks.append(
            _check(
                f"objective details exclude forbidden term {term!r}",
                not containing_objectives,
                "present_in="
                + (
                    ",".join(containing_objectives[:5])
                    if containing_objectives
                    else "none"
                ),
            )
        )

    return {
        "status": "fail"
        if any(check["status"] == "fail" for check in checks)
        else "pass",
        "collection_id": collection_id,
        "material_id": material_id,
        "objective_count": len(objective_rows),
        "objective_detail_count": len(detail_rows),
        "max_process_axis_count": max(
            (len(row.get("process_axes") or []) for row in objective_rows),
            default=0,
        ),
        "measured_property_count": len(measured_properties),
        "sample_matrix_row_count": len(sample_rows),
        "checks": checks,
    }


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "status": "pass" if passed else "fail",
        "name": name,
        "detail": detail,
    }


if __name__ == "__main__":
    main()

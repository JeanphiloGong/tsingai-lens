from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


CROSS_TABLE_CONTEXT_JOIN_CHECK = "measurement units include cross-table context joins"

_RESULT_ROUTE_ROLES = {"current_experimental_evidence"}
_CONTEXT_ROUTE_ROLES = {"process_or_treatment", "test_condition"}


def requires_cross_table_context_join(routes: Iterable[Any]) -> bool:
    """Return whether routed evidence structurally needs cross-table resolution."""
    result_sources_by_scope: dict[tuple[str, str], set[str]] = defaultdict(set)
    context_sources_by_scope: dict[tuple[str, str], set[str]] = defaultdict(set)

    for route in routes:
        if not _route_value(route, "extractable"):
            continue
        if _route_value(route, "source_kind") != "table":
            continue

        scope = (
            str(_route_value(route, "objective_id") or ""),
            str(_route_value(route, "document_id") or ""),
        )
        source_ref = str(_route_value(route, "source_ref") or "")
        if not scope[0] or not scope[1] or not source_ref:
            continue

        role = str(_route_value(route, "role") or "")
        if role in _RESULT_ROUTE_ROLES:
            result_sources_by_scope[scope].add(source_ref)
        if role in _CONTEXT_ROUTE_ROLES and _has_context_columns(route):
            context_sources_by_scope[scope].add(source_ref)

    for scope, result_sources in result_sources_by_scope.items():
        context_sources = context_sources_by_scope.get(scope, set())
        if context_sources - result_sources:
            return True
    return False


def build_cross_table_context_join_check(
    *,
    routes: Iterable[Any],
    measurement_units_with_context_join: int,
) -> dict[str, str]:
    required = requires_cross_table_context_join(routes)
    value = max(0, int(measurement_units_with_context_join))
    passed = value > 0 or not required
    if passed:
        status = "pass"
    else:
        status = "fail"
    suffix = "required" if required else "not_required"
    return {
        "status": status,
        "name": CROSS_TABLE_CONTEXT_JOIN_CHECK,
        "detail": f"value={value}; structural_requirement={suffix}",
    }


def _has_context_columns(route: Any) -> bool:
    column_roles = _route_value(route, "column_roles")
    if not isinstance(column_roles, Mapping):
        return True
    for role in column_roles.values():
        normalized = str(role or "").lower()
        if any(
            marker in normalized
            for marker in (
                "condition",
                "environment",
                "orientation",
                "parameter",
                "process",
                "sample",
                "speed",
                "temperature",
                "test",
                "treatment",
                "variable",
            )
        ):
            return True
    return False


def _route_value(route: Any, key: str) -> Any:
    if isinstance(route, Mapping):
        return route.get(key)
    return getattr(route, key, None)

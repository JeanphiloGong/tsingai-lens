from __future__ import annotations

from collections.abc import Mapping

from application.core.objectives import property_matching


def _downgrade_unresolved_relationships(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    studies = value.get("studies")
    unresolved_signals = value.get("unresolved_signals")
    if not isinstance(studies, list):
        return value
    if unresolved_signals is not None and not isinstance(unresolved_signals, list):
        return value

    retained_studies: list[object] = []
    downgraded_signals: list[dict[str, object]] = []
    changed = False
    for study in studies:
        if not isinstance(study, Mapping):
            retained_studies.append(study)
            continue
        relationships = study.get("relationships")
        if not isinstance(relationships, list):
            retained_studies.append(study)
            continue

        retained_relationships: list[object] = []
        study_changed = False
        for relationship in relationships:
            if not isinstance(relationship, Mapping):
                retained_relationships.append(relationship)
                continue
            factor_values = (
                relationship.get("factor_assertions")
                if "factor_assertions" in relationship
                else relationship.get("varied_factors")
            )
            has_varied_factor = not isinstance(factor_values, list) or (
                bool(factor_values)
                and all(
                    0
                    < len(
                        str(
                            item.get("label") if isinstance(item, Mapping) else item
                        ).strip()
                    )
                    <= 80
                    for item in factor_values
                )
            )
            outcome = str(relationship.get("outcome") or "").strip()
            if has_varied_factor and not property_matching.outcome_label_requires_resolution(
                outcome
            ):
                retained_relationships.append(relationship)
                continue
            lineage_field = (
                "source_labels" if "source_labels" in relationship else "source_unit_ids"
            )
            lineage_values = relationship.get(lineage_field)
            if (
                not outcome
                or len(outcome) > 80
                or not isinstance(lineage_values, list)
                or not any(str(item).strip() for item in lineage_values)
            ):
                retained_relationships.append(relationship)
                continue

            signal = {
                "signal_type": "outcome",
                "label": outcome,
                "variable_role": "not_applicable",
                lineage_field: list(lineage_values),
                "confidence": relationship.get("confidence", study.get("confidence")),
            }
            for field_name in (
                "experiment_label",
                "design_type",
                "claim_scope",
                "material_scope",
                "process_context",
            ):
                if field_name in study:
                    signal[field_name] = study[field_name]
            downgraded_signals.append(signal)
            study_changed = True
            changed = True

        if retained_relationships or not study_changed:
            retained_study = dict(study)
            retained_study["relationships"] = retained_relationships
            retained_studies.append(retained_study)

    if not changed:
        return value
    normalized = dict(value)
    normalized["studies"] = retained_studies
    normalized["unresolved_signals"] = [
        *(unresolved_signals or []),
        *downgraded_signals,
    ]
    return normalized

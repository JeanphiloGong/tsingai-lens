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
    if "unresolved_signals" in value and not isinstance(unresolved_signals, list):
        return value

    retained_studies: list[object] = []
    downgraded_signals: list[dict[str, object]] = []
    changed = False
    for study in studies:
        if not isinstance(study, Mapping) or set(study) - {
            "experiment_label", "design_type", "claim_scope", "material_scope",
            "process_context", "relationships", "confidence",
        }:
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
            factor_values = relationship.get("factor_assertions")
            if (
                set(relationship)
                - {"factor_assertions", "outcome", "source_labels", "confidence"}
                or not isinstance(factor_values, list)
                or any(
                    not isinstance(item, Mapping)
                    or set(item) - {"label", "role", "source_labels"}
                    or not isinstance(item.get("label"), str)
                    or not isinstance(item.get("role"), str)
                    or item.get("role") not in {"varied", "compared", "modeled"}
                    or not isinstance(item.get("source_labels"), list)
                    or not item["source_labels"]
                    or any(
                        not isinstance(label, str) for label in item["source_labels"]
                    )
                    or len(item["source_labels"]) != len(set(item["source_labels"]))
                    for item in factor_values
                )
            ):
                retained_relationships.append(relationship)
                continue
            factor_labels = [item["label"].strip().casefold() for item in factor_values]
            if len(factor_labels) != len(set(factor_labels)):
                retained_relationships.append(relationship)
                continue
            if "confidence" in study and (
                type(study["confidence"]) not in {int, float}
                or not 0 <= study["confidence"] <= 1
            ):
                retained_relationships.append(relationship)
                continue
            has_varied_factor = bool(factor_values) and all(
                0 < len(item["label"].strip()) <= 80 for item in factor_values
            )
            outcome = relationship.get("outcome")
            if not isinstance(outcome, str):
                retained_relationships.append(relationship)
                continue
            outcome = outcome.strip()
            if (
                has_varied_factor
                and not property_matching.outcome_label_requires_resolution(outcome)
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
                or not lineage_values
                or any(not isinstance(item, str) for item in lineage_values)
                or len(lineage_values) != len(set(lineage_values))
            ):
                retained_relationships.append(relationship)
                continue

            signal = {
                "signal_type": "outcome",
                "label": outcome,
                "variable_role": "not_applicable",
                lineage_field: list(
                    dict.fromkeys(
                        [
                            *lineage_values,
                            *(
                                label
                                for assertion in factor_values
                                for label in assertion["source_labels"]
                            ),
                        ]
                    )
                ),
            }
            if "confidence" in relationship:
                signal["confidence"] = relationship["confidence"]
            elif "confidence" in study:
                signal["confidence"] = study["confidence"]
            for field_name, field_value in study.items():
                if field_name not in {"relationships", "confidence"}:
                    signal[field_name] = field_value
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

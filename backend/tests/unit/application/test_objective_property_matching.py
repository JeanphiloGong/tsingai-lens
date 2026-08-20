import pytest

from application.core.objectives import property_matching


@pytest.mark.parametrize(
    ("source_label", "canonical_label"),
    (
        ("UTS [MPa]", "ultimate tensile strength"),
        ("TE (%)", "total elongation"),
        ("\u03c3y (MPa)", "yield strength"),
        ("Icorr (A/cm2)", "corrosion current density"),
        ("Max. defect diameter (LCSM)", "max defect diameter"),
    ),
)
def test_normalize_property_label_preserves_source_alias_behavior(
    source_label: str,
    canonical_label: str,
) -> None:
    assert (
        property_matching.normalize_property_label(source_label) == canonical_label
    )


def test_broad_objective_matches_specific_measurement() -> None:
    assert property_matching.property_matches_target_axes(
        "mechanical properties",
        target_axes=("yield strength",),
    )
    assert property_matching.source_text_mentions_axis(
        "The measured relative density was 99.2%.",
        "densification",
    )


@pytest.mark.parametrize(
    ("outcome", "requires_resolution"),
    (
        ("microstructure", True),
        ("defect structure", True),
        ("corrosion resistance", True),
        ("grain morphology", False),
        ("fatigue strength", False),
        ("relative density", False),
    ),
)
def test_only_multi_measurement_outcome_families_require_resolution(
    outcome: str,
    requires_resolution: bool,
) -> None:
    assert (
        property_matching.outcome_label_requires_resolution(outcome)
        is requires_resolution
    )


def test_density_match_ignores_energy_density_phrase() -> None:
    assert not property_matching.source_text_mentions_axis(
        "The volumetric energy density was 80 J/mm3.",
        "density",
    )


def test_process_symbol_hints_preserve_current_context_mapping() -> None:
    assert property_matching.process_column_axis_keys("\u03b8") == {
        "scan strategy rotation angle"
    }
    assert property_matching.process_column_axis_keys("\u03b1") == {
        "build orientation alpha angle"
    }


def test_axis_matching_preserves_explicit_synonyms_and_source_aliases() -> None:
    assert property_matching.axis_values_match(
        "scan strategy",
        "scanning strategy",
    )
    assert property_matching.axis_values_match(
        "preheating",
        "base plate preheating temperature",
    )
    assert property_matching.axis_values_match(
        "cracking",
        "crack formation",
    )
    assert property_matching.source_text_mentions_axis("E p", "pitting potential")


@pytest.mark.parametrize(
    ("source_label", "objective_axes", "expected"),
    (
        ("Laser power (W)", ("laser power",), "laser power"),
        (
            "preheating",
            ("base plate preheating temperature",),
            "base plate preheating temperature",
        ),
        ("density", ("density", "relative density"), "density"),
        ("unmapped condition", ("laser power",), None),
    ),
)
def test_resolve_objective_axis_requires_one_unambiguous_match(
    source_label: str,
    objective_axes: tuple[str, ...],
    expected: str | None,
) -> None:
    assert (
        property_matching.resolve_objective_axis(source_label, objective_axes)
        == expected
    )


def test_generic_model_roles_do_not_replace_specific_source_labels() -> None:
    assert not property_matching.process_role_is_specific("parameter variable")
    assert property_matching.process_role_is_specific("laser power")
    assert not property_matching.result_role_is_specific_property("predicted result")
    assert property_matching.result_role_is_specific_property("yield strength")

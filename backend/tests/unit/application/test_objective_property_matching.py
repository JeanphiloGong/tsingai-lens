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


@pytest.mark.parametrize(
    "outcome",
    ("anisotropic mechanical properties", "microstructural anisotropy"),
)
def test_modified_broad_outcome_families_require_resolution(outcome: str) -> None:
    assert property_matching.outcome_label_requires_resolution(outcome)


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


def test_variable_theme_membership_does_not_create_axis_equivalence() -> None:
    assert property_matching.shared_variable_theme(
        (
            ("annealing temperature",),
            ("solution temperature", "aging temperature"),
            ("HIP temperature",),
        )
    ) == "thermal post-processing condition"
    assert property_matching.variable_matches_objective_scope(
        "annealing temperature",
        "thermal post-processing condition",
    )
    assert property_matching.variable_matches_objective_scope(
        "HIP temperature",
        "thermal post-processing condition",
    )
    assert property_matching.variable_matches_objective_scope(
        "Solubility temperatures ° C",
        "thermal post-processing condition",
    )
    assert not property_matching.axis_values_match(
        "annealing temperature",
        "HIP temperature",
    )
    assert (
        property_matching.resolve_objective_axis(
            "annealing temperature",
            ("thermal post-processing condition",),
        )
        is None
    )


def test_energy_input_scope_covers_precise_laser_interventions_without_equating_them() -> None:
    assert property_matching.variable_matches_objective_scope(
        "laser power",
        "energy input",
    )
    assert property_matching.variable_matches_objective_scope(
        "scan speed",
        "energy input",
    )
    assert property_matching.variable_matches_objective_scope(
        "volumetric energy density",
        "energy input (laser power, scan speed, energy density)",
    )
    assert not property_matching.axis_values_match("laser power", "scan speed")
    assert (
        property_matching.resolve_objective_axis(
            "laser power",
            ("energy input (laser power, scan speed, energy density)",),
        )
        is None
    )


def test_source_text_matches_normalized_objective_outcome_alias() -> None:
    assert property_matching.source_text_mentions_axis(
        "Increasing laser power enhanced elongation from 15.4% to 20.1%.",
        "ductility",
    )


@pytest.mark.parametrize(
    "source_text",
    (
        "Input current (induction heater), I",
        "The inductive energy was increased during deposition.",
        "The induction heating input current was 200 A.",
    ),
)
def test_energy_input_scope_covers_induction_heating_energy(source_text: str) -> None:
    assert property_matching.source_text_mentions_objective_variable(
        source_text,
        "energy input",
    )


def test_build_preheating_is_outside_the_thermal_post_processing_theme() -> None:
    assert not property_matching.variable_matches_objective_scope(
        "base plate preheating temperature",
        "thermal post-processing condition",
    )
    assert property_matching.variable_matches_objective_scope(
        "base plate preheating temperature",
        "build preheating condition",
    )
    assert property_matching.source_text_mentions_objective_variable(
        "The annealing temperature was increased to 850 C.",
        "thermal post-processing condition",
    )


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


def test_material_scope_matching_distinguishes_alias_broad_and_conflicting_labels() -> None:
    assert property_matching.material_values_match_for_scope(
        "TiAl6V4 alloy",
        "Ti-6Al-4V",
    )
    assert property_matching.material_values_match_for_scope(
        "titanium alloy",
        "Ti-6Al-4V",
    )
    assert not property_matching.material_scope_value_is_specific(
        "metal additively manufactured material"
    )
    assert property_matching.material_scope_value_is_broad(
        "metal additively manufactured material"
    )
    assert not property_matching.material_scope_value_is_broad(
        "aerospace components"
    )
    assert property_matching.material_scope_value_is_specific("Al7075")
    assert property_matching.material_scope_value_is_specific("316L")
    assert property_matching.material_scope_value_is_specific("17-4PH")
    assert not property_matching.material_values_match_for_scope(
        "Al7075",
        "Ti-6Al-4V",
    )
    assert property_matching.material_value_matches_objective_comparison_scope(
        "TiAl6V4 alloy",
        "Ti-6Al-4V",
    )
    assert property_matching.material_value_matches_objective_comparison_scope(
        "stainless steel 316L",
        "316L stainless steel",
    )
    assert not property_matching.material_value_matches_objective_comparison_scope(
        "titanium alloy",
        "Ti-6Al-4V",
    )
    assert not property_matching.material_value_matches_objective_comparison_scope(
        "17-4PH stainless steel",
        "Ti-6Al-4V",
    )

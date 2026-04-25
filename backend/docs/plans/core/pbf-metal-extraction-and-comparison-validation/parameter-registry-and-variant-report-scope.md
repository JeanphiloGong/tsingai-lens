# PBF-Metal Parameter Registry And Variant Report Scope

## Summary

This document records how the long LPBF and EB-PBF metal parameter table
should be used in the current PBF-metal validation wave.

The table is a domain ontology seed and backend parameter registry input.

It is not:

- the first-version extraction field list
- the first-version user-facing report schema
- a flat UI table that exposes every possible metal-AM parameter at once

The first version should narrow that ontology into one evidence-backed
Material Variant Report that is precise enough for review and comparison.

## Placement In The Stack

The parameter table belongs in this order:

```text
domain parameter registry
-> extraction schema
-> paper facts
-> material variant report
-> comparison view
```

That placement keeps one clear separation:

- the registry defines what the system can recognize and normalize
- `paper_facts` records extracted and traceable facts
- the Material Variant Report decides what the reader sees first

The report should stay reader-centered. The registry can stay broader.

## First-Version Boundary

The first version should not try to support the whole ontology.

The first version should support roughly three dozen Level 1 fields that are
enough to answer the core PBF-metal review questions:

- what alloy or material system is this
- what powder condition was used
- what process window defined the variant
- what post-processing changed the final state
- how good was the build quality
- what property results were reported
- what microstructure evidence explains those results
- where is the source evidence

Everything outside that first boundary should stay secondary or deferred even
if it remains in the long-term parameter registry.

## Level 1 Fields

These fields define the first-version Material Variant Report scope.

### Material Identity

- `alloy_designation`
- `nominal_composition`

### Feedstock Powder

- `particle_size_median`
- `particle_size_bounds`
- `oxygen_in_powder`
- `carbon_in_powder`
- `nitrogen_in_powder`
- `apparent_powder_density`
- `tap_powder_density`
- `hall_flow_time`

### Core PBF Process Parameters

- `pbf_modality`
- `laser_power`
- `scan_speed`
- `hatch_spacing`
- `layer_thickness`
- `volumetric_energy_density`
- `build_orientation`
- `chamber_oxygen_content`
- `process_gas_composition`
- `substrate_preheat_temperature`

### Post-Processing

- `hot_isostatic_pressing_cycle`
- `solution_and_aging_treatment`

### Build Quality

- `relative_density`
- `porosity_volume_fraction`
- `lack_of_fusion_defect_fraction`
- `surface_roughness_ra`

### Mechanical Properties

- `yield_strength`
- `ultimate_tensile_strength`
- `elongation_at_fracture`
- `vickers_hardness`
- `fatigue_life`
- `fatigue_strength`

### Microstructure

- `grain_size`
- `texture_strength`
- `phase_volume_fraction`
- `residual_stress`

This is enough for a first report surface without turning the backend into a
generic parameter warehouse.

## Level 2 Fields

These fields may be recognized and stored when evidence is strong, but they
should stay out of the first report summary and out of the first hard
acceptance scope:

- `angle_of_repose`
- `hausner_ratio`
- `true_powder_density`
- `gas_flow_rate`
- `beam_spot_diameter`
- `defocus_distance`
- `interlayer_hatch_rotation`
- `scan_strategy_class`
- `contour_laser_power`
- `contour_scan_speed`
- `core_laser_power`
- `number_of_contour_passes`
- `melt_pool_depth`
- `melt_pool_width`
- `melt_pool_length`
- `cooling_rate`
- `thermal_gradient`

These are valid advanced fields. They are not the first review surface.

## Level 3 Fields

These fields are useful for later mechanistic and crystallographic work, but
they should not be a first-version extraction commitment:

- `space_group_number`
- `lattice_parameter_a`
- `lattice_parameter_c`
- `c_over_a_ratio`
- `high_angle_grain_boundary_fraction`
- `low_angle_grain_boundary_fraction`
- `sigma3_twin_boundary_fraction`
- `taylor_factor`
- `schmid_factor`
- `dislocation_density`
- `gnd_density`
- `precipitate_mean_radius`
- `precipitate_volume_fraction`
- `precipitate_number_density`
- `inclusion_volume_fraction`

## Level 4 Fields

These fields should stay outside the first-version scope even if they remain
valid future registry entries:

- `recoater_type`
- `recoater_speed`
- `stripe_width`
- `island_size`
- `island_overlap`
- `vector_length`
- `laser_duty_cycle`
- `pulse_repetition_frequency`
- `pulse_width`
- `pulse_energy`
- `peak_laser_power`
- `baseplate_thickness`
- `build_plate_temperature_uniformity`
- `laser_to_laser_stitch_offset`
- `multi_laser_overlap_width`
- `spatter_mass_rate`
- `denudation_zone_width`
- `powder_layer_packing_fraction`

## Reader-Facing Report Shape

The first front-end surface should not show the ontology as a 100-plus-column
parameter table.

The first front-end surface should be a Material Variant Report with these
sections:

1. Variant summary
   - alloy, modality, defining process window, post-treatment, confidence
2. Feedstock
   - powder size, oxygen, powder density, flowability when reported
3. Processing parameters
   - power, speed, hatch spacing, layer thickness, VED, atmosphere, preheat
4. Post-processing
   - HIP and heat-treatment history
5. Build quality
   - density, porosity, lack-of-fusion fraction, roughness
6. Mechanical properties
   - yield strength, UTS, elongation, hardness, fatigue when relevant
7. Microstructure
   - grain size, texture, phase fraction, residual stress
8. Comparison and baseline
   - current variant versus explicit baseline or untreated state
9. Evidence and warnings
   - source quotes, unresolved bindings, missing context, value-origin warnings

This shape keeps the primary reader job intact:

review one variant, understand the process and result state, then compare it
against adjacent variants.

## Registry And Fact Model

The ontology should enter the backend as a parameter registry, not as a fixed
report table.

One registry record should look like:

```json
{
  "parameter_id": "laser_power",
  "full_name": "Laser Power",
  "aliases": ["laser power", "P"],
  "category": "process_parameter",
  "canonical_unit": "W",
  "units_allowed": ["W", "kW"],
  "domain": ["metal_am", "lpbf"],
  "mvp_level": 1,
  "applies_to": "variant",
  "display_priority": "primary",
  "is_derived": false,
  "comparable_required_context": []
}
```

One extracted fact should bind back to that registry:

```json
{
  "parameter_id": "laser_power",
  "value": 280,
  "unit": "W",
  "value_origin": "reported",
  "source_anchor_ids": ["anchor_123"],
  "applies_to_variant_id": "variant_456",
  "confidence": 0.91
}
```

This avoids hard-coding every future field into one ever-growing variant row
schema.

## Binding And Normalization Rules

The first-version implementation should keep five rules explicit.

### Variant-Defining Fields And Result Fields Stay Separate

Process variables such as `laser_power`, `scan_speed`, `layer_thickness`, and
`solution_and_aging_treatment` define the variant.

Measured outcomes such as `yield_strength`, `relative_density`, `porosity`,
and `grain_size` describe the variant state or result.

They should not be flattened into one undifferentiated parameter bag.

### Reported And Derived Values Stay Separate

The backend should preserve `value_origin` using the same minimum vocabulary
already planned for the PBF-metal wave:

- `reported`
- `derived`
- `normalized`
- `inferred`

This is especially important for volumetric energy density.

The system must distinguish:

- a value directly reported by the paper
- a value derived locally from power, speed, hatch spacing, and layer
  thickness

Supporting fields should preserve:

- `source_value_text`
- `source_unit_text`
- `derivation_formula`

### Required Context Drives Comparability

Result facts need required context before they can become reliable comparison
objects.

Examples:

- `yield_strength` should carry test method, temperature, strain rate, and
  orientation when available
- `fatigue_life` should carry stress amplitude, R-ratio, frequency, and runout
  criterion when available
- `residual_stress` should carry method and measurement direction when
  available

Missing required context should degrade comparison readiness rather than being
silently ignored.

### LLM Output Should Stay Narrow

The model should identify raw parameter mentions, result claims, and evidence
quotes.

Deterministic backend code should own:

- alias matching
- unit parsing
- canonical `parameter_id` binding
- `value_origin` assignment
- normalization into report sections

This matches the existing direction to keep text-window extraction atomic and
keep backend binding deterministic.

### Unresolved Bindings Should Stay Visible

If a parameter phrase cannot be bound to a canonical registry entry or to one
variant state, the system should keep that missingness explicit.

The report should surface unresolved or low-confidence facts as warnings
rather than flattening them into normal comparison output.

## Effect On The Current Validation Wave

This scope sharpens the current PBF-metal plan family in four ways.

1. Slice 3 should target the Level 1 field set first, not the whole ontology.
2. The first user-facing acceptance surface should be the Material Variant
   Report, not a raw parameter spreadsheet.
3. The long parameter table should become backend registry input, not a fixed
   UI or storage table.
4. LLM prompts should optimize for recognizable parameter mentions and
   evidence quotes, while deterministic backend code owns final parameter
   binding.

That keeps the current wave focused on report usefulness and evidence-backed
comparison rather than ontology completeness.

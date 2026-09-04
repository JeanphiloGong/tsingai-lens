#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import tiktoken
from _common import (
    add_runtime_arguments,
    build_openai_client,
    coerce_message_text,
    display_base_url,
    ensure_backend_root_on_path,
    extract_json_object,
    resolve_runtime,
    summarize_timings,
    write_json_output,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
ensure_backend_root_on_path(_BACKEND_ROOT)

_study_window = importlib.import_module(
    "application.core.objectives.discovery.study_window"
)
StructuredExperimentalPaperMap = _study_window.StructuredExperimentalPaperMap
_paper_map_model_payload = _study_window._paper_map_model_payload
build_paper_research_map_prompt = _study_window.build_paper_research_map_prompt


VariantRequestMode = Literal["json_object", "provider_parse"]


@dataclass(frozen=True)
class PromptVariant:
    variant_id: str
    system_prompt: str
    user_prompt: str
    request_mode: VariantRequestMode
    schema_delivery: str


@dataclass(frozen=True)
class ProbeScenario:
    scenario_id: str
    description: str
    payload: dict[str, Any]
    expectation: dict[str, Any]


_COMPACT_SYSTEM_PROMPT = """
You map explicit research scope from one paper's high-level Sources.
This is Objective discovery, not experiment reconstruction or Evidence extraction.
Use only supplied scientific content and copy only supplied Source labels.
Return one JSON object without commentary.
""".strip()


_COMPACT_OUTPUT_CONTRACT = r"""
OUTPUT SHAPE
{"doc_role":"experimental|modeling|mixed|uncertain","studies":[{"experiment_label":null,"design_type":"experimental|observational|modeling|mixed|uncertain","claim_scope":"current_work|background|uncertain","material_scope":[],"process_context":[],"relationships":[{"factor_assertions":[{"label":"","role":"varied|compared|modeled","source_labels":["S1"]}],"outcome":"","source_labels":["S1"],"confidence":0.0}],"confidence":0.0}],"unresolved_signals":[{"signal_type":"variable|outcome","label":"","variable_role":"varied|compared|modeled|fixed|context|uncertain|not_applicable","experiment_label":null,"design_type":"experimental|observational|modeling|mixed|uncertain","claim_scope":"current_work|background|uncertain","material_scope":[],"process_context":[],"source_labels":["S1"],"confidence":0.0}],"output_saturated":false,"evidence_density":"high|medium|low|unknown","confidence":0.0,"warnings":[]}

Limits: at most 2 studies, 6 relationships per study, 4 unresolved signals, 6 factors per relationship, 4 unique Source labels per item, and 2 short warnings. Use empty arrays when unsupported. Unresolved signals represent incomplete links, not relationship overflow. Set output_saturated=true if a supported relationship or other scientific item exceeds these limits.
""".strip()


_COMPACT_FEW_SHOTS = r"""
BOUNDARY FEW-SHOTS
JOINT FACTORS
Source: "We jointly varied laser power and scan speed and measured porosity."
Output: {"doc_role":"experimental","studies":[{"design_type":"experimental","claim_scope":"current_work","relationships":[{"factor_assertions":[{"label":"laser power","role":"varied","source_labels":["S1"]},{"label":"scan speed","role":"varied","source_labels":["S1"]}],"outcome":"porosity","source_labels":["S1"],"confidence":0.9}]}],"unresolved_signals":[],"output_saturated":false,"evidence_density":"high","confidence":0.9,"warnings":[]}

BROAD OUTCOME
Source: "Heat treatment changed the microstructure." No measurement identity is named.
Output: {"doc_role":"experimental","studies":[],"unresolved_signals":[{"signal_type":"variable","label":"heat treatment","variable_role":"varied","claim_scope":"current_work","source_labels":["S1"],"confidence":0.7},{"signal_type":"outcome","label":"microstructure","variable_role":"not_applicable","claim_scope":"current_work","source_labels":["S1"],"confidence":0.7}],"output_saturated":false,"evidence_density":"low","confidence":0.7,"warnings":[]}

CITED BACKGROUND
Source: "Miranda et al. increased build plate temperature and reduced residual stress."
Output: {"doc_role":"uncertain","studies":[{"experiment_label":"Miranda et al.","design_type":"uncertain","claim_scope":"background","relationships":[{"factor_assertions":[{"label":"build plate temperature","role":"varied","source_labels":["S1"]}],"outcome":"residual stress","source_labels":["S1"],"confidence":0.8}]}],"unresolved_signals":[],"output_saturated":false,"evidence_density":"low","confidence":0.8,"warnings":[]}

EXPLICIT CONFIGURATION EFFECT
Source: "PTA leading with front wire feeding gave stable deposition and good bead appearance."
Output: {"doc_role":"experimental","studies":[{"design_type":"experimental","claim_scope":"current_work","relationships":[{"factor_assertions":[{"label":"heat-source configuration","role":"compared","source_labels":["S1"]},{"label":"wire-feeding direction","role":"compared","source_labels":["S1"]}],"outcome":"deposition stability","source_labels":["S1"],"confidence":0.9},{"factor_assertions":[{"label":"heat-source configuration","role":"compared","source_labels":["S1"]},{"label":"wire-feeding direction","role":"compared","source_labels":["S1"]}],"outcome":"bead appearance","source_labels":["S1"],"confidence":0.9}]}],"unresolved_signals":[],"output_saturated":false,"evidence_density":"high","confidence":0.9,"warnings":[]}

NO SIGNAL
Source: "Additive manufacturing is widely used in aerospace."
Output: {"doc_role":"uncertain","studies":[],"unresolved_signals":[],"output_saturated":false,"evidence_density":"low","confidence":0.8,"warnings":[]}
""".strip()


def default_scenarios() -> tuple[ProbeScenario, ...]:
    return (
        ProbeScenario(
            scenario_id="joint_factors",
            description=(
                "One current-work LPBF scope jointly varies two factors and names two "
                "specific outcomes."
            ),
            payload=_scenario_payload(
                source_unit_id="source-unit-complete-1",
                title="Joint process-parameter effects in LPBF Ti-6Al-4V",
                content=(
                    "In this work, Ti-6Al-4V specimens were produced by laser powder bed "
                    "fusion. Laser power and scan speed were jointly varied, and porosity "
                    "and tensile strength were measured."
                ),
            ),
            expectation={
                "kind": "joint_factors",
                "factor_set": ["laser power", "scan speed"],
                "outcomes": ["porosity", "tensile strength"],
            },
        ),
        ProbeScenario(
            scenario_id="broad_outcome",
            description=(
                "A current-work statement names a treatment and only a broad outcome "
                "family, so it must remain unresolved."
            ),
            payload=_scenario_payload(
                source_unit_id="source-unit-broad-1",
                title="Heat-treated Ti-6Al-4V",
                content=(
                    "In this study, heat treatment was applied to LPBF Ti-6Al-4V and "
                    "changed the microstructure. No specific microstructural measurement "
                    "is identified in this summary."
                ),
            ),
            expectation={
                "kind": "broad_outcome",
                "broad_outcome": "microstructure",
            },
        ),
        ProbeScenario(
            scenario_id="cited_background",
            description=(
                "A named prior study must not be represented as the current paper's work."
            ),
            payload=_scenario_payload(
                source_unit_id="source-unit-cited-1",
                title="Background review of LPBF residual stress",
                content=(
                    "Miranda et al. [20] increased build plate temperature and reported "
                    "lower residual stress. The present paragraph states no experiment "
                    "performed by this paper."
                ),
            ),
            expectation={"kind": "cited_background"},
        ),
        ProbeScenario(
            scenario_id="no_signal",
            description="General background must not become a study or unresolved signal.",
            payload=_scenario_payload(
                source_unit_id="source-unit-empty-1",
                title="Additive manufacturing overview",
                content="Additive manufacturing is widely used in aerospace applications.",
            ),
            expectation={"kind": "no_signal"},
        ),
    )


def load_scenarios(path: Path) -> tuple[ProbeScenario, ...]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    raw_scenarios = (
        payload.get("scenarios") if isinstance(payload, Mapping) else payload
    )
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("scenario file must contain a non-empty 'scenarios' list")

    scenarios: list[ProbeScenario] = []
    scenario_ids: set[str] = set()
    for position, item in enumerate(raw_scenarios, start=1):
        if not isinstance(item, Mapping):
            raise TypeError(f"scenario {position} must be a JSON object")
        scenario_id = str(item.get("scenario_id") or "").strip()
        if not scenario_id:
            raise ValueError(f"scenario {position} has no scenario_id")
        if scenario_id in scenario_ids:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        scenario_ids.add(scenario_id)

        scenario_payload = item.get("payload")
        if not isinstance(scenario_payload, Mapping):
            raise TypeError(f"scenario {scenario_id} has no payload object")
        normalized_payload = dict(scenario_payload)
        _paper_map_model_payload(normalized_payload)

        expectation = item.get("expectation") or {"kind": "structural"}
        if not isinstance(expectation, Mapping):
            raise TypeError(f"scenario {scenario_id} expectation must be an object")
        expectation_kind = str(expectation.get("kind") or "").strip()
        if expectation_kind not in {
            "joint_factors",
            "broad_outcome",
            "cited_background",
            "no_signal",
            "structural",
            "required_relationships",
        }:
            raise ValueError(
                f"scenario {scenario_id} has unsupported expectation kind: "
                f"{expectation_kind or '<empty>'}"
            )
        scenarios.append(
            ProbeScenario(
                scenario_id=scenario_id,
                description=str(item.get("description") or "").strip(),
                payload=normalized_payload,
                expectation=dict(expectation),
            )
        )
    return tuple(scenarios)


def _scenario_payload(
    *,
    source_unit_id: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "document_profile": {"doc_type": "experimental"},
        "window_id": "overview-1",
        "window_role": "overview",
        "source_units": [
            {
                "source_unit_id": source_unit_id,
                "source_kind": "block",
                "source_ref": f"block-{source_unit_id}",
                "section_path": "Abstract",
                "content": content,
            }
        ],
    }


def build_compact_paper_map_prompt(
    payload: Mapping[str, Any],
    *,
    include_output_contract: bool = True,
) -> tuple[str, str]:
    model_payload, _ = _paper_map_model_payload(payload)
    source_labels = [
        str(source.get("label") or "").strip()
        for source in model_payload.get("sources") or ()
        if isinstance(source, Mapping) and str(source.get("label") or "").strip()
    ]
    user_prompt = (
        "TASK\n"
        "Extract only paper-stated research axes for a candidate Objective map. "
        "A relationship is candidate scope, not proven Evidence.\n\n"
        "INPUT\n"
        f"{json.dumps(model_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "DECISION\n"
        "1. Identify whose work is described: current_work or cited background.\n"
        "2. Keep only explicitly changed/compared/modeled factors and explicitly "
        "measured/observed/predicted outcomes.\n"
        "3. Preserve a jointly varied factor set; emit one relationship per specific "
        "outcome. Values, directions, settings, samples, controls, and test details are "
        "not research axes.\n"
        "Do not demote an explicit link between a changed or compared configuration "
        "and an observed outcome to unresolved signals.\n"
        "4. If only one axis is explicit, or an outcome is only a broad family such as "
        "microstructure or mechanical properties, preserve it as unresolved rather than "
        "inventing a measurement.\n"
        "5. Copy every directly supporting Source label. Use uncertainty or empty arrays "
        "instead of completing missing facts.\n\n"
        "HARD RULES\n"
        "Do not merge cited work with current work. Do not infer from titles, headings, "
        "or general knowledge. Do not generate an Objective or reconstruct experiments. "
        f"Allowed Source labels: {json.dumps(source_labels, separators=(',', ':'))}.\n\n"
        f"{_COMPACT_FEW_SHOTS}\n\n"
        "Return the provider-supplied schema object. Set output_saturated=true only "
        "when distinct supported scientific items exceed its limits."
    )
    if include_output_contract:
        user_prompt = f"{user_prompt}\n\n{_COMPACT_OUTPUT_CONTRACT}"
    return _COMPACT_SYSTEM_PROMPT, user_prompt


def build_prompt_variants(payload: Mapping[str, Any]) -> dict[str, PromptVariant]:
    current_system, current_user = build_paper_research_map_prompt(dict(payload))
    schema_json = _response_schema_json()
    current_user_with_schema = (
        f"{current_user}\n\n"
        "Return exactly one JSON object that matches this schema. "
        "Do not include markdown fences or commentary.\n"
        f"JSON schema:\n{schema_json}"
    )
    compact_system, compact_user = build_compact_paper_map_prompt(
        payload,
        include_output_contract=True,
    )
    compact_parse_system, compact_parse_user = build_compact_paper_map_prompt(
        payload,
        include_output_contract=True,
    )
    return {
        "current_json_schema": PromptVariant(
            variant_id="current_json_schema",
            system_prompt=current_system,
            user_prompt=current_user_with_schema,
            request_mode="json_object",
            schema_delivery="message",
        ),
        "current_provider_parse": PromptVariant(
            variant_id="current_provider_parse",
            system_prompt=current_system,
            user_prompt=current_user,
            request_mode="provider_parse",
            schema_delivery="provider_response_format",
        ),
        "compact_json_object": PromptVariant(
            variant_id="compact_json_object",
            system_prompt=compact_system,
            user_prompt=compact_user,
            request_mode="json_object",
            schema_delivery="compact_output_contract",
        ),
        "compact_provider_parse": PromptVariant(
            variant_id="compact_provider_parse",
            system_prompt=compact_parse_system,
            user_prompt=compact_parse_user,
            request_mode="provider_parse",
            schema_delivery="provider_response_format",
        ),
    }


def audit_prompt_variants(
    variants: Mapping[str, PromptVariant],
    *,
    model: str,
) -> dict[str, dict[str, Any]]:
    encoding = _token_encoding(model)
    schema_json = _response_schema_json()
    schema_tokens = len(encoding.encode(schema_json))
    audits: dict[str, dict[str, Any]] = {}
    for variant_id, variant in variants.items():
        messages = _messages(variant)
        serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        provider_schema = variant.request_mode == "provider_parse"
        audits[variant_id] = {
            "request_mode": variant.request_mode,
            "schema_delivery": variant.schema_delivery,
            "system_prompt_chars": len(variant.system_prompt),
            "user_prompt_chars": len(variant.user_prompt),
            "message_chars": len(serialized),
            "message_tokens_estimate": len(encoding.encode(serialized)),
            "provider_schema_chars": len(schema_json) if provider_schema else 0,
            "provider_schema_tokens_estimate": schema_tokens if provider_schema else 0,
        }

    baseline_tokens = audits["current_json_schema"]["message_tokens_estimate"]
    provider_baseline_tokens = audits["current_provider_parse"][
        "message_tokens_estimate"
    ]
    for audit in audits.values():
        message_tokens = audit["message_tokens_estimate"]
        audit["message_token_reduction_vs_current_percent"] = round(
            (baseline_tokens - message_tokens) / baseline_tokens * 100,
            2,
        )
        audit["message_token_reduction_vs_current_provider_parse_percent"] = round(
            (provider_baseline_tokens - message_tokens)
            / provider_baseline_tokens
            * 100,
            2,
        )
    return audits


def evaluate_scenario_output(
    scenario: ProbeScenario,
    parsed: StructuredExperimentalPaperMap,
) -> dict[str, Any]:
    def relationship_factor_labels(relationship: Any) -> tuple[str, ...]:
        return tuple(
            str(assertion.label).strip()
            for assertion in relationship.factor_assertions
            if str(assertion.label).strip()
        )

    allowed_labels = {
        f"S{index}"
        for index, source in enumerate(scenario.payload.get("source_units") or (), 1)
        if isinstance(source, Mapping)
    }
    relationships = [
        (study, relationship)
        for study in parsed.studies
        for relationship in study.relationships
    ]
    signals = list(parsed.unresolved_signals)
    returned_labels = {
        label
        for _, relationship in relationships
        for label in relationship.source_labels
    } | {label for signal in signals for label in signal.source_labels}
    checks: dict[str, bool] = {
        "source_labels_allowed": returned_labels <= allowed_labels,
    }
    if not bool(scenario.expectation.get("allow_output_saturated")):
        checks["not_output_saturated"] = not parsed.output_saturated
    expectation_kind = str(scenario.expectation.get("kind") or "")

    if expectation_kind == "joint_factors":
        expected_factors = _normalized_set(scenario.expectation.get("factor_set") or ())
        expected_outcomes = _normalized_set(scenario.expectation.get("outcomes") or ())
        current_relationships = [
            relationship
            for study, relationship in relationships
            if study.claim_scope == "current_work"
        ]
        returned_outcomes = {
            _normalized_label(relationship.outcome)
            for relationship in current_relationships
        }
        expected_relationships = [
            relationship
            for relationship in current_relationships
            if _normalized_label(relationship.outcome) in expected_outcomes
        ]
        checks["expected_outcomes_present"] = expected_outcomes <= returned_outcomes
        checks["joint_factor_set_preserved"] = bool(expected_relationships) and all(
            _normalized_set(relationship_factor_labels(relationship)) == expected_factors
            for relationship in expected_relationships
        )
    elif expectation_kind == "broad_outcome":
        broad_outcome = _normalized_label(scenario.expectation.get("broad_outcome"))
        relationship_outcomes = {
            _normalized_label(relationship.outcome) for _, relationship in relationships
        }
        unresolved_outcomes = {
            _normalized_label(signal.label)
            for signal in signals
            if signal.signal_type == "outcome"
        }
        checks["broad_outcome_not_promoted"] = (
            broad_outcome not in relationship_outcomes
        )
        checks["broad_outcome_preserved_unresolved"] = (
            broad_outcome in unresolved_outcomes
        )
    elif expectation_kind == "cited_background":
        checks["no_cited_current_work"] = not any(
            study.claim_scope == "current_work" for study, _ in relationships
        ) and not any(signal.claim_scope == "current_work" for signal in signals)
    elif expectation_kind == "no_signal":
        checks["no_invented_scope"] = not relationships and not signals
    elif expectation_kind == "structural":
        pass
    elif expectation_kind == "required_relationships":
        required_relationships = scenario.expectation.get("relationships")
        if not isinstance(required_relationships, list) or not required_relationships:
            checks["required_relationship_expectations_present"] = False
        else:
            for position, required in enumerate(required_relationships, start=1):
                if not isinstance(required, Mapping):
                    checks[f"required_relationship_{position}"] = False
                    continue
                factor_terms = _normalized_set(required.get("factor_contains") or ())
                outcome_terms = _normalized_set(required.get("outcome_contains") or ())
                checks[f"required_relationship_{position}"] = bool(
                    factor_terms
                    and outcome_terms
                    and any(
                        all(
                            term
                            in " ".join(
                                _normalized_label(factor)
                                for factor in relationship_factor_labels(relationship)
                            )
                            for term in factor_terms
                        )
                        and all(
                            term in _normalized_label(relationship.outcome)
                            for term in outcome_terms
                        )
                        for _, relationship in relationships
                    )
                )
        max_studies = scenario.expectation.get("max_studies")
        if max_studies is not None:
            checks["study_count_within_limit"] = (
                isinstance(max_studies, int)
                and not isinstance(max_studies, bool)
                and max_studies >= 0
                and len(parsed.studies) <= max_studies
            )
        forbidden_outcomes = scenario.expectation.get("forbidden_outcome_contains")
        if forbidden_outcomes is not None:
            forbidden_terms = _normalized_set(forbidden_outcomes)
            checks["forbidden_outcomes_absent"] = bool(forbidden_terms) and all(
                not any(
                    term in _normalized_label(relationship.outcome)
                    for term in forbidden_terms
                )
                for _, relationship in relationships
            )
    else:
        checks["known_expectation"] = False

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "studies": len(parsed.studies),
            "relationships": len(relationships),
            "unresolved_signals": len(signals),
        },
    }


def run_live_matrix(
    client: Any,
    *,
    scenarios: tuple[ProbeScenario, ...],
    variant_ids: tuple[str, ...],
    model: str,
    repeat: int,
    temperature: float,
    max_completion_tokens: int | None,
    enable_thinking: bool,
    reasoning_effort: str | None,
    show_response: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    for scenario in scenarios:
        variants = build_prompt_variants(scenario.payload)
        for variant_id in variant_ids:
            variant = variants[variant_id]
            for run in range(1, repeat + 1):
                record, capture = _run_live_case(
                    client,
                    scenario=scenario,
                    variant=variant,
                    model=model,
                    run=run,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                    enable_thinking=enable_thinking,
                    reasoning_effort=reasoning_effort,
                )
                records.append(record)
                captures.append(capture)
                if show_response:
                    print(json.dumps(capture, ensure_ascii=False, indent=2))

    return _summarize_live_records(records), captures


def _run_live_case(
    client: Any,
    *,
    scenario: ProbeScenario,
    variant: PromptVariant,
    model: str,
    run: int,
    temperature: float,
    max_completion_tokens: int | None,
    enable_thinking: bool,
    reasoning_effort: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": _messages(variant),
    }
    if max_completion_tokens is not None:
        request_kwargs["max_completion_tokens"] = max_completion_tokens
    if not enable_thinking:
        request_kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": False}
        }
    if reasoning_effort is not None:
        request_kwargs["reasoning_effort"] = reasoning_effort

    started_at = perf_counter()
    raw_text = ""
    parsed: StructuredExperimentalPaperMap | None = None
    finish_reason: str | None = None
    usage: dict[str, int | None] = {}
    error: Exception | None = None
    try:
        if variant.request_mode == "provider_parse":
            response = client.beta.chat.completions.parse(
                **request_kwargs,
                response_format=StructuredExperimentalPaperMap,
            )
        else:
            response = client.chat.completions.create(
                **request_kwargs,
                response_format={"type": "json_object"},
            )

        choice = response.choices[0] if response.choices else None
        message = choice.message if choice is not None else None
        finish_reason = str(getattr(choice, "finish_reason", "") or "").strip() or None
        usage = _usage_dict(getattr(response, "usage", None))
        raw_text = coerce_message_text(getattr(message, "content", None))
        if variant.request_mode == "provider_parse":
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                raise RuntimeError(
                    "provider structured parse returned no parsed payload"
                )
        else:
            if not raw_text:
                raise RuntimeError("JSON-object request returned no content")
            parsed = StructuredExperimentalPaperMap.model_validate_json(
                extract_json_object(raw_text)
            )
    # Provider compatibility, transport, decoding, and validation failures are all
    # experiment outcomes; one failed cell must not stop the remaining matrix.
    except Exception as exc:  # noqa: BLE001
        error = exc
    elapsed_s = perf_counter() - started_at

    evaluation = evaluate_scenario_output(scenario, parsed) if parsed else None
    record = {
        "scenario_id": scenario.scenario_id,
        "variant_id": variant.variant_id,
        "run": run,
        "request_mode": variant.request_mode,
        "elapsed_s": round(elapsed_s, 6),
        "finish_reason": finish_reason,
        "response_chars": len(raw_text),
        "validated": parsed is not None,
        "scientific_passed": bool(evaluation and evaluation["passed"]),
        "evaluation": evaluation,
        "usage": usage,
        "error_type": type(error).__name__ if error else None,
        "error": str(error)[:1000] if error else None,
    }
    capture = {
        "scenario_id": scenario.scenario_id,
        "variant_id": variant.variant_id,
        "run": run,
        "raw_text": raw_text,
        "parsed": parsed.model_dump(mode="json") if parsed else None,
        "evaluation": evaluation,
        "error_type": record["error_type"],
        "error": record["error"],
    }
    return record, capture


def _summarize_live_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = {}
    for variant_id in sorted({str(record["variant_id"]) for record in records}):
        selected = [record for record in records if record["variant_id"] == variant_id]
        timings = [float(record["elapsed_s"]) for record in selected]
        prompt_tokens = [
            int(record["usage"]["prompt_tokens"])
            for record in selected
            if record["usage"].get("prompt_tokens") is not None
        ]
        completion_tokens = [
            int(record["usage"]["completion_tokens"])
            for record in selected
            if record["usage"].get("completion_tokens") is not None
        ]
        variants[variant_id] = {
            "attempts": len(selected),
            "validated": sum(bool(record["validated"]) for record in selected),
            "scientific_passed": sum(
                bool(record["scientific_passed"]) for record in selected
            ),
            "errors": sum(bool(record["error_type"]) for record in selected),
            "timing": summarize_timings(timings),
            "provider_usage": {
                "reported_attempts": len(prompt_tokens),
                "prompt_tokens_total": sum(prompt_tokens),
                "prompt_tokens_average": (
                    round(sum(prompt_tokens) / len(prompt_tokens), 2)
                    if prompt_tokens
                    else None
                ),
                "completion_tokens_total": sum(completion_tokens),
                "completion_tokens_average": (
                    round(sum(completion_tokens) / len(completion_tokens), 2)
                    if completion_tokens
                    else None
                ),
            },
        }
    return {"records": records, "variants": variants}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and A/B test the current Paper Map schema-bearing prompt against "
            "compact schema-shaped few-shots and provider-native structured parsing."
        )
    )
    parser.add_argument(
        "--execution",
        choices=("offline", "live", "both"),
        default="offline",
        help="Run token audit only, live provider calls only, or both.",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=(
            "current_json_schema",
            "current_provider_parse",
            "compact_json_object",
            "compact_provider_parse",
        ),
        help="Variant to run. Repeat to select multiple; defaults to all variants.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario to run. Repeat to select multiple; defaults to all scenarios.",
    )
    parser.add_argument(
        "--scenario-file",
        type=Path,
        help=(
            "Load real or custom scenarios from JSON instead of the built-in "
            "scientific boundary cases."
        ),
    )
    parser.add_argument("--repeat", type=int, default=1, help="Live calls per case.")
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Allow provider/model thinking. Disabled by default to match Core extraction.",
    )
    parser.add_argument("--show-prompt", action="store_true")
    parser.add_argument("--show-response", action="store_true")
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--response-output", type=Path)
    add_runtime_arguments(
        parser,
        default_temperature=0.0,
        include_max_completion_tokens=True,
        default_max_completion_tokens=2048,
    )
    parser.add_argument(
        "--reasoning-effort",
        help=(
            "Optional provider reasoning effort. Precedence is CLI > env > env-file."
        ),
    )
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be greater than 0")
    return args


def main() -> int:
    args = parse_args()
    if args.execution == "offline" and not args.api_key:
        args.api_key = "offline-not-used"
    runtime = resolve_runtime(args)
    available_scenarios = (
        load_scenarios(args.scenario_file)
        if args.scenario_file is not None
        else default_scenarios()
    )
    scenario_ids = set(args.scenario or ())
    available_scenario_ids = {scenario.scenario_id for scenario in available_scenarios}
    unknown_scenario_ids = sorted(scenario_ids - available_scenario_ids)
    if unknown_scenario_ids:
        raise ValueError(f"unknown scenario ids: {unknown_scenario_ids}")
    scenarios = tuple(
        scenario
        for scenario in available_scenarios
        if not scenario_ids or scenario.scenario_id in scenario_ids
    )
    variant_ids = tuple(
        dict.fromkeys(
            args.variant
            or (
                "current_json_schema",
                "current_provider_parse",
                "compact_json_object",
                "compact_provider_parse",
            )
        )
    )

    offline: dict[str, Any] | None = None
    if args.execution in {"offline", "both"}:
        scenario_audits: dict[str, Any] = {}
        for scenario in scenarios:
            variants = build_prompt_variants(scenario.payload)
            all_audits = audit_prompt_variants(
                variants,
                model=runtime.model,
            )
            scenario_audits[scenario.scenario_id] = {
                variant_id: all_audits[variant_id] for variant_id in variant_ids
            }
        offline = {"scenarios": scenario_audits}

    if args.show_prompt:
        for scenario in scenarios:
            variants = build_prompt_variants(scenario.payload)
            for variant_id in variant_ids:
                variant = variants[variant_id]
                print(f"SCENARIO={scenario.scenario_id} VARIANT={variant_id}")
                print("SYSTEM_PROMPT:")
                print(variant.system_prompt)
                print("USER_PROMPT:")
                print(variant.user_prompt)

    live: dict[str, Any] | None = None
    captures: list[dict[str, Any]] = []
    if args.execution in {"live", "both"}:
        client = build_openai_client(runtime)
        live, captures = run_live_matrix(
            client,
            scenarios=scenarios,
            variant_ids=variant_ids,
            model=runtime.model,
            repeat=args.repeat,
            temperature=runtime.temperature,
            max_completion_tokens=runtime.max_completion_tokens,
            enable_thinking=args.enable_thinking,
            reasoning_effort=runtime.reasoning_effort,
            show_response=args.show_response,
        )

    summary = {
        "script": "paper_map_prompt_probe.py",
        "execution": args.execution,
        "backend_root": str(runtime.backend_root),
        "env_file": str(runtime.env_file) if runtime.env_file else None,
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "temperature": runtime.temperature,
            "max_completion_tokens": runtime.max_completion_tokens,
            "timeout_s": runtime.timeout_s,
            "thinking_enabled": args.enable_thinking,
            "reasoning_effort": runtime.reasoning_effort,
        },
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "scenario_file": (
            str(args.scenario_file.expanduser().resolve())
            if args.scenario_file
            else None
        ),
        "variant_ids": list(variant_ids),
        "offline": offline,
        "live": live,
        "response_output": (
            str(args.response_output.expanduser().resolve())
            if args.response_output
            else None
        ),
    }
    write_json_output(
        args.response_output,
        {"script": "paper_map_prompt_probe.py", "captures": captures},
    )
    write_json_output(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if live is not None and any(
        record["error_type"] or not record["scientific_passed"]
        for record in live["records"]
    ):
        return 1
    return 0


def _messages(variant: PromptVariant) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": variant.system_prompt},
        {"role": "user", "content": variant.user_prompt},
    ]


def _response_schema_json() -> str:
    return json.dumps(
        StructuredExperimentalPaperMap.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _token_encoding(model: str) -> Any:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalized_set(values: Any) -> set[str]:
    return {_normalized_label(value) for value in values if _normalized_label(value)}


def _usage_dict(usage: Any) -> dict[str, int | None]:
    return {
        "prompt_tokens": _optional_int(getattr(usage, "prompt_tokens", None)),
        "completion_tokens": _optional_int(getattr(usage, "completion_tokens", None)),
        "total_tokens": _optional_int(getattr(usage, "total_tokens", None)),
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.core.objectives import (
    objective_analysis_service as experiment_analysis_service,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentExtractionResult,
    PaperExperimentSourceBundle,
)
from application.core.objectives.analysis.paper_experiment_reuse import (
    reusable_paper_experiments,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import PreparedDocumentInput
from domain.core.research_objective import normalize_objective_terms
from tests.unit.application.test_experiment_analysis_writer import (
    _analysis,
    _draft_output,
    _objective,
    _physical_split_experiment,
    _writer,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _bundle(output):
    return PaperExperimentSourceBundle(
        document_id=output.output.document_id,
        source_fingerprint=output.output.source_fingerprint,
        source_catalog=output.output.source_labels,
        prompt_sources=tuple(
            {"source_label": label} for label in output.output.source_labels
        ),
    )


async def test_saved_paper_facts_feed_multiple_objectives_and_cross_paper_comparison(
    monkeypatch,
):
    import application.core.objectives.objective_analysis_service as service_module

    writer, repository, graphs = _writer()
    outputs = (
        _physical_split_experiment("paper-a", distinct_boundary=True),
        _draft_output("paper-b"),
    )
    outputs = tuple(
        replace(
            output,
            output=replace(
                output.output,
                source_labels={
                    label: {
                        **source,
                        "source_kind": (
                            "text_window"
                            if source["source_kind"] == "section"
                            else source["source_kind"]
                        ),
                    }
                    for label, source in output.output.source_labels.items()
                },
            ),
        )
        for output in outputs
    )
    saved = await writer.write_paper_experiment_revisions(
        experiment_outputs=outputs,
        db=object(),
        created_by="researcher",
    )
    assert len(saved.revisions) == 3
    assert saved.selections == saved.findings == ()
    assert graphs.graphs == []
    fixed_revisions = tuple(item.revision for item in saved.revisions)
    bundles = {output.output.document_id: _bundle(output) for output in outputs}
    analysis = replace(
        _analysis(),
        document_inputs=tuple(
            PreparedDocumentInput(
                document_id=key, preparation_fingerprint=value.source_fingerprint
            )
            for key, value in bundles.items()
        ),
    )
    objective = replace(_objective(), active_analysis_version=analysis.analysis_version)
    objective_repository = SimpleNamespace(
        read_objective=AsyncMock(return_value=objective)
    )
    experiment_analysis_service.collection_service = object()
    experiment_analysis_service.PaperMapRepo = object()
    experiment_analysis_service.ObjectiveRepo = objective_repository
    experiment_analysis_service.PaperExperimentRepo = repository
    service = experiment_analysis_service
    inputs = {
        "documents": tuple(SimpleNamespace(document_id=key) for key in bundles),
        "paper_maps": tuple(SimpleNamespace(document_id=key) for key in bundles),
        **{
            name: {key: () for key in bundles}
            for name in (
                "blocks_by_document_id",
                "tables_by_document_id",
                "figures_by_document_id",
                "table_cells_by_document_id",
                "profiles_by_document_id",
                "document_trees_by_document_id",
            )
        },
    }
    monkeypatch.setattr(
        service, "_build_objective_analysis_inputs", AsyncMock(return_value=inputs)
    )

    def screen(**kwargs):
        return tuple(
            PaperAnalysisFrame(
                objective_id=str(objective.objective_id or "").strip(),
                document_id=str(item.document_id or "").strip(),
                relevance="high",
                paper_role="primary_experiment",
                screening_note=None,
                material_match=normalize_objective_terms(["316L"]),
                changed_variables=normalize_objective_terms(["preheat"]),
                measured_property_scope=normalize_objective_terms(["elongation"]),
                test_environment_scope=(),
                relevant_sections=(),
                relevant_text_source_refs=(),
                relevant_tables=(),
                excluded_tables=(),
            )
            for item in kwargs["documents"]
        )

    def route(**kwargs):
        document_id = kwargs["objective_paper_frames"][0].document_id
        return tuple(
            SimpleNamespace(**source, extractable=True)
            for source in bundles[document_id].source_catalog.values()
        )

    monkeypatch.setattr(service_module, "screen_sources", screen)
    monkeypatch.setattr(service_module, "route_sources", route)
    monkeypatch.setattr(
        service_module,
        "build_bundle_from_routes",
        lambda **kwargs: bundles[kwargs["document_id"]],
    )
    artifacts = await service.generate_experiment_analysis_artifacts(
        "collection-1", analysis,
        response_client=SimpleNamespace(model="test-model"),
        paper_map_extractor=service_module.PaperResearchMapExtractor(
            SimpleNamespace(model="test-model")
        ),
        source_screener=service_module.ObjectiveSourceScreener(
            SimpleNamespace(model="test-model")
        ),
        paper_experiment_extractor=service_module.PaperExperimentExtractor(
            SimpleNamespace(model="test-model")
        ),
    )
    assert artifacts.experiment_outputs == ()
    assert len(artifacts.reused_revisions) == 3
    assert set(artifacts.extraction_statuses.values()) == {"reused"}
    assert all(
        item.extracted_source_count == item.routed_source_count
        for item in artifacts.contributions
    )
    assert all(item.uninspected_source_count == 0 for item in artifacts.contributions)
    first = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=objective,
        analysis=analysis,
        experiment_outputs=(),
        reused_revisions=artifacts.reused_revisions,
        db=object(),
    )
    assert len(first.selections) == 3
    assert first.groups
    assert first.findings
    experiment_documents = {
        item.revision.experiment_id: item.revision.document_id
        for item in first.revisions
    }
    selection_documents = {
        item.selection_id: experiment_documents[item.experiment_id]
        for item in first.selections
    }
    assert any(
        len({selection_documents[member.selection_id] for member in group.members}) == 2
        for group in first.groups
    )
    other_objective = replace(objective, objective_id="objective-2")
    second = await writer.write_experiment_analysis(
        collection_id="collection-1",
        objective=other_objective,
        analysis=replace(analysis, objective_id="objective-2"),
        experiment_outputs=(),
        reused_revisions=artifacts.reused_revisions,
        db=object(),
    )
    assert {item.experiment_id for item in first.selections} == {
        item.experiment_id for item in second.selections
    }
    assert all(item.objective_id == "objective-2" for item in second.selections)
    await writer.write_paper_experiment_revisions(
        experiment_outputs=(
            _draft_output("paper-b", source_fingerprint="updated-source"),
        ),
        db=object(),
    )
    assert tuple(item.revision for item in first.revisions) == fixed_revisions
    assert all(item.experiment_version == 1 for item in first.selections)


@pytest.mark.parametrize(
    "change",
    [
        "fingerprint",
        "quote",
        "missing_source",
        "omitted_source",
        "outcome",
        "variable",
        "material",
        "constraint",
        "archived",
        "boundary",
        "conflict",
    ],
)
async def test_insufficient_or_stale_facts_require_extraction(change):
    writer, _, _ = _writer()
    output = _draft_output("paper-a")
    saved = await writer.write_paper_experiment_revisions(
        experiment_outputs=(output,), db=object()
    )
    candidates = saved.revisions
    bundle = _bundle(output)
    objective = _objective()
    assert reusable_paper_experiments(candidates, objective=objective, bundle=bundle)
    if change == "fingerprint":
        bundle = replace(bundle, source_fingerprint="changed")
    elif change == "quote":
        bundle = replace(
            bundle,
            source_catalog={
                key: {**source, "quote": "changed"}
                for key, source in bundle.source_catalog.items()
            },
        )
    elif change == "missing_source":
        bundle = replace(
            bundle,
            source_catalog={
                **bundle.source_catalog,
                "extra": {"source_kind": "block", "source_ref": "new", "quote": "new"},
            },
            prompt_sources=(*bundle.prompt_sources, {"source_label": "extra"}),
        )
    elif change == "omitted_source":
        bundle = replace(bundle, omitted_source_refs=("unread",))
    elif change in {"outcome", "variable", "material", "constraint"}:
        field = {
            "outcome": "outcomes",
            "variable": "variables",
            "material": "material_scope",
            "constraint": "constraints",
        }[change]
        objective = replace(objective, **{field: ("unreported requirement",)})
    elif change == "archived":
        candidates = (replace(candidates[0], archived_at=datetime.now(timezone.utc)),)
    else:
        revision = replace(
            candidates[0].revision,
            **(
                {"identity_status": "unknown"}
                if change == "boundary"
                else {"unresolved_issues": ({"description": "conflicting reports"},)}
            ),
        )
        candidates = (replace(candidates[0], revision=revision),)
    assert (
        reusable_paper_experiments(candidates, objective=objective, bundle=bundle) == ()
    )

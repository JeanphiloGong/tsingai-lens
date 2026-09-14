from pathlib import Path

import pytest

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.objectives.analysis.finding_synthesis import (
    StructuredFindingSynthesis,
)
from application.core.objectives.analysis.source_extraction import (
    DirectEvidenceExtractionModelOutput,
    DirectEvidenceExtractionsModelOutput,
    DirectEvidenceResultModelOutput,
    EvidenceAttributeModelOutput,
    EvidenceComparisonModelOutput,
    EvidenceContextModelOutput,
    EvidenceExtractionModelOutput,
    EvidenceExtractionsModelOutput,
    EvidenceResultModelOutput,
    EvidenceVariableModelOutput,
    ObjectiveSourceExtractor,
    RequestedContextFactModelOutput,
    RequestedContextFactsModelOutput,
)
from application.core.objectives.analysis.source_screening import (
    PaperFrameBatchModelOutput,
    PaperFrameBatchResult,
)
from application.core.objectives.discovery.axis_equivalence import (
    StructuredAxisCanonicalizationPlan,
)
from application.core.objectives.discovery import signal_reconciliation
from application.core.objectives.discovery.paper_understanding import paper_map_outputs
from application.core.objectives.discovery.signal_reconciliation import (
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.paper_facts.extraction import (
    PaperFactsExtractor,
    TableMatrixRepairItemModelOutput,
    TableMatrixRepairModelOutput,
)


def test_model_clients_are_owned_by_their_domains() -> None:
    assert DocumentProfileExtractor.__module__ == (
        "application.core.document_profiles.extraction"
    )
    assert PaperFactsExtractor.__module__ == "application.core.paper_facts.extraction"
    assert StructuredResponseClient.__module__ == (
        "application.core.objectives.llm.structured_response"
    )


def test_objective_judgments_own_their_response_contracts() -> None:
    expected_owners = {
        StructuredPaperResearchMap: "application.core.objectives.discovery.paper_understanding.paper_map_results",
        StructuredPaperSignalReconciliation: (
            "application.core.objectives.discovery.signal_reconciliation"
        ),
        StructuredAxisCanonicalizationPlan: (
            "application.core.objectives.discovery.axis_equivalence"
        ),
        PaperFrameBatchModelOutput: (
            "application.core.objectives.analysis.source_screening"
        ),
        PaperFrameBatchResult: (
            "application.core.objectives.analysis.source_screening"
        ),
        StructuredFindingSynthesis: (
            "application.core.objectives.analysis.finding_synthesis"
        ),
    }

    assert all(
        response_model.__module__ == owner
        for response_model, owner in expected_owners.items()
    )


@pytest.mark.parametrize(
    ("module", "model_name"),
    [
        (paper_map_outputs, "ExperimentalPaperMapModelOutput"),
        (paper_map_outputs, "PaperSourceSignalScreenModelOutput"),
        (paper_map_outputs, "ReviewPaperMapModelOutput"),
        (signal_reconciliation, "PaperSignalReconciliationModelOutput"),
    ],
)
def test_discovery_model_outputs_keep_nested_output_names(module, model_name):
    output_model = getattr(module, model_name)
    schema = output_model.model_json_schema()

    assert output_model.__module__ == module.__name__
    assert schema["title"] == model_name
    assert all(name.endswith("ModelOutput") for name in schema.get("$defs", {}))


@pytest.mark.parametrize(
    "output_model",
    [
        EvidenceAttributeModelOutput,
        EvidenceVariableModelOutput,
        EvidenceComparisonModelOutput,
        EvidenceResultModelOutput,
        EvidenceContextModelOutput,
        EvidenceExtractionModelOutput,
        EvidenceExtractionsModelOutput,
        DirectEvidenceResultModelOutput,
        DirectEvidenceExtractionModelOutput,
        DirectEvidenceExtractionsModelOutput,
        RequestedContextFactModelOutput,
        RequestedContextFactsModelOutput,
    ],
)
def test_source_extraction_owns_its_model_outputs(output_model: type) -> None:
    assert output_model.__module__ == ObjectiveSourceExtractor.__module__


def test_paper_facts_retains_only_the_active_table_repair_contract() -> None:
    assert TableMatrixRepairModelOutput.__module__ == PaperFactsExtractor.__module__
    assert TableMatrixRepairItemModelOutput.__module__ == PaperFactsExtractor.__module__
    assert not hasattr(PaperFactsExtractor, "extract_text_window_mentions")
    assert not hasattr(PaperFactsExtractor, "extract_table_batch_mentions")


def test_shared_structured_extraction_package_only_owns_json_support() -> None:
    core_path = Path(__file__).parents[3] / "application" / "core"
    shared_path = core_path / "structured_extraction"

    assert {path.name for path in shared_path.glob("*.py")} == {
        "__init__.py",
        "json_support.py",
    }
    assert "openai" not in (shared_path / "json_support.py").read_text().lower()

    for domain in ("document_profiles", "paper_facts"):
        files = {path.name for path in (core_path / domain).glob("*.py")}
        assert "extraction.py" in files
        assert not {"prompts.py", "schemas.py"} & files

    objectives_path = core_path / "objectives"
    assert not {
        "extraction.py",
        "prompts.py",
        "schemas.py",
    } & {path.name for path in objectives_path.glob("*.py")}
    assert {path.name for path in (objectives_path / "llm").glob("*.py")} == {
        "__init__.py",
        "structured_response.py",
    }

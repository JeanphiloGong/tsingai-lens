from pathlib import Path

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.objectives.analysis.evidence_routing import (
    StructuredEvidenceSelections,
)
from application.core.objectives.analysis.finding_synthesis import (
    StructuredFindingSynthesis,
)
from application.core.objectives.analysis.source_extraction import (
    StructuredEvidenceExtractions,
)
from application.core.objectives.analysis.source_screening import (
    StructuredPaperFrameBatch,
)
from application.core.objectives.discovery.axis_equivalence import (
    StructuredAxisCanonicalizationPlan,
)
from application.core.objectives.discovery.signal_reconciliation import (
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.study_window import StructuredPaperSkim
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.paper_facts.extraction import PaperFactsExtractor


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
        StructuredPaperSkim: "application.core.objectives.discovery.study_window",
        StructuredPaperSignalReconciliation: (
            "application.core.objectives.discovery.signal_reconciliation"
        ),
        StructuredAxisCanonicalizationPlan: (
            "application.core.objectives.discovery.axis_equivalence"
        ),
        StructuredPaperFrameBatch: (
            "application.core.objectives.analysis.source_screening"
        ),
        StructuredEvidenceSelections: (
            "application.core.objectives.analysis.evidence_routing"
        ),
        StructuredEvidenceExtractions: (
            "application.core.objectives.analysis.source_extraction"
        ),
        StructuredFindingSynthesis: (
            "application.core.objectives.analysis.finding_synthesis"
        ),
    }

    assert all(
        response_model.__module__ == owner
        for response_model, owner in expected_owners.items()
    )


def test_shared_structured_extraction_package_only_owns_json_support() -> None:
    core_path = Path(__file__).parents[3] / "application" / "core"
    shared_path = core_path / "structured_extraction"

    assert {path.name for path in shared_path.glob("*.py")} == {
        "__init__.py",
        "json_support.py",
    }
    assert "openai" not in (shared_path / "json_support.py").read_text().lower()

    for domain in ("document_profiles", "paper_facts"):
        assert {
            "extraction.py",
            "prompts.py",
            "schemas.py",
        } <= {path.name for path in (core_path / domain).glob("*.py")}

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

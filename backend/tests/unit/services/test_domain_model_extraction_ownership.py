from pathlib import Path

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.objectives.extraction import ObjectiveExtractor
from application.core.paper_facts.extraction import PaperFactsExtractor


def test_model_extraction_entrypoints_are_owned_by_their_domains() -> None:
    assert DocumentProfileExtractor.__module__ == (
        "application.core.document_profiles.extraction"
    )
    assert PaperFactsExtractor.__module__ == "application.core.paper_facts.extraction"
    assert ObjectiveExtractor.__module__ == "application.core.objectives.extraction"


def test_shared_structured_extraction_package_only_owns_json_support() -> None:
    core_path = Path(__file__).parents[3] / "application" / "core"
    shared_path = core_path / "structured_extraction"

    assert {path.name for path in shared_path.glob("*.py")} == {
        "__init__.py",
        "json_support.py",
    }
    assert "openai" not in (shared_path / "json_support.py").read_text().lower()

    for domain in ("document_profiles", "paper_facts", "objectives"):
        assert {
            "extraction.py",
            "prompts.py",
            "schemas.py",
        } <= {path.name for path in (core_path / domain).glob("*.py")}

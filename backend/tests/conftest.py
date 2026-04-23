from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _patch_core_llm_extractor(monkeypatch):
    from application.core import comparison_service
    from application.core.semantic_build import (
        document_profile_service,
        paper_facts_service,
    )
    from tests.support.fake_core_llm_extractor import FakeCoreLLMStructuredExtractor

    fake = FakeCoreLLMStructuredExtractor()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_core_llm_structured_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        paper_facts_service,
        "build_default_core_llm_structured_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(document_profile_service, "core_semantic_rebuild_required", lambda _base_dir: False)
    monkeypatch.setattr(paper_facts_service, "core_semantic_rebuild_required", lambda _base_dir: False)
    monkeypatch.setattr(comparison_service, "core_semantic_rebuild_required", lambda _base_dir: False)

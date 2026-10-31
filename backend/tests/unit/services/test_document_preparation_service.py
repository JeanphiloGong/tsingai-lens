import pytest
from application.core.document_profiles.extraction import (
    DOCUMENT_PROFILE_PROMPT_VERSION,
)
from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from application.source.document_preparation_service import (
    DOCUMENT_ANALYSIS_VERSION,
    profile_fingerprint,
    source_fingerprint,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_document_preparation_fingerprints_invalidate_only_dependent_stages():
    source_v1 = source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
    )
    profile_v1 = profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v1",
    )
    assert source_v1 == source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
    )
    assert profile_v1 == profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v1",
    )
    profile_v2 = profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v2",
    )
    assert profile_v2 != profile_v1

    source_v2 = source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v2",
    )
    assert source_v2 != source_v1
    assert profile_v1 != profile_fingerprint(
        source_fingerprint=source_v2,
        profile_version="document-profile.v1",
    )


def test_document_preparation_version_covers_only_profile_triage() -> None:
    assert DOCUMENT_ANALYSIS_VERSION == DOCUMENT_PROFILE_PROMPT_VERSION

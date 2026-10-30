from __future__ import annotations

import asyncio

import pytest
from application.core.document_profiles import service as document_profile_service
from application.core.document_profiles.extraction import (
    DocumentProfileExtractionError,
    DocumentProfileModelOutput,
)
from application.core.objectives import objective_input_service
from application.core.objectives.objective_input_service import (
    ResearchObjectivesNotReadyError,
)
from application.source import collection_service, document_preparation_service
from application.source.document_preparation_service import (
    DOCUMENT_ANALYSIS_VERSION,
    SOURCE_PARSER_VERSION,
)
from controllers.source import pipeline_run_routes
from infra.source.build_source_artifacts import build_source_artifacts
from tests.integration.test_app_layer_api import _create_collection, _upload

pytest_plugins = ("tests.integration.test_app_layer_api",)


def test_upload_classification_retry_content_and_research_readiness(
    app_client, monkeypatch
):
    """Use the real text parser and HTTP routes, failing only the model boundary."""
    parse_calls = []

    async def parse_sources(**kwargs):
        parse_calls.append(kwargs["input_documents"]["id"].tolist())
        return await build_source_artifacts(**kwargs)

    class Classifier:
        calls = 0

        def extract_document_profile(self, payload):
            self.calls += 1
            if self.calls == 1:
                raise DocumentProfileExtractionError(
                    "controlled transient model failure"
                )
            return DocumentProfileModelOutput(
                doc_type="experimental", profile_warnings=[], confidence=0.9
            )

        def consume_last_trace(self):
            return None

    classifier = Classifier()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_document_profile_extractor",
        lambda: classifier,
    )
    document_preparation_service._source_artifact_builder = parse_sources
    monkeypatch.setattr(
        pipeline_run_routes,
        "document_preparation_service",
        document_preparation_service,
    )
    preparation = document_preparation_service
    collection_id = _create_collection(app_client, "LPBF classification recovery")
    text = b"Laser power and Ti-6Al-4V porosity\n\nMethods\nLaser power was varied from 100 W to 150 W.\n\nResults\nPorosity decreased from 2.0% to 0.5%."
    uploaded = _upload(app_client, collection_id, "laser-porosity.txt", text)
    document_id = uploaded["document_id"]
    document_path = f"/api/v1/collections/{collection_id}/documents/{document_id}"

    async def finish_workers():
        await asyncio.gather(*tuple(preparation._active_workers))

    first = app_client.post(f"{document_path}/preparation")
    assert first.status_code == 200
    app_client.portal.call(finish_workers)
    first_run = app_client.get(f"/api/v1/pipeline-runs/{first.json()['data']['run_id']}").json()["data"]
    assert first_run["status"] == "partial_success"
    assert first_run["warnings"]
    profile = app_client.get(f"{document_path}/profile").json()["data"]
    assert profile["profile_status"] == "extraction_failed"
    content = app_client.get(f"{document_path}/content")
    assert content.status_code == 200
    assert "2.0%" in content.json()["data"]["content_text"]
    source_output_dir = (
        collection_service.workspace.get_paths(collection_id).output_dir
        / "documents"
        / document_id
    )
    assert (source_output_dir / "documents.json").is_file()
    assert not (source_output_dir / "cache").exists()
    input_service = objective_input_service
    with pytest.raises(ResearchObjectivesNotReadyError):
        app_client.portal.call(
            input_service.resolve_prepared_document_inputs,
            collection_id,
            (document_id,),
        )

    retry = app_client.post(f"{document_path}/preparation")
    assert retry.status_code == 200
    assert retry.json()["data"]["run_id"] != first.json()["data"]["run_id"]
    app_client.portal.call(finish_workers)
    retry_run = app_client.get(f"/api/v1/pipeline-runs/{retry.json()['data']['run_id']}").json()["data"]
    assert retry_run["status"] == "completed"
    assert retry_run["warnings"] == []
    current_profile = app_client.get(f"{document_path}/profile").json()["data"]
    assert current_profile["doc_type"] == "experimental"
    stored_profile = app_client.portal.call(
        document_profile_service.DocumentProfileRepo.read,
        collection_id,
        document_id,
    )
    stored_source = app_client.portal.call(
        document_profile_service.SourceArtifactRepo.read_document,
        collection_id,
        document_id,
    )
    assert (
        app_client.get(f"{document_path}/content").json()["data"]["content_text"]
        == content.json()["data"]["content_text"]
    )
    inputs = app_client.portal.call(
        input_service.resolve_prepared_document_inputs, collection_id, (document_id,)
    )
    assert inputs[0].document_id == document_id
    assert inputs[0].preparation_fingerprint
    assert stored_source.metadata["parser_version"] == SOURCE_PARSER_VERSION
    assert (
        stored_source.metadata["source_fingerprint"]
        == stored_profile.source_fingerprint
    )
    assert stored_profile.profile_version == DOCUMENT_ANALYSIS_VERSION
    assert stored_profile.profile_fingerprint == inputs[0].preparation_fingerprint
    assert stored_profile.generated_at
    assert len(parse_calls) == 1
    assert classifier.calls == 2
    assert (
        app_client.post(f"{document_path}/preparation").json()["data"]["run_id"]
        == retry.json()["data"]["run_id"]
    )

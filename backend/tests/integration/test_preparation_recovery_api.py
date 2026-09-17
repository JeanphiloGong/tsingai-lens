from __future__ import annotations

import asyncio

import pytest

from application.core.document_profiles.extraction import DocumentProfileExtractionError
from application.core.document_profiles.extraction import DocumentProfileModelOutput
from application.core.objectives.objective_input_service import (
    ResearchObjectivesNotReadyError,
)
from application.source.document_preparation_service import DocumentPreparationService
from infra.source.runtime.build_source_artifacts import build_source_artifacts
from tests.integration.test_app_layer_api import _create_collection, _upload


pytest_plugins = ("tests.integration.test_app_layer_api",)


def test_upload_classification_retry_content_and_research_readiness(app_client):
    """Use the real text parser and HTTP routes, failing only the model boundary."""
    state = app_client.app.state
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
    state.document_profile_service._document_profile_extractor = classifier
    preparation = DocumentPreparationService(
        collection_service=state.collection_service,
        pipeline_run_service=state.pipeline_run_service,
        source_artifact_repository=state.document_profile_service.source_artifact_repository,
        document_profile_service=state.document_profile_service,
        source_artifact_builder=parse_sources,
    )
    state.document_preparation_service = preparation
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
    first_run = app_client.get(f"/api/v1/pipeline-runs/{first.json()['run_id']}").json()
    assert first_run["status"] == "partial_success"
    assert first_run["warnings"]
    profile = app_client.get(f"{document_path}/profile").json()
    assert profile["profile_status"] == "extraction_failed"
    content = app_client.get(f"{document_path}/content")
    assert content.status_code == 200
    assert "2.0%" in content.json()["content_text"]
    input_service = state.objective_discovery_service.objective_input_service
    with pytest.raises(ResearchObjectivesNotReadyError):
        app_client.portal.call(
            input_service.resolve_prepared_document_inputs,
            collection_id,
            (document_id,),
        )

    retry = app_client.post(f"{document_path}/preparation")
    assert retry.status_code == 200
    assert retry.json()["run_id"] != first.json()["run_id"]
    app_client.portal.call(finish_workers)
    retry_run = app_client.get(f"/api/v1/pipeline-runs/{retry.json()['run_id']}").json()
    assert retry_run["status"] == "completed"
    assert retry_run["warnings"] == []
    assert (
        app_client.get(f"{document_path}/profile").json()["doc_type"] == "experimental"
    )
    assert (
        app_client.get(f"{document_path}/content").json()["content_text"]
        == content.json()["content_text"]
    )
    inputs = app_client.portal.call(
        input_service.resolve_prepared_document_inputs, collection_id, (document_id,)
    )
    assert inputs[0].document_id == document_id
    assert inputs[0].preparation_fingerprint
    assert len(parse_calls) == 1
    assert classifier.calls == 2
    assert (
        app_client.post(f"{document_path}/preparation").json()["run_id"]
        == retry.json()["run_id"]
    )

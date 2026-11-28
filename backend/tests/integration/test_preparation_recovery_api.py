from __future__ import annotations

from infra.persistence.file import object_store as store_module


import pytest
from document.application import profile_service as document_profile_service
from document.application.profile_extraction import (
    DocumentProfileExtractionError,
    DocumentProfileModelOutput,
)
from application.core.objectives import objective_input_service
from application.core.objectives.objective_input_service import (
    ResearchObjectivesNotReadyError,
)
from application.source import workspace_service
from pipeline.application.document_preparation_runner import (
    DOCUMENT_ANALYSIS_VERSION,
    SOURCE_PARSER_VERSION,
)
from infra.source.build_source_artifacts import build_source_artifacts
from tests.integration.test_app_layer_api import _create_workspace, _upload

pytest_plugins = ("tests.integration.test_app_layer_api",)


def test_upload_classification_retry_content_and_research_readiness(
    app_client,
    monkeypatch,
    *,
    workspace_files,
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
                doc_type="experimental", description="Experimental materials study."
            )

        def consume_last_trace(self):
            return None

    classifier = Classifier()
    from pipeline.application import document_preparation_runner as preparation
    from pipeline.controllers import pipeline_run_routes
    from repositories.model_connection_repository import ModelConnectionRepo
    from repositories.pipeline_run_repository import PipelineRunRepo
    from datetime import timedelta

    monkeypatch.setattr(
        pipeline_run_routes,
        "accept_document_preparation",
        preparation.accept_document_preparation,
    )

    async def assign_model():
        model = await ModelConnectionRepo.create("manager", "profile-recovery", {
            "display_name": "Profile recovery",
            "model": "profile-recovery",
            "base_url": "http://127.0.0.1:1/v1",
        }, actor_display_name=None)
        await ModelConnectionRepo.update(
            "manager", model.connection_id, model.version, {"enabled": True},
            actor_display_name=None,
        )
        await ModelConnectionRepo.assign("document_profile", model.connection_id, 0, "manager")

    app_client.portal.call(assign_model)
    workspace_id = _create_workspace(app_client, "LPBF classification recovery")
    text = b"Laser power and Ti-6Al-4V porosity\n\nMethods\nLaser power was varied from 100 W to 150 W.\n\nResults\nPorosity decreased from 2.0% to 0.5%."
    uploaded = _upload(app_client, workspace_id, "laser-porosity.txt", text)
    document_id = uploaded["document_id"]
    document_path = f"/api/v1/workspaces/{workspace_id}/documents/{document_id}"

    async def finish_workers():
        job = await PipelineRunRepo.claim_next_document_preparation_job(
            worker_id="test-worker", lease_duration=timedelta(seconds=300)
        )
        assert job is not None
        await preparation.execute_document_preparation_job(
            job,
            workspace=workspace_files,
            object_store=store_module.Store,
            source_artifact_builder=parse_sources,
            profile_extractor=classifier,
        )

    first = app_client.post(f"{document_path}/preparation")
    assert first.status_code == 200
    app_client.portal.call(finish_workers)
    first_run = app_client.get(
        f"/api/v1/pipeline-runs/{first.json()['data']['run_id']}"
    ).json()["data"]
    assert first_run["status"] == "partial_success"
    assert first_run["warnings"]
    profile = app_client.get(f"{document_path}/profile")
    assert profile.json()["data"]["code"] == "document_profiles_not_ready"
    assert classifier.calls == 1
    content = app_client.get(f"{document_path}/content")
    assert content.status_code == 200
    assert "2.0%" in content.json()["data"]["content_text"]
    source_output_dir = (
        workspace_files.get_paths(workspace_id).output_dir
        / "documents"
        / document_id
    )
    assert not source_output_dir.exists()
    assert not tuple(
        workspace_files.get_paths(workspace_id).output_dir.glob("preparation/*")
    )
    assert not (source_output_dir / "cache").exists()
    input_service = objective_input_service
    with pytest.raises(ResearchObjectivesNotReadyError):
        app_client.portal.call(
            input_service.resolve_prepared_document_inputs,
            workspace_id,
            (document_id,),
        )

    retry = app_client.post(f"{document_path}/preparation")
    assert retry.status_code == 200
    assert retry.json()["data"]["run_id"] != first.json()["data"]["run_id"]
    app_client.portal.call(finish_workers)
    retry_run = app_client.get(
        f"/api/v1/pipeline-runs/{retry.json()['data']['run_id']}"
    ).json()["data"]
    assert retry_run["status"] == "completed"
    assert retry_run["warnings"] == []
    current_profile = app_client.get(f"{document_path}/profile").json()["data"]
    assert current_profile["doc_type"] == "experimental"
    stored_profile = app_client.portal.call(
        document_profile_service.ProfileRepo.read,
        workspace_id,
        document_id,
    )
    stored_source = app_client.portal.call(
        document_profile_service.SourceRepo.read_document,
        workspace_id,
        document_id,
    )
    assert (
        app_client.get(f"{document_path}/content").json()["data"]["content_text"]
        == content.json()["data"]["content_text"]
    )
    inputs = app_client.portal.call(
        input_service.resolve_prepared_document_inputs, workspace_id, (document_id,)
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

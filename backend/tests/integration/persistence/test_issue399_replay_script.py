"""Verify the CLI's current lifecycle wiring with synthetic Sources and an offline model."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.chat import ModelTurn
from domain.source import SourceBlock, SourceDocument
from repositories.source_artifact_repository import SourceArtifactRepo
from scripts.evaluation.research_agent import run_inconel_four_turns as replay
from tests.support.postgres import seed_collection
from tests.unit.application.test_research_agent_runner import _Model
from tests.support.chat_model_connections import scripted_chat_runner

pytestmark = pytest.mark.anyio


async def test_freeze_and_replay_use_current_lifespan_without_scientific_writes(
    postgres_session_factory,
    postgres_sync_engine,
    tmp_path,
    monkeypatch,
    scripted_chat_runner,
):
    import main

    document_ids = tuple(f"doc-{i:03d}" for i in range(100))
    await seed_collection(
        postgres_session_factory, "col-cli", document_ids=document_ids
    )
    for index, document_id in enumerate(document_ids):
        await SourceArtifactRepo.replace_document(
            "col-cli",
            SourceDocument(
                document_id=document_id,
                document_order=index,
                title="Synthetic fixture; no scientific evidence",
                text="",
                blocks=(
                    SourceBlock(
                        block_id=f"methods-{index}",
                        document_id=document_id,
                        block_type="paragraph",
                        text="Synthetic conditions remain unknown.",
                        block_order=0,
                        page=1,
                        heading_path="Methods",
                    ),
                ),
            ),
        )

    def offline_model():
        model = _Model(
            *(
                ModelTurn(
                    content="Unknown; synthetic fixture is not scientific evidence."
                )
                for _ in range(4)
            )
        )
        model.client = SimpleNamespace(close=AsyncMock())
        return model

    monkeypatch.setattr(main, "OpenAIChatModel", offline_model)
    monkeypatch.setenv(
        "LENS_TEST_DATABASE_URL",
        postgres_sync_engine.url.render_as_string(hide_password=False),
    )
    snapshot_path = tmp_path / "prepared.json"
    args = SimpleNamespace(
        collection_id="col-cli",
        user_id="user-1",
        output=snapshot_path,
        snapshot=True,
        expected_snapshot=None,
        fixture=Path("tests/fixtures/chat/inconel718_four_turns.json"),
    )
    assert await replay.run(args) == 0
    frozen = json.loads(snapshot_path.read_text())
    assert len(frozen["corpus"]) == 100
    args.snapshot = False
    args.expected_snapshot = snapshot_path
    args.output = tmp_path / "report.json"
    assert await replay.run(args) == 0
    report = json.loads(args.output.read_text())
    assert len(report["turns"]) == 4
    assert (
        report["technical_result"] == "passed" and report["scientific_data_unchanged"]
    )
    assert report["scientific_review"] == "not_reviewed"

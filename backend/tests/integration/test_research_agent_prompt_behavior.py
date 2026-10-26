"""Opt-in provider-backed checks for the Research Agent initialization prompt.

These tests deliberately use the production runner and read capabilities. They
are skipped in normal CI because they spend provider quota and require an
explicit operator-supplied endpoint. No environment file is loaded here.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from openai import AsyncOpenAI

from application.chat import CapabilityRegistry, ResearchAgentRunner
from application.chat.agent_runner import AgentRunLimits
from application.chat.capabilities import (
    AgentContext,
    BrowseCollectionPapersCapability,
    GetCollectionContextCapability,
    InspectDocumentSourcesCapability,
    InspectTableCapability,
    ReadSourceCapability,
    SearchSourcesCapability,
)
from application.chat.tool_result_projection import tool_result_record
from domain.source import Document, SourceDocument
from repositories.collection_repository import StoredDocument
from tests.support.repositories import (
    MemoryDocumentProfileRepository,
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
)

_LIVE = os.environ.get("LENS_RUN_LIVE_PROMPT_TESTS") == "1"
_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "agent_p002"
    / "source_document.json"
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not _LIVE,
        reason="set LENS_RUN_LIVE_PROMPT_TESTS=1 with explicit provider environment to run",
    ),
]


class _EmptyObjectiveRepository:
    async def list_objectives(self, collection_id: str) -> tuple:
        return ()


async def _fixture_collection(collection_service):
    user_id = "live-prompt-test-user"
    collection = await collection_service.create_collection(
        "P002 prompt behavior fixture",
        "Isolated in-memory collection for the opt-in prompt check.",
        owner_user_id=user_id,
    )
    record = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    document_id = record["document_id"]
    now = datetime.now(timezone.utc).isoformat()
    stored_document = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="P002-preheating.pdf",
            sha256=sha256(document_id.encode()).hexdigest(),
            media_type="application/pdf",
            status="ready",
            size_bytes=1,
        ),
        stored_filename="P002-preheating.pdf",
        storage_key=f"{collection['collection_id']}/P002-preheating.pdf",
        created_at=now,
        updated_at=now,
    )
    await collection_service.repository.add_documents(
        collection["collection_id"],
        (stored_document,),
        updated_at=now,
    )
    sources = MemorySourceArtifactRepository()
    await sources.replace_document(
        collection["collection_id"], SourceDocument.from_record(record)
    )
    return user_id, collection["collection_id"], document_id, sources


def _runner(*, client: AsyncOpenAI, collection_service, sources):
    profiles = MemoryDocumentProfileRepository()
    maps = MemoryPaperMapRepository()
    objective_repository = _EmptyObjectiveRepository()
    handlers = (
        GetCollectionContextCapability(
            collection_service=collection_service,
            objective_repository=objective_repository,
        ),
        BrowseCollectionPapersCapability(
            collection_service=collection_service,
            document_profile_repository=profiles,
            paper_map_repository=maps,
            source_artifact_repository=sources,
        ),
        InspectDocumentSourcesCapability(
            collection_service=collection_service,
            source_artifact_repository=sources,
        ),
        SearchSourcesCapability(
            collection_service=collection_service,
            source_artifact_repository=sources,
        ),
        ReadSourceCapability(
            collection_service=collection_service,
            source_artifact_repository=sources,
        ),
        InspectTableCapability(
            collection_service=collection_service,
            source_artifact_repository=sources,
        ),
    )
    from infra.llm.chat_model import OpenAIChatModel

    return ResearchAgentRunner(
        model=OpenAIChatModel(
            client=client,
            model=os.environ["LLM_MODEL"],
        ),
        capabilities=CapabilityRegistry(handlers),
        limits=AgentRunLimits(
            max_elapsed_seconds=240,
            max_tool_calls=14,
            max_model_tokens=30_000,
            max_request_seconds=60,
            max_finalization_seconds=60,
        ),
    )


async def test_live_agent_reads_source_when_profile_and_map_are_missing(
    collection_service,
):
    """A readable paper remains inspectable without optional navigation metadata."""

    required = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    if any(not os.environ.get(name) for name in required):
        pytest.skip("explicit LLM_API_KEY, LLM_BASE_URL and LLM_MODEL are required")
    user_id, collection_id, document_id, sources = await _fixture_collection(
        collection_service
    )
    client = AsyncOpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ["LLM_BASE_URL"],
        timeout=60,
    )
    try:
        result = await _runner(
            client=client,
            collection_service=collection_service,
            sources=sources,
        ).run_turn(
            context=AgentContext(
                session_id="live-prompt-session",
                user_id=user_id,
                collection_id=collection_id,
            ),
            previous_messages=(),
            permission_mode="read_only",
            user_message=(
                "Select the paper about 316L build-platform preheating and inspect "
                "the experimental conditions and tensile table. Report the NP and "
                "P150 elongation values with Source citations."
            ),
        )
    finally:
        await client.close()

    assert result.status == "completed", result.error_code
    assert any(
        call.name in {"inspect_document_sources", "read_source", "inspect_table"}
        for call in result.tool_calls
    ), [call.name for call in result.tool_calls]
    assert any(
        outcome.status == "succeeded"
        and (
            outcome.data.get("document_id") == document_id
            or (
                isinstance(outcome.data.get("document"), dict)
                and outcome.data["document"].get("document_id") == document_id
            )
        )
        for outcome in result.tool_results
    ), [tool_result_record(outcome) for outcome in result.tool_results]
    answer = " ".join(message.content for message in result.messages if message.content)
    assert "72" in answer and "82" in answer
    assert not any(
        phrase in answer.casefold()
        for phrase in ("build a paper map first", "manually review the pdf", "cannot inspect")
    )


@pytest.mark.parametrize("knowledge_scope", ["ordinary", "no_web", "supplied_only"])
async def test_live_agent_respects_the_requested_knowledge_scope(
    collection_service, knowledge_scope,
):
    """A trend supports arithmetic; explaining its mechanism needs allowed premises."""

    required = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    if any(not os.environ.get(name) for name in required):
        pytest.skip("explicit LLM_API_KEY, LLM_BASE_URL and LLM_MODEL are required")
    user_id, collection_id, _document_id, sources = await _fixture_collection(
        collection_service
    )
    scope_instruction = {
        "ordinary": "",
        "no_web": "Do not search the web.",
        "supplied_only": (
            "Use only the supplied facts below. Do not use model background "
            "knowledge or external scientific facts, including when explaining "
            "mechanisms or proposing hypotheses."
        ),
    }[knowledge_scope]
    client = AsyncOpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ["LLM_BASE_URL"],
        timeout=60,
    )
    try:
        result = await _runner(
            client=client, collection_service=collection_service, sources=sources,
        ).run_turn(
            context=AgentContext(
                session_id=f"live-knowledge-{knowledge_scope}",
                user_id=user_id,
                collection_id=collection_id,
            ),
            previous_messages=(),
            permission_mode="none",
            user_message=(
                f"{scope_instruction}\n"
                "User-supplied controlled observations: the same alloy was tensile "
                "tested under matched conditions before and after heat treatment. "
                "Yield strength changed from 600 MPa to 500 MPa; elongation "
                "changed from 10% to 15%. No mechanism measurements or explanations "
                "are supplied. Calculate the elongation change in percentage points "
                "and explain possible physical mechanisms, distinguishing observations "
                "from hypotheses and stating what cannot be determined. Do not read "
                "the collection or save anything. Return only a JSON object with "
                "elongation_change_pp (number), mechanism_hypotheses (list of objects "
                "with hypothesis and basis strings), and mechanism_gap (string)."
            ),
        )
    finally:
        await client.close()

    assert result.status == "completed", result.error_code
    assert not result.tool_calls
    answer = result.messages[-1].content.strip()
    if answer.startswith("```json") and answer.endswith("```"):
        answer = answer[len("```json"): -len("```")].strip()
    payload = json.loads(answer)
    assert payload["elongation_change_pp"] == 5
    assert payload["mechanism_gap"].strip()
    hypotheses = payload["mechanism_hypotheses"]
    assert isinstance(hypotheses, list)
    if knowledge_scope == "supplied_only":
        assert hypotheses == [], payload
    else:
        assert hypotheses, payload
        assert all(item["hypothesis"].strip() and item["basis"].strip()
                   for item in hypotheses)

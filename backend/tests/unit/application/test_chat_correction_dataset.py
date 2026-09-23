from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.evaluation.chat_correction_dataset_service import (
    ChatCorrectionDatasetAccessError,
    ChatCorrectionDatasetService,
    _AcceptedCandidate,
    _remove_partition_conflicts,
)
from domain.evaluation import ChatCorrectionDatasetSelection, ChatCorrectionDatasetRow, sample_digest
from tests.support.chat_correction_dataset import MemoryChatCorrectionDatasetRepository
from tests.unit.application.test_chat_correction_review import _setup


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _SourceRepository:
    async def read_document(self, collection_id: str, document_id: str):
        if collection_id != "collection" or document_id != "doc-1":
            return None
        return SimpleNamespace(document_id=document_id)


async def _accepted_service():
    _chat, case_service, review_service, _reviews, case = await _setup()
    sample = await review_service.create_sample_for_user(
        "chat-review", case.case_id, "researcher"
    )
    await review_service.review_sample_for_user(
        "chat-review",
        sample.sample_id,
        "researcher",
        decision="accept",
        support_message_ids=("msg-tool-result", "msg-corrected"),
    )
    repository = MemoryChatCorrectionDatasetRepository()
    service = ChatCorrectionDatasetService(
        chat_session_service=case_service,
        review_service=review_service,
        repository=repository,
        source_artifact_repository=_SourceRepository(),
    )
    return service, repository, sample


async def test_freeze_preserves_exact_row_and_rebuilds_same_digest() -> None:
    service, repository, sample = await _accepted_service()
    selection = ChatCorrectionDatasetSelection("chat-review", sample.sample_id, "train")

    first = await service.create_dataset_for_user(
        user_id="researcher",
        collection_id="collection",
        selections=(selection,),
        paper_families={"doc-1": "alloy-family"},
    )
    second = await service.create_dataset_for_user(
        user_id="researcher",
        collection_id="collection",
        selections=(selection,),
        paper_families={"doc-1": "alloy-family"},
    )

    assert first.digest == second.digest
    assert first.provenance_digest == second.provenance_digest
    assert first.rows[0].input["tools"]
    assert first.rows[0].paper_families[0]["family_id"] == "alloy-family"
    assert len(repository.manifests) == 1


async def test_withdrawal_excludes_new_snapshot_but_keeps_old_manifest() -> None:
    service, repository, sample = await _accepted_service()
    selection = ChatCorrectionDatasetSelection("chat-review", sample.sample_id, "train")
    old = await service.freeze_for_user(
        user_id="researcher", collection_id="collection", selections=(selection,), paper_families={"doc-1": "family"}
    )
    await service.review_service.review_sample_for_user(
        "chat-review", sample.sample_id, "researcher", decision="withdraw", reason="superseded"
    )
    new = await service.freeze_for_user(
        user_id="researcher", collection_id="collection", selections=(selection,), paper_families={"doc-1": "family"}
    )

    assert old.row_count == 1
    assert new.row_count == 0
    assert new.exclusions[0].reason.value == "withdrawn"
    assert old.digest != new.digest
    assert await service.get_dataset_for_user(old.dataset_id, "researcher") == old
    assert len(repository.manifests) == 2


async def test_train_eval_partition_conflict_excludes_valid_candidates() -> None:
    service, _, sample = await _accepted_service()
    manifest = await service.create_dataset_for_user(
        user_id="researcher",
        collection_id="collection",
        selections=(ChatCorrectionDatasetSelection("chat-review", sample.sample_id, "train"),),
        paper_families={"doc-1": "family"},
    )
    first = manifest.rows[0]
    second_content = first.content_for_digest()
    second_content.update(
        {
            "sample_id": "chat_sample_second",
            "case_id": "chat_case_second",
            "split": "eval",
        }
    )
    second = ChatCorrectionDatasetRow(
        row_id="chat_dataset_row_second",
        content_digest=sample_digest(second_content),
        **second_content,
    )

    accepted, exclusions = _remove_partition_conflicts(
        (
            _AcceptedCandidate(
                selection=ChatCorrectionDatasetSelection("chat-review", first.sample_id, "train"),
                row=first,
                family_ids=("family",),
            ),
            _AcceptedCandidate(
                selection=ChatCorrectionDatasetSelection("chat-review", second.sample_id, "eval"),
                row=second,
                family_ids=("family",),
            ),
        )
    )

    assert accepted == ()
    assert len(exclusions) == 2
    assert {item.reason.value for item in exclusions} == {"partition_conflict"}


async def test_cross_collection_selection_is_rejected() -> None:
    service, _, sample = await _accepted_service()
    with pytest.raises(ChatCorrectionDatasetAccessError):
        await service.create_dataset_for_user(
            user_id="researcher",
            collection_id="other-collection",
            selections=(ChatCorrectionDatasetSelection("chat-review", sample.sample_id, "train"),),
            paper_families={"doc-1": "family"},
        )


async def test_jsonl_contains_manifest_rows_and_exclusions() -> None:
    service, _, sample = await _accepted_service()
    manifest = await service.create_dataset_for_user(
        user_id="researcher",
        collection_id="collection",
        selections=(ChatCorrectionDatasetSelection("chat-review", sample.sample_id, "train"),),
        paper_families={"doc-1": "family"},
    )
    content = await service.jsonl_for_user(manifest.dataset_id, "researcher")
    lines = content.strip().splitlines()
    assert '"record_type":"manifest"' in lines[0]
    assert '"record_type":"sample"' in lines[1]

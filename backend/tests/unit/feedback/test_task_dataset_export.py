from __future__ import annotations

import json
from dataclasses import replace

import pytest

from application.feedback.dataset_export_service import (
    DatasetExportError,
    FeedbackDatasetExportService,
)
from application.repositories.feedback_dataset_export_repository import (
    DatasetExportConflict,
    DatasetExportDraft,
    DatasetExportIdempotencyConflict,
    DatasetExportSummary,
)
from application.repositories.feedback_dataset_sample_repository import (
    ConfirmedDatasetMember,
)
from domain.feedback import Dataset, DatasetExport, DatasetSample, SampleRevision
from domain.feedback.sample_revision import (
    EvaluationRevisionContent,
    PreferenceRevisionContent,
    SftRevisionContent,
    content_digest_for,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _dataset() -> Dataset:
    return Dataset(
        dataset_id="fdset_export_test",
        collection_id="collection-1",
        name="文献问答 SFT",
        task_type="sft",
        construction_spec={"language": "zh-CN"},
        spec_version=1,
        created_by="user-1",
    )


def _content(index: int = 1) -> SftRevisionContent:
    return SftRevisionContent.from_mapping(
        {
            "schema_version": "literature-sft.v1",
            "messages": [{"role": "user", "content": f"比较文献 {index} 的预热条件。"}],
            "context": [
                {
                    "document_title": f"文献 {index}",
                    "text": "图注记录了 200 C 的预热条件。",
                }
            ],
            "target": "文献图注明确记录了 200 C 的预热条件。",
            "evidence": [
                {
                    "document_title": f"文献 {index}",
                    "text": "图注记录了 200 C 的预热条件。",
                }
            ],
        }
    )


def _member(index: int = 1, *, complete: bool = True) -> ConfirmedDatasetMember:
    sample_id = f"sample-{index}"
    case_id = f"case-{index}"
    revision_id = f"revision-{index}"
    content = _content(index)
    sample = DatasetSample(
        sample_id=sample_id,
        dataset_id="fdset_export_test",
        source_case_id=case_id,
        status="confirmed",
        current_revision_id=revision_id,
        confirmed_revision_id=revision_id,
        generation=1,
        source_digest="a" * 64,
        active_job_id=None,
        missing_reasons=(),
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
        confirmed_by="user-1",
        confirmed_at="2026-09-29T00:01:00+00:00",
    )
    revision = SampleRevision(
        revision_id=revision_id,
        sample_id=sample_id,
        revision_no=1,
        author_kind="human",
        content=content,
        content_digest=content_digest_for(content),
        input_digest="b" * 64,
        construction_spec_version=1,
        provenance=(
            {
                "session_id": "session-1",
                "anchor_message_id": "answer-1",
                "related_message_ids": ["question-1", "answer-1"],
                "source_refs": ["source-ref-1"],
                "evidence_records": [
                    {
                        "document_id": "doc-1",
                        "source_ref": "source-ref-1",
                        "document_title": "文献 1",
                        "page": 8,
                        "heading_path": "Results > Figure 3",
                        "quote": "图注记录了 200 C 的预热条件。",
                    }
                ],
            }
            if complete
            else {}
        ),
        created_at="2026-09-29T00:01:00+00:00",
        created_by="user-1",
        job_id=None,
    )
    return ConfirmedDatasetMember(sample=sample, revision=revision)


class _DatasetService:
    def __init__(self, dataset: Dataset | None = None) -> None:
        self.dataset = dataset or _dataset()

    async def read_for_user(self, *, user_id: str, dataset_id: str) -> Dataset:
        assert user_id == "user-1"
        if dataset_id != "fdset_export_test":
            raise FileNotFoundError("dataset not found")
        return self.dataset


class _Samples:
    def __init__(self, *members: ConfirmedDatasetMember) -> None:
        self.members = list(members)

    async def read_confirmed_members(self, *, dataset_id: str):
        assert dataset_id == "fdset_export_test"
        return tuple(self.members)


class _Exports:
    def __init__(self) -> None:
        self.previews: dict[str, object] = {}
        self.exports: dict[str, DatasetExport] = {}
        self.by_key: dict[tuple[str, str], DatasetExport] = {}
        self.publish_calls = 0

    async def save_preview(self, preview):
        self.previews[preview.preview_id] = preview
        return preview

    async def read_preview(self, preview_id: str):
        return self.previews.get(preview_id)

    async def list_exports(self, *, dataset_id: str, limit: int = 50, offset: int = 0):
        values = [item for item in self.exports.values() if item.dataset_id == dataset_id]
        return tuple(
            DatasetExportSummary(
                export_id=item.export_id,
                dataset_id=item.dataset_id,
                export_no=item.export_no,
                schema_version=item.schema_version,
                row_count=item.row_count,
                content_digest=item.content_digest,
                provenance_digest=item.provenance_digest,
                manifest_digest=item.manifest_digest,
                created_at=item.created_at,
            )
            for item in values[offset : offset + limit]
        )

    async def publish_if_current(self, *, draft: DatasetExportDraft) -> DatasetExport:
        self.publish_calls += 1
        key = (draft.dataset_id, draft.idempotency_key)
        existing = self.by_key.get(key)
        if existing is not None:
            if (
                existing.preview_id != draft.preview_id
                or existing.content_digest != draft.content_digest
            ):
                raise DatasetExportIdempotencyConflict("export_idempotency_identity_conflict")
            return existing
        preview = self.previews[draft.preview_id]
        if preview.preview_digest != draft.preview_digest:
            raise DatasetExportConflict("export_preview_stale")
        export_no = len(self.exports) + 1
        export_id = str(draft.manifest["export_id"])
        manifest = {
            **draft.manifest,
            "export_id": export_id,
            "export_no": export_no,
        }
        from domain.feedback.dataset_export import digest_for_value

        export = DatasetExport(
            export_id=export_id,
            dataset_id=draft.dataset_id,
            export_no=export_no,
            schema_version=str(draft.manifest["schema_version"]),
            rows=draft.rows,
            provenance=draft.provenance,
            members=draft.members,
            preview_id=draft.preview_id,
            preview_digest=draft.preview_digest,
            member_digest=draft.member_digest,
            content_digest=draft.content_digest,
            provenance_digest=draft.provenance_digest,
            manifest_digest=digest_for_value(manifest),
            manifest=manifest,
            created_by=draft.created_by,
            idempotency_key=draft.idempotency_key,
            created_at=draft.created_at,
        )
        self.exports[export_id] = export
        self.by_key[key] = export
        return export

    async def read_export(self, export_id: str):
        return self.exports.get(export_id)


def _service(
    samples: _Samples, exports: _Exports, dataset: Dataset | None = None
) -> FeedbackDatasetExportService:
    return FeedbackDatasetExportService(
        dataset_service=_DatasetService(dataset),
        sample_repository=samples,
        repository=exports,
    )


async def test_selected_export_ignores_unselected_changes_but_rejects_selected_changes():
    samples = _Samples(_member(1), _member(2))
    service = _service(samples, _Exports())
    preview = await service.preview_for_user(
        user_id="user-1", dataset_id="fdset_export_test", sample_ids=["sample-1"]
    )
    assert [item.sample_id for item in preview.members] == ["sample-1"]
    samples.members = [samples.members[0]]
    export = await service.publish_for_user(
        user_id="user-1", dataset_id="fdset_export_test",
        preview_id=preview.preview_id, preview_digest=preview.preview_digest,
        allow_partial=False, idempotency_key="selected-export",
    )
    assert export.row_count == 1
    samples.members = []
    with pytest.raises(DatasetExportError, match="export_preview_stale"):
        await service.publish_for_user(
            user_id="user-1", dataset_id="fdset_export_test",
            preview_id=preview.preview_id, preview_digest=preview.preview_digest,
            allow_partial=False, idempotency_key="changed-export",
        )


@pytest.mark.parametrize("selection", [[], ["sample-1", "sample-1"], ["foreign-sample"]])
async def test_export_rejects_invalid_selection(selection):
    with pytest.raises(DatasetExportError, match="export_sample_selection_invalid"):
        await _service(_Samples(_member()), _Exports()).preview_for_user(
            user_id="user-1", dataset_id="fdset_export_test", sample_ids=selection
        )


def _content_member(content, *, sample_id: str, dataset_id: str = "fdset_export_test") -> ConfirmedDatasetMember:
    sample = DatasetSample(
        sample_id=sample_id,
        dataset_id=dataset_id,
        source_case_id=f"case-{sample_id}",
        status="confirmed",
        current_revision_id=f"revision-{sample_id}",
        confirmed_revision_id=f"revision-{sample_id}",
        generation=1,
        source_digest="a" * 64,
        active_job_id=None,
        missing_reasons=(),
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
        confirmed_by="user-1",
        confirmed_at="2026-09-29T00:01:00+00:00",
    )
    revision = SampleRevision(
        revision_id=f"revision-{sample_id}",
        sample_id=sample_id,
        revision_no=1,
        author_kind="human",
        content=content,
        content_digest=content_digest_for(content),
        input_digest="b" * 64,
        construction_spec_version=1,
        provenance={
            "session_id": "session-1",
            "anchor_message_id": "answer-1",
            "related_message_ids": ["question-1", "answer-1"],
            "source_refs": ["source-ref-1"],
            "evidence_records": [{"document_title": "文献", "quote": "原文"}],
        },
        created_at="2026-09-29T00:01:00+00:00",
        created_by="user-1",
        job_id=None,
    )
    return ConfirmedDatasetMember(sample=sample, revision=revision)


@pytest.mark.anyio
async def test_preview_reports_invalid_provenance_and_partial_publish_excludes_it() -> None:
    samples = _Samples(_member(1), _member(2, complete=False))
    exports = _Exports()
    service = _service(samples, exports)

    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")

    assert preview.requested_count == 2
    assert preview.exportable_count == 1
    assert {issue.sample_id for issue in preview.issues} == {"sample-2"}
    with pytest.raises(DatasetExportError, match="export_preview_has_issues"):
        await service.publish_for_user(
            user_id="user-1",
            dataset_id="fdset_export_test",
            preview_id=preview.preview_id,
            preview_digest=preview.preview_digest,
            allow_partial=False,
            idempotency_key="publish-1",
        )

    exported = await service.publish_for_user(
        user_id="user-1",
        dataset_id="fdset_export_test",
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=True,
        idempotency_key="publish-1",
    )
    assert exported.row_count == 1
    assert exported.members[0].sample_id == "sample-1"


@pytest.mark.anyio
async def test_publish_rejects_empty_export_and_stale_preview() -> None:
    empty_samples = _Samples()
    empty_exports = _Exports()
    empty_service = _service(empty_samples, empty_exports)
    empty_preview = await empty_service.preview_for_user(
        user_id="user-1", dataset_id="fdset_export_test"
    )
    with pytest.raises(DatasetExportError, match="empty_export"):
        await empty_service.publish_for_user(
            user_id="user-1",
            dataset_id="fdset_export_test",
            preview_id=empty_preview.preview_id,
            preview_digest=empty_preview.preview_digest,
            allow_partial=False,
            idempotency_key="empty-1",
        )

    samples = _Samples(_member(1))
    exports = _Exports()
    service = _service(samples, exports)
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    samples.members[0] = _member(2)
    with pytest.raises(DatasetExportError, match="export_preview_stale"):
        await service.publish_for_user(
            user_id="user-1",
            dataset_id="fdset_export_test",
            preview_id=preview.preview_id,
            preview_digest=preview.preview_digest,
            allow_partial=False,
            idempotency_key="stale-1",
        )


@pytest.mark.anyio
async def test_publish_is_idempotent_and_separates_model_file_from_provenance() -> None:
    samples = _Samples(_member(1))
    exports = _Exports()
    service = _service(samples, exports)
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")

    first = await service.publish_for_user(
        user_id="user-1",
        dataset_id="fdset_export_test",
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="same-key",
    )
    second = await service.publish_for_user(
        user_id="user-1",
        dataset_id="fdset_export_test",
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="same-key",
    )
    assert second == first
    assert exports.publish_calls == 2

    model_row = first.rows[0]
    serialized = json.dumps(model_row, ensure_ascii=False)
    for internal_id in ("sample-1", "case-1", "revision-1", "session-1", "source-ref-1"):
        assert internal_id not in serialized
    assert first.provenance[0]["sample_id"] == "sample-1"
    assert first.provenance[0]["evidence_records"][0]["heading_path"] == "Results > Figure 3"


@pytest.mark.anyio
async def test_preference_export_requires_human_a_or_b_and_maps_chosen_rejected() -> None:
    content = PreferenceRevisionContent.from_mapping(
        {
            "schema_version": "literature-preference.v1",
            "messages": [{"role": "user", "content": "比较 A、B。"}],
            "context": [{"document_title": "文献", "text": "原文"}],
            "response_a": "回答 A",
            "response_b": "回答 B",
            "suggested_preference": "a",
            "rationale": "AI 建议 A",
            "evidence": [{"document_title": "文献", "text": "原文"}],
        }
    )
    dataset = replace(_dataset(), task_type="preference")
    samples = _Samples(_content_member(content, sample_id="preference-1"))
    exports = _Exports()
    service = _service(samples, exports, dataset)
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    assert preview.exportable_count == 0
    assert any(issue.code == "preference_not_pairwise" for issue in preview.issues)

    content_with_label = PreferenceRevisionContent.from_mapping(
        {**content.to_record(), "human_preference": "b"}
    )
    samples.members = [_content_member(content_with_label, sample_id="preference-1")]
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    assert preview.issues == ()
    exported = await service.publish_for_user(
        user_id="user-1",
        dataset_id="fdset_export_test",
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="preference-1",
    )
    assert exported.rows[0]["chosen"] == "回答 B"
    assert exported.rows[0]["rejected"] == "回答 A"
    assert "suggested_preference" not in exported.rows[0]


@pytest.mark.anyio
async def test_evaluation_export_keeps_reference_criteria_and_evidence() -> None:
    content = EvaluationRevisionContent.from_mapping(
        {
            "schema_version": "literature-evaluation.v1",
            "messages": [{"role": "user", "content": "比较 A、B。"}],
            "context": [{"document_title": "文献", "text": "原文"}],
            "reference": "B 有预热。",
            "criteria": ["指出 B 的预热条件", "引用图注"],
            "evaluation_mode": "reference",
            "evidence": [{"document_title": "文献", "text": "原文"}],
        }
    )
    dataset = replace(_dataset(), task_type="evaluation")
    service = _service(
        _Samples(_content_member(content, sample_id="evaluation-1")), _Exports(), dataset
    )
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    assert preview.issues == ()
    exported = await service.publish_for_user(
        user_id="user-1",
        dataset_id="fdset_export_test",
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="evaluation-1",
    )
    assert exported.schema_version == "literature-evaluation.v1"
    assert exported.rows[0]["reference"] == "B 有预热。"
    assert exported.rows[0]["criteria"] == ["指出 B 的预热条件", "引用图注"]

from __future__ import annotations

from repositories.feedback_dataset_sample_repository import revision_content_json

from repositories.feedback_dataset_sample_repository import revision_content_from_json

import json
from dataclasses import replace

import pytest
from scripts.evaluation.feedback_dataset.prepare import load_prepared, prepare_export

from application.feedback.dataset_export_service import (
    DatasetExportError,
    FeedbackDatasetExportService,
)
from domain.feedback import Dataset, DatasetExport, DatasetSample, SampleRevision
from domain.feedback.sample_revision import (
    EvaluationRevisionContent,
    PreferenceRevisionContent,
    SftRevisionContent,
    content_digest_for,
)
from repositories.feedback_dataset_export_repository import (
    DatasetExportConflict,
    DatasetExportDraft,
    DatasetExportIdempotencyConflict,
    DatasetExportSummary,
)
from repositories.feedback_dataset_sample_repository import (
    ConfirmedDatasetMember,
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
    return revision_content_from_json(
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

    async def read_confirmed_members(self, *, dataset_id: str, sample_ids=None):
        assert dataset_id == "fdset_export_test"
        return tuple(member for member in self.members if sample_ids is None or member.sample.sample_id in sample_ids)


async def test_selected_export_never_reads_unselected_stale_members() -> None:
    class SamplesWithStaleUnselectedMember(_Samples):
        async def read_confirmed_members(self, *, dataset_id, sample_ids=None):
            if sample_ids is None or "sample-2" in sample_ids:
                from repositories.feedback_dataset_sample_repository import (
                    DatasetSampleRevisionConflict,
                )
                raise DatasetSampleRevisionConflict("sample_source_stale")
            return await super().read_confirmed_members(dataset_id=dataset_id, sample_ids=sample_ids)

    service = FeedbackDatasetExportService(
        dataset_service=_DatasetService(), sample_repository=SamplesWithStaleUnselectedMember(_member(1), _member(2)),
        repository=_Exports(),
    )
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test", sample_ids=["sample-1"])
    export = await service.publish_for_user(
        user_id="user-1", dataset_id="fdset_export_test", preview_id=preview.preview_id,
        preview_digest=preview.preview_digest, allow_partial=False, idempotency_key="selected-healthy",
    )
    assert len(export.rows) == 1


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
    assert set(model_row) == {"messages"}
    assert first.schema_version == "literature-sft.v2"
    assert first.manifest["data_format"] == "messages-sft"
    assert model_row["messages"][0]["content"] == "文献：文献 1\n原文：图注记录了 200 C 的预热条件。\n\n问题：比较文献 1 的预热条件。"
    assert model_row["messages"][-1] == {"role": "assistant", "content": _content().target}
    assert first.provenance[0]["evidence"] == list(_content().evidence)
    serialized = json.dumps(model_row, ensure_ascii=False)
    for internal_id in ("sample-1", "case-1", "revision-1", "session-1", "source-ref-1"):
        assert internal_id not in serialized
    assert first.provenance[0]["sample_id"] == "sample-1"
    assert first.provenance[0]["evidence_records"][0]["heading_path"] == "Results > Figure 3"


@pytest.mark.anyio
@pytest.mark.parametrize("task_type", ["sft", "preference", "evaluation"])
async def test_export_without_excerpts_preserves_input_and_identity(task_type) -> None:
    messages = (
        {"role": "user", "content": "Hold scan speed fixed."},
        {"role": "assistant", "content": "We will compare laser power levels."},
        {"role": "user", "content": "Summarize our decision."},
    )
    common = dict(messages=messages, context=(), evidence=())
    if task_type == "sft":
        content = SftRevisionContent(schema_version="literature-sft.v1", target="Vary power at fixed speed.", **common)
    elif task_type == "preference":
        content = PreferenceRevisionContent(schema_version="literature-preference.v1",
            response_a="Vary power at fixed speed.", response_b="Vary both power and speed.",
            suggested_preference=None, human_preference="a", rationale="Preserves the decision.", **common)
    else:
        content = EvaluationRevisionContent(schema_version="literature-evaluation.v1",
            reference="Vary power at fixed speed.", criteria=("Keep scan speed fixed.",), evaluation_mode="reference", **common)
    member = _content_member(content, sample_id="conversation-1")
    member = replace(member, revision=replace(member.revision, provenance={
        "session_id": "session-1", "anchor_message_id": "answer-1", "evidence_records": [],
    }))
    service = _service(_Samples(member), _Exports(), replace(_dataset(), task_type=task_type))
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    assert preview.issues == ()
    exported = await service.publish_for_user(user_id="user-1", dataset_id="fdset_export_test",
        preview_id=preview.preview_id, preview_digest=preview.preview_digest,
        allow_partial=False, idempotency_key="conversation")
    row = exported.rows[0]
    actual = row["prompt"] if task_type == "preference" else row["messages"]
    assert actual == list(messages) + ([{"role": "assistant", "content": content.target}] if task_type == "sft" else [])
    assert exported.provenance[0]["session_id"] == "session-1"


async def test_preference_export_requires_human_a_or_b_and_maps_chosen_rejected() -> None:
    content = revision_content_from_json(
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

    content_with_label = revision_content_from_json(
        {**revision_content_json(content), "human_preference": "b"}
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
    assert exported.schema_version == "literature-preference.v2"
    assert set(exported.rows[0]) == {"prompt", "chosen", "rejected"}
    assert exported.rows[0]["chosen"] == [{"role": "assistant", "content": "回答 B"}]
    assert exported.rows[0]["rejected"] == [{"role": "assistant", "content": "回答 A"}]
    assert exported.rows[0]["prompt"] == [{"role": "user", "content": "文献：文献\n原文：原文\n\n问题：比较 A、B。"}]
    assert "suggested_preference" not in exported.rows[0]


@pytest.mark.anyio
async def test_evaluation_export_keeps_reference_and_criteria_outside_input() -> None:
    content = revision_content_from_json(
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
    assert exported.schema_version == "literature-evaluation.v2"
    assert set(exported.rows[0]) == {"messages", "reference", "criteria", "evaluation_mode"}
    assert exported.rows[0]["messages"] == [{"role": "user", "content": "文献：文献\n原文：原文\n\n问题：比较 A、B。"}]
    assert exported.rows[0]["reference"] == "B 有预热。"
    assert exported.rows[0]["criteria"] == ["指出 B 的预热条件", "引用图注"]


@pytest.mark.parametrize("task_type", ["sft", "preference", "evaluation"])
async def test_published_files_load_offline_without_review_data_in_input(tmp_path, task_type) -> None:
    question = "固定构建方向时，每个扫描策略条件做了几次拉伸测试？"
    excerpt = "Three tests were conducted for each condition."
    common = {
        "schema_version": f"literature-{task_type}.v1",
        "messages": [{"role": "system", "content": "依据原文回答。"}, {"role": "user", "content": question}],
        "context": [{"document_title": "P006.pdf", "text": excerpt}] * 2,
        "evidence": [{"document_title": "P006.pdf", "text": "Review-only evidence marker"}],
    }
    if task_type == "sft":
        content = revision_content_from_json({**common, "target": "每个条件三次拉伸测试。"})
    elif task_type == "preference":
        content = revision_content_from_json({**common, "response_a": "每个条件三次拉伸测试。",
            "response_b": "每个条件一次。", "human_preference": "a", "rationale": "Private review rationale"})
    else:
        content = revision_content_from_json({**common, "reference": "每个条件三次拉伸测试。",
            "criteria": ["明确三次测试。"], "evaluation_mode": "reference"})
    service = _service(_Samples(_content_member(content, sample_id="p006")), _Exports(), replace(_dataset(), task_type=task_type))
    preview = await service.preview_for_user(user_id="user-1", dataset_id="fdset_export_test")
    export = await service.publish_for_user(user_id="user-1", dataset_id="fdset_export_test",
        preview_id=preview.preview_id, preview_digest=preview.preview_digest, allow_partial=False,
        idempotency_key=f"p006-{task_type}")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for format in ("jsonl", "provenance", "manifest", "json"):
        _, data, _, filename = await service.download_for_user(user_id="user-1", dataset_id="fdset_export_test",
            export_id=export.export_id, format=format)
        (bundle / filename).write_bytes(data)
    row = json.loads((bundle / "data.jsonl").read_text())
    assert json.loads((bundle / "data.json").read_text()) == [row]
    inputs = row["prompt"] if task_type == "preference" else row["messages"][:-1] if task_type == "sft" else row["messages"]
    assert inputs[0] == common["messages"][0]
    assert inputs[-1]["content"].count(excerpt) == 1
    assert inputs[-1]["content"].endswith(question)
    assert "每个条件三次拉伸测试。" not in json.dumps(inputs, ensure_ascii=False)
    assert "Review-only evidence marker" not in json.dumps(row)
    assert "Private review rationale" not in json.dumps(row)
    trace = json.loads((bundle / "provenance.jsonl").read_text())
    assert trace["evidence"] == common["evidence"]
    prepared_dir = tmp_path / "prepared"
    prepare_export(export_path=bundle, output_dir=prepared_dir, revision="test")
    prepared = load_prepared(prepared_dir)
    assert prepared["counts"] == {"train": 0, "eval": 1}


def test_frozen_content_and_preview_fingerprints_keep_their_stored_contract():
    from pathlib import Path
    import json
    from domain.feedback.dataset_export import ExportIssue, ExportMember, ExportPreview, member_digest
    from domain.feedback.sample_revision import content_digest_for
    from repositories.feedback_dataset_sample_repository import revision_content_from_json, revision_content_json

    fixtures = json.loads((Path(__file__).parents[2] / "fixtures" / "sample_revision_fingerprints.json").read_text())
    for fixture in fixtures:
        content = revision_content_from_json(fixture["content"])
        assert revision_content_json(content) == fixture["content"]
        assert content_digest_for(content) == fixture["content_digest"]
        member = ExportMember(
            sample_id="sample-fixed", source_case_id="case-fixed", revision_id="revision-fixed", revision_no=2,
            content=content, content_digest=fixture["content_digest"], input_digest="a" * 64,
            provenance={"paper_order": ["b", "a"], "scope": {"collection": "collection-fixed"}},
        )
        preview = ExportPreview.build(
            preview_id="preview-fixed", dataset_id="dataset-fixed", members=(member,),
            issues=(ExportIssue(sample_id="sample-other", revision_id=None, code="not_confirmed", message="尚未确认", question="控制条件是否一致？"),),
            created_at="2026-10-27T00:00:00Z", expires_at="2026-10-28T00:00:00Z",
        )
        assert preview.preview_digest == fixture["preview_digest"]
        assert member_digest((member,)) == fixture["member_digest"]

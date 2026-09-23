from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.evaluation import ChatCorrectionDatasetManifest, ChatCorrectionDatasetRow, sample_digest
from scripts.evaluation.chat_correction_training.experiment import build_report, load_report, run_experiment
from scripts.evaluation.chat_correction_training.prepare import (
    ContextOverflowError,
    PreparationError,
    load_export,
    prepare_rows,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _row(index: int, split: str, *, family: str | None = None, tree: str | None = None):
    content = {
        "sample_id": f"sample-{index}",
        "case_id": f"case-{index}",
        "session_id": f"session-{index}",
        "collection_id": "collection-1",
        "model_call_id": f"call-{index}",
        "input": {
            "messages": [{"role": "user", "content": f"question-{index}"}],
            "tools": [{"name": "read_source", "parameters": {"type": "object"}}],
            "temperature": 0,
        },
        "observations": ({"kind": "tool_result", "message_id": f"obs-{index}", "text": "Source quote"},),
        "target": f"reviewed target {index}",
        "review_id": f"review-{index}",
        "review_digest": sha256(f"review-{index}".encode()).hexdigest(),
        "source_refs": ({"kind": "message_source", "document_id": f"doc-{index}", "source_ref": f"p-{index}"},),
        "paper_families": ({"document_id": f"doc-{index}", "family_id": family or f"family-{index}"},),
        "session_tree_id": tree or f"tree-{index}",
        "split": split,
    }
    digest = sample_digest(content)
    return ChatCorrectionDatasetRow(
        row_id=f"row-{index}",
        content_digest=digest,
        **content,
    )


def _export(path: Path, rows: tuple[ChatCorrectionDatasetRow, ...]) -> ChatCorrectionDatasetManifest:
    provenance = {
        "schema": "chat-correction-dataset.v1",
        "owner_id": "owner-1",
        "collection_id": "collection-1",
        "selections": [],
        "paper_families": [],
        "source_policy": "exact_p3_source_refs",
    }
    manifest = ChatCorrectionDatasetManifest.create(
        owner_id="owner-1",
        collection_id="collection-1",
        provenance=provenance,
        rows=rows,
        exclusions=(),
        created_at="2026-09-23T00:00:00+00:00",
    )
    lines = [
        {
            "record_type": "manifest",
            "dataset_id": manifest.dataset_id,
            "collection_id": manifest.collection_id,
            "manifest_digest": manifest.digest,
            "provenance_digest": manifest.provenance_digest,
            "provenance": manifest.provenance,
        },
        *({"record_type": "sample", **row.to_record()} for row in rows),
    ]
    path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in lines), encoding="utf-8")
    return manifest


class _Tokenizer:
    eos_token_id = 7

    def encode(self, text: str, *, add_special_tokens: bool = False):
        return [ord(char) % 7 for char in text]

    def decode(self, values, *, skip_special_tokens: bool = True):
        return "".join(str(int(value)) for value in list(values))


def test_prepare_masks_only_final_target_and_rejects_overflow(tmp_path: Path) -> None:
    export_path = tmp_path / "dataset.jsonl"
    _export(export_path, (_row(1, "train"), _row(2, "eval")))
    bundle = load_export(export_path)
    prepared = prepare_rows(bundle, _Tokenizer(), max_length=4096)
    item = prepared[0]
    first_target = next(index for index, value in enumerate(item["labels"]) if value != -100)
    assert item["labels"][:first_target] == [-100] * first_target
    assert item["labels"][first_target:] == item["input_ids"][first_target:]
    assert item["request"]["tools"][0]["name"] == "read_source"
    assert item["observations"][0]["message_id"] == "obs-1"
    with pytest.raises(ContextOverflowError, match="must be shortened"):
        prepare_rows(bundle, _Tokenizer(), max_length=4)


@pytest.mark.parametrize(
    "rows, message",
    [
        ((_row(1, "train"),), "nonempty train and eval"),
        ((_row(1, "train", family="same"), _row(2, "eval", family="same")), "paper family"),
        ((_row(1, "train", tree="same"), _row(2, "eval", tree="same")), "session tree"),
    ],
)
def test_prepare_rejects_empty_or_leaky_partitions(
    tmp_path: Path,
    rows: tuple[ChatCorrectionDatasetRow, ...],
    message: str,
) -> None:
    with pytest.raises(PreparationError, match=message):
        _export(tmp_path / "dataset.jsonl", rows)
        load_export(tmp_path / "dataset.jsonl")


def test_prepare_rejects_manifest_digest_tampering(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    _export(path, (_row(1, "train"), _row(2, "eval")))
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["manifest_digest"] = "0" * 64
    lines[0] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(PreparationError, match="digest"):
        load_export(path)


def test_report_digest_can_be_rebuilt_and_missing_authorization_is_not_run(tmp_path: Path) -> None:
    export_path = tmp_path / "dataset.jsonl"
    _export(export_path, (_row(1, "train"), _row(2, "eval")))
    bundle = load_export(export_path)
    prepared_rows = prepare_rows(bundle, _Tokenizer())
    prepared_dir = tmp_path / "prepared"
    from scripts.evaluation.chat_correction_training.prepare import write_prepared

    write_prepared(
        bundle,
        prepared_rows,
        prepared_dir,
        tokenizer_name="test-tokenizer",
        tokenizer_revision="tok-1",
        max_length=4096,
    )
    report = run_experiment(
        prepared_dir,
        tmp_path / "not-run",
        model_name="missing-model",
        revision="model-1",
    )
    assert report["status"] == "not_run"
    assert "authorization" in report["not_run_reason"]
    assert load_report(tmp_path / "not-run" / "report.json")["report_digest"] == report["report_digest"]
    rebuilt = build_report({"status": "not_run", "lineage": {"dataset": "x"}})
    assert load_report(tmp_path / "not-run" / "report.json")["schema_version"].endswith("report.v1")
    assert rebuilt["report_digest"] == build_report({"status": "not_run", "lineage": {"dataset": "x"}})["report_digest"]


class _TinyTokenizer(_Tokenizer):
    def save_pretrained(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "tokenizer.json").write_text("{}", encoding="utf-8")

    @classmethod
    def from_pretrained(cls, path: Path, **kwargs):
        return cls()


class _TinyModel:
    """A tiny torch model used only to exercise the offline orchestration."""

    def __new__(cls):
        import torch

        class TinyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(8, 8)
                self.projection = torch.nn.Linear(8, 8)

            def forward(self, input_ids, attention_mask=None, labels=None):
                import torch.nn.functional as functional

                logits = self.projection(self.embedding(input_ids))
                loss = functional.cross_entropy(
                    logits.reshape(-1, logits.shape[-1]),
                    labels.reshape(-1),
                    ignore_index=-100,
                )
                return SimpleNamespace(loss=loss)

            def generate(self, input_ids, **kwargs):
                return torch.cat(
                    [
                        input_ids,
                        torch.full((input_ids.shape[0], 1), 7, dtype=torch.long),
                    ],
                    dim=1,
                )

            def save_pretrained(self, path: Path) -> None:
                path.mkdir(parents=True, exist_ok=True)
                torch.save(self.state_dict(), path / "weights.pt")

            @classmethod
            def from_pretrained(cls, path: Path, **kwargs):
                instance = cls()
                instance.load_state_dict(
                    torch.load(path / "weights.pt", weights_only=True)
                )
                return instance

        return TinyModule()


def test_authorized_experiment_compares_baseline_and_reloads_weights(tmp_path: Path) -> None:
    pytest.importorskip("torch", reason="the bounded training-path check uses the isolated training dependency")
    export_path = tmp_path / "dataset.jsonl"
    manifest = _export(export_path, (_row(1, "train"), _row(2, "eval")))
    bundle = load_export(export_path)
    from scripts.evaluation.chat_correction_training.prepare import write_prepared

    prepared_dir = tmp_path / "prepared"
    write_prepared(
        bundle,
        prepare_rows(bundle, _TinyTokenizer()),
        prepared_dir,
        tokenizer_name="tiny",
        tokenizer_revision="tok-1",
        max_length=4096,
    )

    def loader(**kwargs):
        import torch

        return torch, _TinyTokenizer(), _TinyModel()

    report = run_experiment(
        prepared_dir,
        tmp_path / "experiment",
        model_name="tiny",
        revision="model-1",
        authorization={
            "scope": "chat_correction_training",
            "dataset_digest": manifest.digest,
            "approved_by": "research-owner",
            "approved_at": "2026-09-23T00:00:00+00:00",
        },
        max_steps=2,
        loader=loader,
    )
    assert report["status"] == "completed"
    assert report["baseline"]["row_count"] == report["after_training"]["row_count"] == 1
    assert report["reload"]["status"] == "passed"
    assert (tmp_path / "experiment" / "model" / "weights.pt").is_file()
    assert load_report(tmp_path / "experiment" / "report.json")["status"] == "completed"


def test_missing_model_environment_is_not_run_after_authorization(tmp_path: Path) -> None:
    export_path = tmp_path / "dataset.jsonl"
    manifest = _export(export_path, (_row(1, "train"), _row(2, "eval")))
    bundle = load_export(export_path)
    from scripts.evaluation.chat_correction_training.prepare import write_prepared

    prepared_dir = tmp_path / "prepared"
    write_prepared(
        bundle,
        prepare_rows(bundle, _Tokenizer()),
        prepared_dir,
        tokenizer_name="tiny",
        tokenizer_revision="tok-1",
        max_length=4096,
    )

    def unavailable_loader(**kwargs):
        raise ImportError("training dependency absent")

    report = run_experiment(
        prepared_dir,
        tmp_path / "missing-model",
        model_name="missing",
        revision="model-1",
        authorization={
            "scope": "chat_correction_training",
            "dataset_digest": manifest.digest,
            "approved_by": "research-owner",
            "approved_at": "2026-09-23T00:00:00+00:00",
        },
        loader=unavailable_loader,
    )
    assert report["status"] == "not_run"
    assert "environment" in report["not_run_reason"]

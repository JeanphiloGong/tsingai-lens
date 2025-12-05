import json
from types import SimpleNamespace

import pytest

from services.document_manager import DocumentManager
from services import llm_client as llm_module


def test_document_manager_register_get_list_and_path(tmp_path):
    index_file = tmp_path / "index.json"
    docs_dir = tmp_path / "docs"
    manager = DocumentManager(index_file=index_file, documents_dir=docs_dir)

    doc_id = manager.register(
        original_filename="paper.pdf",
        stored_filename="stored.pdf",
        tags=["science"],
        metadata={"author": "Ada"},
        doc_id="doc-1",
    )

    assert doc_id == "doc-1"
    loaded = manager.get(doc_id)
    assert loaded["original_filename"] == "paper.pdf"
    assert loaded["tags"] == ["science"]
    assert manager.list() == [loaded]
    assert manager.path_for(doc_id) == docs_dir / "stored.pdf"
    assert json.loads(index_file.read_text(encoding="utf-8"))[doc_id]["filename"] == "stored.pdf"


def test_document_manager_path_for_missing(tmp_path):
    manager = DocumentManager(index_file=tmp_path / "index.json", documents_dir=tmp_path / "docs")
    with pytest.raises(FileNotFoundError):
        manager.path_for("missing-id")

def test_llm_client_chat_and_summarize(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="mocked"))])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = FakeChat()

    monkeypatch.setattr(llm_module, "OpenAI", FakeOpenAI)
    client = llm_module.LLMClient(api_key="k", base_url="http://fake", model="gpt-test", max_tokens=123)

    chat_result = client.chat(system="sys", user="who?", temperature=0.5)
    assert chat_result == "mocked"
    assert captured["model"] == "gpt-test"
    assert captured["temperature"] == 0.5
    assert captured["max_tokens"] == 123

    called = {}

    def fake_chat(system: str, user: str, temperature: float = 0.3) -> str:
        called["system"] = system
        called["user"] = user
        called["temperature"] = temperature
        return "summary"

    client.chat = fake_chat
    summary = client.summarize("content here")
    assert summary == "summary"
    assert "content here" in called["user"]
    assert called["system"].startswith("你是科研助手")

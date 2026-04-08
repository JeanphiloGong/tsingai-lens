from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from types import ModuleType


def test_legacy_query_usecase_delegates_to_application(monkeypatch):
    payload = SimpleNamespace(query="test")
    sentinel = object()

    fake_application = ModuleType("application")
    fake_application.__path__ = []
    fake_query_module = ModuleType("application.query")

    async def fake_query_index(received_payload):  # noqa: ANN001
        assert received_payload is payload
        return sentinel

    fake_query_module.query_index = fake_query_index
    fake_application.query = fake_query_module
    monkeypatch.setitem(sys.modules, "application", fake_application)
    monkeypatch.setitem(sys.modules, "application.query", fake_query_module)
    sys.modules.pop("app.usecases.query", None)

    legacy_query = importlib.import_module("app.usecases.query")
    assert asyncio.run(legacy_query.query_index(payload)) is sentinel


def test_legacy_reports_usecases_delegate_to_application(monkeypatch):
    list_sentinel = object()
    detail_sentinel = object()
    patterns_sentinel = object()

    fake_application = ModuleType("application")
    fake_application.__path__ = []
    fake_reports_module = ModuleType("application.reports")

    def fake_list_community_reports(**kwargs):  # noqa: ANN003
        assert kwargs == {
            "collection_id": "c1",
            "level": 2,
            "limit": 10,
            "offset": 5,
            "min_size": 1,
            "sort": "rating",
        }
        return list_sentinel

    def fake_get_community_report_detail(**kwargs):  # noqa: ANN003
        assert kwargs == {
            "collection_id": "c1",
            "community_id": "7",
            "level": 3,
            "entity_limit": 20,
            "relationship_limit": 15,
            "document_limit": 12,
        }
        return detail_sentinel

    def fake_list_patterns(**kwargs):  # noqa: ANN003
        assert kwargs == {
            "collection_id": "c1",
            "level": 2,
            "limit": 4,
            "sort": "size",
        }
        return patterns_sentinel

    fake_reports_module.list_community_reports = fake_list_community_reports
    fake_reports_module.get_community_report_detail = fake_get_community_report_detail
    fake_reports_module.list_patterns = fake_list_patterns
    fake_application.reports = fake_reports_module
    monkeypatch.setitem(sys.modules, "application", fake_application)
    monkeypatch.setitem(sys.modules, "application.reports", fake_reports_module)
    sys.modules.pop("app.usecases.reports", None)

    legacy_reports = importlib.import_module("app.usecases.reports")
    assert (
        legacy_reports.list_community_reports(
            collection_id="c1",
            level=2,
            limit=10,
            offset=5,
            min_size=1,
            sort="rating",
        )
        is list_sentinel
    )
    assert (
        legacy_reports.get_community_report_detail(
            collection_id="c1",
            community_id="7",
            level=3,
            entity_limit=20,
            relationship_limit=15,
            document_limit=12,
        )
        is detail_sentinel
    )
    assert (
        legacy_reports.list_patterns(
            collection_id="c1",
            level=2,
            limit=4,
            sort="size",
        )
        is patterns_sentinel
    )

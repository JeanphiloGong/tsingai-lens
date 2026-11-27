from agent.application.answer_citations import bind_answer_citations
from agent.domain.models import Operation


def _operation(
    *,
    name: str,
    data: dict[str, object],
    resource_id: str,
    status: str = "succeeded",
) -> Operation:
    return Operation(
        operation_id=f"op-{name}",
        task_id="task-1",
        name=name,
        arguments_digest="a" * 64,
        status=status,
        result={
            "status": status,
            "data": data,
            "resource_refs": (
                {
                    "resource_type": "source",
                    "resource_id": resource_id,
                    "href": "/workspaces/ws-1/documents/doc-a",
                },
            ),
        },
    )


def test_binds_complete_source_and_keeps_utf16_offset() -> None:
    operation = _operation(
        name="inspect_table",
        data={
            "document_id": "doc-a",
            "document_title": "Paper A",
            "table_ref": "table-3",
            "source_kind": "table",
            "page": 8,
            "caption": "Table 3. Heat treatment",
            "complete_table": True,
            "content_truncated": False,
        },
        resource_id="doc-a:table-3",
    )

    content, citations = bind_answer_citations(
        "🔬 保温时间为 30 分钟。[[cite:doc-a/table-3]]", (operation,)
    )

    assert content == "🔬 保温时间为 30 分钟。"
    assert citations[0].offset == len("🔬 保温时间为 30 分钟。".encode("utf-16-le")) // 2
    assert citations[0].caption == "Table 3. Heat treatment"


def test_removes_markers_without_complete_support() -> None:
    operation = _operation(
        name="inspect_table",
        data={
            "document_id": "doc-a",
            "table_ref": "table-3",
            "complete_table": False,
            "content_truncated": True,
        },
        resource_id="doc-a:table-3",
    )

    content, citations = bind_answer_citations(
        "预览结果 [[cite:doc-a/table-3]]。", (operation,)
    )

    assert content == "预览结果 。"
    assert citations == ()


def test_ignores_search_results_and_unknown_source_ids() -> None:
    operation = _operation(
        name="search_sources",
        data={
            "matches": [
                {
                    "document_id": "doc-a",
                    "source_ref": "methods",
                    "content": "preview",
                }
            ]
        },
        resource_id="doc-a:methods",
    )

    content, citations = bind_answer_citations(
        "候选结果 [[cite:doc-a/methods]]，未知结果 [[cite:doc-a/other]]。",
        (operation,),
    )

    assert content == "候选结果 ，未知结果 。"
    assert citations == ()

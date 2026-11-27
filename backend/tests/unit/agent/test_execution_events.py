from agent.application.execution_events import operation_activity
from agent.domain.models import Operation


def test_operation_activity_projects_source_result_without_raw_arguments():
    activity = operation_activity(
        Operation(
            operation_id="op-1",
            task_id="task-1",
            name="read_source",
            arguments_digest="a" * 64,
            status="succeeded",
            arguments={"document_id": "private-doc", "source_ref": "methods"},
            result={
                "status": "succeeded",
                "data": {
                    "document_title": "Paper A",
                    "heading_path": "Methods",
                    "page": 8,
                    "content": "The hold time was 30 minutes.",
                },
            },
        )
    )

    assert activity == {
        "summary": "Read Paper A · Methods · p. 8",
        "context": "Paper A · Methods · p. 8",
        "excerpt": "The hold time was 30 minutes.",
        "result_truncated": False,
    }


def test_operation_activity_marks_long_results_as_truncated():
    activity = operation_activity(
        Operation(
            operation_id="op-2",
            task_id="task-1",
            name="inspect_table",
            arguments_digest="b" * 64,
            status="succeeded",
            result={
                "status": "succeeded",
                "data": {
                    "table_ref": "table-3",
                    "content": "x" * 700,
                },
            },
        )
    )

    assert len(activity["excerpt"]) == 520
    assert activity["result_truncated"] is True

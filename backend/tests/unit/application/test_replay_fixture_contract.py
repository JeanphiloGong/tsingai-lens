import copy
import pytest

from scripts.evaluation.research_agent.run_scenarios import (
    SCIENTIFIC_SNAPSHOT_TABLES,
    database_url,
    validate_fixture,
)


def fixture():
    return {"scenarios": [{"id": f"S{i:02}", "collection_id": f"collection-{i}",
        "user_id": "u", "scientific_rubric": ["Check original data"],
        "turns": [{"message": "Inspect", "expected_statuses": ["completed"]}]} for i in range(1, 22)]}


def test_complete_fixture_requires_independent_scope_and_approved_actions():
    record = fixture()
    validate_fixture(record)
    invalid = copy.deepcopy(record)
    invalid["scenarios"][1]["collection_id"] = invalid["scenarios"][0]["collection_id"]
    with pytest.raises(ValueError, match="isolated collection"):
        validate_fixture(invalid)
    invalid = copy.deepcopy(record)
    invalid["scenarios"][0]["turns"][0]["approve"] = ["create_finding_version"]
    with pytest.raises(ValueError, match="approval action"):
        validate_fixture(invalid)
    invalid = copy.deepcopy(record)
    invalid["scenarios"][0]["automatic_actions"] = ["create_finding_version"]
    with pytest.raises(ValueError, match="approval scope"):
        validate_fixture(invalid)
    invalid = copy.deepcopy(record)
    invalid["scenarios"][0]["allowed_approval_actions"] = ["future_device_operation"]
    invalid["scenarios"][0]["automatic_actions"] = ["future_device_operation"]
    with pytest.raises(ValueError, match="session permissions"):
        validate_fixture(invalid)
    invalid = copy.deepcopy(record)
    invalid["scenarios"][0]["allowed_approval_actions"] = ["create_finding_version"]
    invalid["scenarios"][0]["turns"][0]["approve"] = [
        "create_finding_version", "create_finding_version",
    ]
    with pytest.raises(ValueError, match="unique"):
        validate_fixture(invalid)


def test_template_and_missing_scenarios_cannot_run():
    record = fixture()
    record["scenarios"][0]["user_id"] = "REPLACE_owner"
    with pytest.raises(ValueError, match="replace template"):
        validate_fixture(record)
    with pytest.raises(ValueError, match="exactly once"):
        validate_fixture({"scenarios": []})


def test_scientific_snapshot_covers_the_experiment_and_plan_contract():
    assert SCIENTIFIC_SNAPSHOT_TABLES == (
        "documents",
        "document_preparations",
        "collections",
        "research_objectives",
        "objective_analyses",
        "paper_experiment",
        "experimental_variant",
        "test_condition",
        "measurement_result",
        "experiment_comparison",
        "experiment_comparison_measurement",
        "reported_interpretation",
        "objective_experiment_selection",
        "selection_measurement",
        "selection_comparison",
        "comparison_group",
        "comparison_group_member",
        "finding",
        "finding_selection",
        "finding_comparison_group",
        "objective_experiment_plans",
        "finding_feedback_records",
        "finding_curation_records",
        "evaluation_gold_sets",
        "evaluation_prediction_snapshots",
        "evaluation_runs",
    )


@pytest.mark.parametrize("url", ["postgresql+psycopg://u@remote/test_test", "postgresql+psycopg://u@localhost/production", "sqlite:///local_test"])
def test_replay_refuses_nonisolated_database(monkeypatch, url):
    monkeypatch.setenv("LENS_TEST_DATABASE_URL", url)
    with pytest.raises(ValueError, match="localhost"):
        database_url()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["confirm", "auto"])
async def test_replay_uses_service_permission_and_exact_approval(mode):
    from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner, ToolSpec
    from application.chat.session_service import ChatSessionService
    from domain.chat import ToolRisk
    from scripts.evaluation.research_agent.run_scenarios import replay_case
    from tests.support.chat_repository import MemoryChatRepository
    from tests.unit.application.test_chat_session_service import _CollectionService, _SourceArtifactRepository, _WriteCapability, _Question
    from tests.unit.application.test_research_agent_runner import _Model
    write = _WriteCapability()
    write.spec = ToolSpec(name="record_finding_feedback", description="Save feedback", risk=ToolRisk.WRITE, input_model=_Question)
    repo = MemoryChatRepository()
    model = _Model(ModelTurn(tool_calls=(ModelToolCall(name=write.spec.name, arguments={"question": "Review"}),)),
                   ModelTurn(content="Saved"), ModelTurn(content="No tools needed."))
    service = ChatSessionService(repository=repo, collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(), runner=ResearchAgentRunner(
            model=model,
            capabilities=CapabilityRegistry((write,))))
    case = {"id": "S21", "collection_id": "col-1", "user_id": "user-1", "scientific_rubric": ["Check review"],
        "automatic_actions": [write.spec.name], "turns": [
            {"message": "Save feedback on this published Finding.", "approve": [write.spec.name],
             "required_tools": [write.spec.name], "expected_statuses": ["completed"]},
            {"message": "Explain what changed without using tools.", "expected_statuses": ["completed"],
             "no_tools": True, "no_writes": True},
            {"message": "Explain the saved review without using tools.", "new_session": True,
             "expected_statuses": ["completed"], "no_tools": True, "no_writes": True},
        ]}
    result = await replay_case(service, case, mode)
    assert result["failures"] == [], (
        [[(call.name, call.tool_call_id, call.status.value) for call in turn["calls"]]
         for turn in result["turns"]],
        [turn["response"] for turn in result["turns"]],
        model.tool_spec_names,
        len(model.turns),
    )
    assert len(write.executed) == 1
    calls = [call for call in repo.calls.values() if call.name == write.spec.name]
    assert [call.decision_basis for call in calls] == ["explicit" if mode == "confirm" else "scope_grant"]
    assert result["turns"][-1]["automatic_authorization_active"] is False
    assert result["scientific_review"] == "incomplete"


@pytest.mark.anyio
async def test_replay_records_session_setup_failure_without_aborting_batch():
    from scripts.evaluation.research_agent.run_scenarios import replay_case

    class MissingCollectionService:
        async def create_session(self, **_):
            raise FileNotFoundError("collection not found")

    case = {"id": "S01", "collection_id": "missing", "user_id": "user-1",
            "scientific_rubric": ["Check original data"], "turns": []}
    result = await replay_case(MissingCollectionService(), case, "confirm")
    assert result["technical_result"] == "failed"
    assert result["session_id"] is None
    assert result["failures"] == ["exception_type:FileNotFoundError"]

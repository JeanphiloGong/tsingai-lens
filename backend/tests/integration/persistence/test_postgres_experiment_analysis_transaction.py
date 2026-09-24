from __future__ import annotations

import pytest

from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision
from infra.persistence.postgres.experiment_analysis_transaction import (
    PostgresExperimentAnalysisTransactionFactory,
)
from infra.persistence.postgres.objective_experiment_selection_repository import (
    PostgresObjectiveExperimentSelectionRepository,
)
from infra.persistence.postgres.paper_experiment_repository import (
    PostgresPaperExperimentRepository,
)
from tests.integration.persistence.test_postgres_objectives import (
    COLLECTION_ID,
    OBJECTIVE_ID,
    _contribution,
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_objectives",)
pytestmark = pytest.mark.anyio


def _revision() -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": "experiment-transaction",
            "document_id": "doc_a",
            "experiment_version": 1,
            "source_fingerprint": "fingerprint-doc-a",
            "label": "Reported tensile series",
            "scope_description": "One reported tensile-strength condition.",
            "design_type": "observational",
            "identity_status": "identified",
            "binding_status": "bound",
            "variants": [
                {
                    "variant_key": "reported-condition",
                    "variant_label": "Reported condition",
                    "binding_status": "direct",
                }
            ],
            "test_conditions": [
                {
                    "test_key": "tensile",
                    "test_type": "tensile test",
                    "binding_status": "direct",
                }
            ],
            "measurements": [
                {
                    "measurement_key": "strength-a",
                    "variant_key": "reported-condition",
                    "test_key": "tensile",
                    "outcome": "tensile strength",
                    "value": 900,
                    "unit": "MPa",
                    "binding_status": "direct",
                }
            ],
        }
    )


def _selection(analysis_version: int) -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection(
        selection_id="selection-transaction",
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis_version,
        experiment_id="experiment-transaction",
        experiment_version=1,
        outcome="tensile strength",
        measurement_keys=("strength-a",),
    )


async def test_shared_transaction_rolls_back_graph_and_objective_publication(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    session_factory = objective_repository.session_factory
    experiments = PostgresPaperExperimentRepository(session_factory)
    selections = PostgresObjectiveExperimentSelectionRepository(session_factory)
    transaction_factory = PostgresExperimentAnalysisTransactionFactory(session_factory)
    revision = _revision()
    selection = _selection(analysis.analysis_version)

    with pytest.raises(RuntimeError, match="forced rollback"):
        async with transaction_factory.begin() as transaction:
            stored = await experiments.add_revision(
                revision,
                created_by="test-agent",
                transaction=transaction,
            )
            await selections.add_selection(
                COLLECTION_ID,
                selection,
                revision_id=stored.revision_id,
                transaction=transaction,
            )
            await objective_repository.publish_experiment_analysis(
                COLLECTION_ID,
                OBJECTIVE_ID,
                analysis.analysis_version,
                contributions=(
                    _contribution(analysis.analysis_version, "doc_a"),
                    _contribution(analysis.analysis_version, "doc_b"),
                ),
                transaction=transaction,
            )
            raise RuntimeError("forced rollback")

    assert await experiments.read_latest_revision(
        "experiment-transaction"
    ) is None
    assert await selections.list_selections(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()
    restored = await objective_repository.read_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    )
    assert restored is not None
    assert restored.status == "running"

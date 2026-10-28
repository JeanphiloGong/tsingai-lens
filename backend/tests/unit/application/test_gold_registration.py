"""Gold input rejection before any persistence operation."""
from __future__ import annotations

import pytest

from application.evaluation.gold_service import EvaluationGoldService
from repositories.evaluation_repository import EvaluationRepository
from tests.unit.services.test_evaluation_services import FakeCollectionService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("target_layer", ["invalid-layer", "", "CORE"])
async def test_gold_registration_rejects_unknown_target_before_persistence(target_layer):
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=EvaluationRepository(),
    )
    with pytest.raises(ValueError, match="unsupported evaluation target layer"):
        await service.register_gold_set(
            collection_id="col-gold", gold_id="gold-v1", target_layer=target_layer, items=(),
        )

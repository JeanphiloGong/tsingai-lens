"""
indexing api for graphrag
"""

import logging

from retrieval.config.enums import IndexingMethod
from retrieval.config.models.graph_rag_config import GraphRagConfig
from retrieval.index.run.utils import create_callback_chain
from retrieval.index.typing.pipeline_run_result import PipelineRunResult
from retrieval.index.workflows.factory import PipelineFactory

logger = logging.getLogger(__name__)


async def build_index(
        config: GraphRagConfig,
        method: IndexingMethod | str = IndexingMethod.Standard,
        ) -> list[PipelineRunResult]:
    outputs: list[PipelineRunResult] = []
    logger.info("Initializing indexing pipeline...")
    method = _get_method(method)
    pipeline = PipelineFactory.create_pipeline(config, method)
    return outputs

def _get_method(method: IndexingMethod | str) -> str:
    m = method.value if isinstance(method, IndexingMethod) else method
    return m

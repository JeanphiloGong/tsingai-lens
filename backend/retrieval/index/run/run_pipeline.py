"""
different methods to run the pipeline
"""

import json
import logging
import re
import time
from collections.abc import AsyncIterable
from dataclasses import asdict

from retrieval.config.models.graph_rag_config import GraphRagConfig
from retrieval.index.typing.pipeline import Pipeline
from retrieval.index.typing.pipeline_run_result import PipelineRunResult
from retrieval.utils.api import create_cache_from_config, create_storage_from_config

async def run_pipeline(
        pipeline: Pipeline,
        config: GraphRagConfig,
        ) -> AsyncIterable[PipelineRunResult]:
    """run all workflows using a simplified pipeline"""
    root_dir = config.root_dir

    input_storage = create_storage_from_config(config.input.storage)
    output_storage = create_storage_from_config(config.output)
    cache = create_cache_from_config(config.cache, root_dir)


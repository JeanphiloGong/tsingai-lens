import logging
import pandas as pd

from retrieval.config.models.input_config import InputConfig
from retrieval.index.input.factory import create_input
from retrieval.storage.pipeline_storage import PipelineStorage

logger = logging.getLogger(__name__)
async def load_input_documents(
        config: InputConfig, storage: PipelineStorage
        ) -> pd.DataFrame:
    """
    load and parse input documents into a standard format
    """
    return await create_input(config, storage)

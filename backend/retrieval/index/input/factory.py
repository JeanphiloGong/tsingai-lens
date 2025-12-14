import logging
import pandas as pd
from typing import Awaitable, Callable

from retrieval.config.enums import InputFileType
from retrieval.config.models.input_config import InputConfig
from retrieval.storage.pipeline_storage import PipelineStorage

logger = logging.getLogger(__name__)

loaders: dict[str, Callable[..., Awaitable[pd.DataFrame]]] = {
        InputFileType.text: load_text,
        InputFileType.csv: load_csv,
        InputFileType.json: load_json,
        }

async def create_input(
        config: InputConfig,
        storage: PipelineStorage,
        ) -> pd.DataFrame:
    """
    instance input data for a pipeline
    """
    if config.file_type in loaders:
        logger.info("loading input %s", config.file_type)
        loader = loaders[config.file_type]
        result = await loader(config, storage)

        # convert metadata columns to strings and collapse them into a json object
        if config.metadata:
            if all(col in result.columns for col in config.metadata):
                # collapse the metadata columns into a single json object column
                result["metadata"] = result[config.metadata].apply(
                        lambda row: row.to_dict(), axis=1
                        )
            else:
                value_error_msg = (
                        "one or more metadata columns not found in hte dataframe."
                        )
                raise ValueError(value_error_msg)

            result[config.metadata] = result[config.metadata].astype(str)

        return cast("pd.DataFrame", result)
    msg = f"unknown input type {config.file_type}"
    raise ValueError(msg)


import logging
from pathlib import Path
import pandas as pd


from retrieval.config.models.input_config import InputConfig
from retrieval.index.utils.hashing import gen_sha512_hash
from retrieval.storage.pipeline_storage import PipelineStorage

logger = logging.getLogger(__name__)


async def  load_text(
        config: InputConfig,
        storage: PipelineStorage,
        ) -> pd.DataFrame:
    """
    load text input from a directory
    """
    async def load_file(path: str, group: dict | None = None) -> pd.DataFrame:
        if group is None:
            group = {}
        text = await storage.get(path, encoding=config.encoding)
        new_item = {**group, "text": text}
        new_item["id"] = gen_sha512_hash(new_item, new_item.keys())
        new_item["title"] = str(Path(path).name)
        new_item["creation_date"] = await storage.get_creation_date(path)
        return pd.DataFrame([new_item])

    return await load_files(load_file, config, storage)


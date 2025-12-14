from pydantic import BaseModel, Field

from retrieval.config.enums import InputFileType
from retrieval.config.defaults import graphrag_config_defaults
import retrieval.config.defaults as defs
from retrieval.config.models.storage_config import StorageConfig


class InputConfig(BaseModel):
    """the default configuration section for input"""

    storage: StorageConfig = Field(
            description="the storage configuration to use for reading input documents.",
            default=StorageConfig(
                base_dir=graphrag_config_defaults.input.storage.base_dir,
                ),
            )

    # 管理输入文件的类型
    file_type: InputFileType = Field(
            description="the input file type to use",
            default=graphrag_config_defaults.input.file_type
            )

    encoding: str = Field(
            description="the input file encoding to use",
            default=defs.graphrag_config_defaults.input.encoding,
            )
    file_pattern: str = Field(
            description="the input file pattern to use.",
            default=graphrag_config_defaults.input.file_pattern,
            )

    metadata: list[str] | None = Field(
            description="the document attribute columns to use.",
            default=graphrag_config_defaults.input.metadata
            )


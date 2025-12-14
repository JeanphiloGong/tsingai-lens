"""
parameterization settings for the default configuration.
"""

from pathlib import Path
from pydantic import BaseModel, Field

from devtools import pformat

from retrieval.config.defaults import graphrag_config_defaults
from retrieval.config.models.input_config import InputConfig
import graphrag.config.defaults as defs
from retrieval.config.models.storage_config import StorageConfig

class GraphRagConfig(BaseModel):
    """
    base class for the default-configuration parameterization settings
    """

    def __repr__(self) -> str:
        """get a string representation"""
        return pformat(self, highlight=False)

    def __str__(self) -> str:
        """
        get a string representation
        """
        return self.model_dump_json(indent=4)

    workflows: list[str] | None = Field(
            description="list of workflows to run, in execution order. this always overrides any built-in workflow methods",
            default=graphrag_config_defaults.workflows,
            )
    """
    list of workflows to run, in execution order.
    """

    root_dir: str = Field(
            description="the root directory for the configuration",
            default_factory=graphrag_config_defaults.root_dir,
            )

    input: InputConfig = Field(
            description="the input configuration", default=InputConfig()
            )
    """the input configuration"""

    def _validate_input_pattern(self) -> None:
        """validate the input file pattern based on the spedified type."""
        if len(self.input.file_pattern) == 0:
            if self.input.file_type == defs.InputFileType.text:
                self.input.file_pattern = ".*\\.txt$"
            else:
                self.input.file_pattern = f".*\\.{self.input.file_type.value}$"

    def _validate_input_base_dir(self) -> None:
        """validate the input base directory."""
        if self.input.storage.type == defs.StorageType.file:
            if self.input.storage.base_dir.strip() == "":
                msg = "input storage bse directory is required for file input storage. Please rerun `graphrag init` and set the input storage configuration"
                raise ValueError(msg)
            self.input.storage.base_dir = str(
                    (Path(self.root_dir) / self.input.storage.base_dir).resolve()
                    )

    output: StorageConfig = Field(
            description="the output configuration.",
            default=StorageConfig(),
            )
    """the output configuration"""

    def _validate_output_base_dir(self) -> None:
        """validate the output base directory"""
        if self.output.type == defs.StorageType.file:
            if self.output.base_dir.strip() == "":
                msg = "output base directory is required for file output. please rerun `graphrag init` and set the output configuration"
                raise ValueError(msg)
            self.output.base_dir = str(
                    (Path(self.root_dir) / self.output.base_dir).resolve()
                    )




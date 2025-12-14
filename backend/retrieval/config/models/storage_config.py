from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from retrieval.config.enums import StorageType
from retrieval.config.defaults import graphrag_config_defaults


class StorageConfig(BaseModel):
    """
    the default configuration section for storage.
    """
    type: StorageType | str = Field(
            description="the storage type to use.",
            default=graphrag_config_defaults.storage.type,
            ) 
    base_dir: str = Field(
            description="the base directory for the output.",
            default=graphrag_config_defaults.storage.base_dir,
            )

    # validate the base dir for multiple OS
    # if not using a cloud storage type
    @field_validator("base_dir", mode="before")
    @classmethod
    def validate_base_dir(cls, value, info):
        """ensure that base_dir is a valid filesystem path when using local storge."""
        # info.data contains other field values, including "type"
        if info.data.get("type") != StorageType.file:
            return value
        return str(Path(value))

    connection_string: str | None = Field(
            description="the storage connection string to use",
            default=graphrag_config_defaults.storage.connection_string,
            )
    container_name: str | None = Field(
            description="the storage container name to use",
            default=graphrag_config_defaults.storage.container_name,
            )
    storage_account_blob_url: str | None = Field(
            description="the storage account blob url to use.",
            default=graphrag_config_defaults.storage.storage_account_blob_url,
            )
    cosmosdb_account_url: str | None = Field(
            description="The cosmosdb account url to use.",
            default=graphrag_config_defaults.storage.cosmosdb_account_url,
            )




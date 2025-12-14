from abc import ABCMeta, abstractmethod
from typing import Any


class PipelineStorage(metaclass=ABCMeta):
    """
    provide a storage interface for the pipeline. this is where the pipeline will store its output data
    """
    # 为什么这里是一个空的方法呢
    @abstractmethod
    async def get(
            self, key: str, as_bytes: bool | None = None, encoding: str | None = None}
    ) -> Any:
        """
        get the value for the given key

        Args:
            - key - the key to get the value for.
            - as_bytes - Whether or not tot return the value as bytes.

        Returns:
        ----
            - output - The value for the given key.
        """
        ...

    @abstractmethod
    async def get_creation_date(self, key: str) -> str:
        """
        get the creation date for the given key.

        Args:
            -key - the key to get the creation date for .
        Returns:
            - output - the creation date for the given key.
        """

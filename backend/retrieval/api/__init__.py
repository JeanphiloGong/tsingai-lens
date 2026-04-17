# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""API for GraphRAG.

WARNING: This API is under development and may undergo changes in future releases.
Backwards compatibility is not guaranteed at this time.
"""

from retrieval.api.index import build_index
from retrieval.api.prompt_tune import generate_indexing_prompts
from retrieval.prompt_tune.types import DocSelectionType

__all__ = [  # noqa: RUF022
    # index API
    "build_index",
    # prompt tuning API
    "DocSelectionType",
    "generate_indexing_prompts",
]

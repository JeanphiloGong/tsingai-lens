# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Source runtime logging configuration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from utils.logger import setup_logger

if TYPE_CHECKING:
    from infra.source.config.source_runtime_config import GraphRagConfig


def init_runtime_loggers(
    config: "GraphRagConfig",
    verbose: bool = False,
    filename: str = "indexing-engine.log",
) -> None:
    """Route Source runtime logging into the application logging system."""
    _ = config
    _ = filename
    log_level = logging.DEBUG if verbose else logging.INFO
    setup_logger("infra.source")

    for logger_name in ("infra.source", "retrieval", "graphrag"):
        namespace_logger = logging.getLogger(logger_name)
        if namespace_logger.hasHandlers():
            for handler in list(namespace_logger.handlers):
                if isinstance(handler, logging.FileHandler):
                    handler.close()
            namespace_logger.handlers.clear()
        namespace_logger.setLevel(log_level)
        namespace_logger.propagate = True

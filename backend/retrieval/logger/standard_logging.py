# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Standard logging configuration for the graphrag package.

This module provides a standardized way to configure Python's built-in
logging system for use within the graphrag package.

Usage:
    # Configuration should be done once at the start of your application:
    from retrieval.logger.standard_logging import init_loggers
    init_loggers(config)

    # Then throughout your code:
    import logging
    logger = logging.getLogger(__name__)  # Use standard logging

    # Use standard logging methods:
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical error message")

Notes
-----
    The logging system is hierarchical. Loggers are organized in a tree structure,
    with the root logger named 'graphrag'. All loggers created with names starting
    with 'retrieval.' will be children of this root logger. This allows for consistent
    configuration of all graphrag-related logs throughout the application.

    All progress logging now uses this standard logging system for consistency.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from utils.logger import setup_logger

if TYPE_CHECKING:
    from infra.source.config.source_runtime_config import GraphRagConfig

DEFAULT_LOG_FILENAME = "indexing-engine.log"


def init_loggers(
    config: GraphRagConfig,
    verbose: bool = False,
    filename: str = DEFAULT_LOG_FILENAME,
) -> None:
    """Route retrieval logging into the application logging system.

    Parameters
    ----------
    config : GraphRagConfig | None, default=None
        The GraphRAG configuration. Kept for API compatibility.
    verbose : bool, default=False
        Whether to enable verbose (DEBUG) logging for retrieval namespaces.
    filename : Optional[str]
        Kept for API compatibility. Retrieval no longer manages a separate file.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    setup_logger("retrieval")

    for logger_name in ("retrieval", "graphrag"):
        namespace_logger = logging.getLogger(logger_name)
        if namespace_logger.hasHandlers():
            for handler in list(namespace_logger.handlers):
                if isinstance(handler, logging.FileHandler):
                    handler.close()
            namespace_logger.handlers.clear()
        namespace_logger.setLevel(log_level)
        namespace_logger.propagate = True

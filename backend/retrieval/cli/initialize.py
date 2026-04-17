# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""CLI implementation of the initialization subcommand."""

import logging
from pathlib import Path

from retrieval.config.init_content import INIT_DOTENV, INIT_YAML
from retrieval.prompts.index.community_report import (
    COMMUNITY_REPORT_PROMPT,
)
from retrieval.prompts.index.community_report_text_units import (
    COMMUNITY_REPORT_TEXT_PROMPT,
)
from retrieval.prompts.index.extract_claims import EXTRACT_CLAIMS_PROMPT
from retrieval.prompts.index.extract_graph import GRAPH_EXTRACTION_PROMPT
from retrieval.prompts.index.summarize_descriptions import SUMMARIZE_PROMPT

logger = logging.getLogger(__name__)


def initialize_project_at(path: Path, force: bool) -> None:
    """
    Initialize the project at the given path.

    Parameters
    ----------
    path : Path
        The path at which to initialize the project.
    force : bool
        Whether to force initialization even if the project already exists.

    Raises
    ------
    ValueError
        If the project already exists and force is False.
    """
    logger.info("Initializing project at %s", path)
    root = Path(path)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)

    settings_yaml = root / "settings.yaml"
    if settings_yaml.exists() and not force:
        msg = f"Project already initialized at {root}"
        raise ValueError(msg)

    with settings_yaml.open("wb") as file:
        file.write(INIT_YAML.encode(encoding="utf-8", errors="strict"))

    dotenv = root / ".env"
    if not dotenv.exists() or force:
        with dotenv.open("wb") as file:
            file.write(INIT_DOTENV.encode(encoding="utf-8", errors="strict"))

    prompts_dir = root / "prompts"
    if not prompts_dir.exists():
        prompts_dir.mkdir(parents=True, exist_ok=True)

    prompts = {
        "extract_graph": GRAPH_EXTRACTION_PROMPT,
        "summarize_descriptions": SUMMARIZE_PROMPT,
        "extract_claims": EXTRACT_CLAIMS_PROMPT,
        "community_report_graph": COMMUNITY_REPORT_PROMPT,
        "community_report_text": COMMUNITY_REPORT_TEXT_PROMPT,
    }

    for name, content in prompts.items():
        prompt_file = prompts_dir / f"{name}.txt"
        if not prompt_file.exists() or force:
            with prompt_file.open("wb") as file:
                file.write(content.encode(encoding="utf-8", errors="strict"))

# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License


"""A package containing all built-in workflow definitions."""

from infra.source.runtime.workflows.factory import PipelineFactory

from .create_base_text_units import (
    run_workflow as run_create_base_text_units,
)
from .create_final_documents import (
    run_workflow as run_create_final_documents,
)
from .create_final_text_units import (
    run_workflow as run_create_final_text_units,
)
from .create_sections import (
    run_workflow as run_create_sections,
)
from .create_table_cells import (
    run_workflow as run_create_table_cells,
)
from .create_source_artifacts import (
    run_workflow as run_create_source_artifacts,
)
from .load_input_documents import (
    run_workflow as run_load_input_documents,
)

# register all of our built-in workflows at once
PipelineFactory.register_all({
    "load_input_documents": run_load_input_documents,
    "create_base_text_units": run_create_base_text_units,
    "create_final_documents": run_create_final_documents,
    "create_final_text_units": run_create_final_text_units,
    "create_sections": run_create_sections,
    "create_table_cells": run_create_table_cells,
    "create_source_artifacts": run_create_source_artifacts,
})

"""Compatibility alias for indexing task orchestration."""

import sys

from application import index_task_runner as _impl

sys.modules[__name__] = _impl

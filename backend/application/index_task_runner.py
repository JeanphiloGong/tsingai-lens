"""Compatibility shim for indexing task orchestration."""

import sys

import application.indexing.index_task_runner as _impl

sys.modules[__name__] = _impl

"""Compatibility shim for the indexing task service."""

import sys

import application.indexing.task_service as _impl

sys.modules[__name__] = _impl

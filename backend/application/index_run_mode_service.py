"""Compatibility shim for indexing run-mode helpers."""

import sys

import application.indexing.run_mode_service as _impl

sys.modules[__name__] = _impl

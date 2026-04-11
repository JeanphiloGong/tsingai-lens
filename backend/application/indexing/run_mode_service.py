"""Compatibility alias for indexing run-mode helpers."""

import sys

from application import index_run_mode_service as _impl

sys.modules[__name__] = _impl

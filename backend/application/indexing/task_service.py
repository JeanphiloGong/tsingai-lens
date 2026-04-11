"""Compatibility alias for task persistence helpers."""

import sys

from application import task_service as _impl

sys.modules[__name__] = _impl

"""Compatibility alias for report application services."""

import sys

from application import report_service as _impl

sys.modules[__name__] = _impl

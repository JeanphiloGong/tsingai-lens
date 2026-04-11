"""Compatibility alias for graph application services."""

import sys

from application import graph_service as _impl

sys.modules[__name__] = _impl

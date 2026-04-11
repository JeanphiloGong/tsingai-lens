"""Compatibility alias for query application services."""

import sys

from application import query_service as _impl

sys.modules[__name__] = _impl

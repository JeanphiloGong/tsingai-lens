"""Compatibility alias for protocol search."""

import sys

from application import protocol_search_service as _impl

sys.modules[__name__] = _impl

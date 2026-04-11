"""Compatibility alias for protocol extraction."""

import sys

from application import protocol_extract_service as _impl

sys.modules[__name__] = _impl

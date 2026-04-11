"""Compatibility alias for protocol normalization."""

import sys

from application import protocol_normalize_service as _impl

sys.modules[__name__] = _impl

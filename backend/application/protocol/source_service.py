"""Compatibility alias for protocol source loading."""

import sys

from application import protocol_source_service as _impl

sys.modules[__name__] = _impl

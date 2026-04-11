"""Compatibility alias for protocol block parsing."""

import sys

from application import protocol_block_service as _impl

sys.modules[__name__] = _impl

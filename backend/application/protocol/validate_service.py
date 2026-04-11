"""Compatibility alias for protocol validation."""

import sys

from application import protocol_validate_service as _impl

sys.modules[__name__] = _impl

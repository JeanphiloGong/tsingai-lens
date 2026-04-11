"""Compatibility alias for protocol SOP helpers."""

import sys

from application import protocol_sop_service as _impl

sys.modules[__name__] = _impl

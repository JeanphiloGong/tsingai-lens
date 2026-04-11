"""Compatibility alias for protocol section parsing."""

import sys

from application import protocol_section_service as _impl

sys.modules[__name__] = _impl

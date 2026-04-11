"""Compatibility alias for protocol pipeline orchestration."""

import sys

from application import protocol_pipeline_service as _impl

sys.modules[__name__] = _impl

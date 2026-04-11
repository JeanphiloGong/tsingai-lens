"""Compatibility alias for workspace assembly."""

import sys

from application import workspace_service as _impl

sys.modules[__name__] = _impl

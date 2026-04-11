"""Compatibility alias for workspace artifact registry access."""

import sys

from application import artifact_registry_service as _impl

sys.modules[__name__] = _impl

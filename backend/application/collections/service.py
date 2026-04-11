"""Compatibility alias for the collection-domain service."""

import sys

from application import collection_service as _impl

sys.modules[__name__] = _impl

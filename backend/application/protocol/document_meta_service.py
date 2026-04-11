"""Compatibility alias for protocol document metadata helpers."""

import sys

from application import protocol_document_meta_service as _impl

sys.modules[__name__] = _impl

"""Compatibility shim for protocol extraction."""

import sys

import application.protocol.extract_service as _impl

sys.modules[__name__] = _impl

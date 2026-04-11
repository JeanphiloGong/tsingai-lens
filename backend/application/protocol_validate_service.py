"""Compatibility shim for protocol validation."""

import sys

import application.protocol.validate_service as _impl

sys.modules[__name__] = _impl

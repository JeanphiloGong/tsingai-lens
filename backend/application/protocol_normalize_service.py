"""Compatibility shim for protocol normalization."""

import sys

import application.protocol.normalize_service as _impl

sys.modules[__name__] = _impl

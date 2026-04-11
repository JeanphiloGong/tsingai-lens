"""Compatibility shim for protocol source loading."""

import sys

import application.protocol.source_service as _impl

sys.modules[__name__] = _impl

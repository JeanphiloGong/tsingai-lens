"""Compatibility shim for protocol search."""

import sys

import application.protocol.search_service as _impl

sys.modules[__name__] = _impl

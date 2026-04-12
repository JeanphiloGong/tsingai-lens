"""Compatibility shim for protocol SOP helpers."""

import sys

import application.protocol.sop_service as _impl

sys.modules[__name__] = _impl

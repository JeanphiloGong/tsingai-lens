"""Compatibility shim for protocol section parsing."""

import sys

import application.protocol.section_service as _impl

sys.modules[__name__] = _impl

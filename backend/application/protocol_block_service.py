"""Compatibility shim for protocol block parsing."""

import sys

import application.protocol.block_service as _impl

sys.modules[__name__] = _impl

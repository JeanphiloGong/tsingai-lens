"""Compatibility shim for protocol pipeline orchestration."""

import sys

import application.protocol.pipeline_service as _impl

sys.modules[__name__] = _impl

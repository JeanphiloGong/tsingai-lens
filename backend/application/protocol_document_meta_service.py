"""Compatibility shim for protocol document metadata helpers."""

import sys

import application.protocol.document_meta_service as _impl

sys.modules[__name__] = _impl

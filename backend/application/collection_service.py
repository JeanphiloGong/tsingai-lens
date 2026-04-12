"""Compatibility shim for the collection-domain service."""

import sys

import application.collections.service as _impl

sys.modules[__name__] = _impl

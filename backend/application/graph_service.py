"""Compatibility shim for graph application services."""

import sys

import application.graph.service as _impl

sys.modules[__name__] = _impl

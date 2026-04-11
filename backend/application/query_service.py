"""Compatibility shim for query application services."""

import sys

import application.query.service as _impl

sys.modules[__name__] = _impl

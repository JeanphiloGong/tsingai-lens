"""Compatibility shim for report application services."""

import sys

import application.reports.service as _impl

sys.modules[__name__] = _impl

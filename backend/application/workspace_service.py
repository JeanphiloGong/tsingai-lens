"""Compatibility shim for workspace assembly."""

import sys

import application.workspace.service as _impl

sys.modules[__name__] = _impl

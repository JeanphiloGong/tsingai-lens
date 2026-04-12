"""Compatibility shim for workspace artifact registry access."""

import sys

import application.workspace.artifact_registry_service as _impl

sys.modules[__name__] = _impl

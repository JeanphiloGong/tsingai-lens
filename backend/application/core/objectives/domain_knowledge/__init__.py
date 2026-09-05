"""Versioned, recall-only domain vocabulary for research-objective tooling.

The registry helps the system find likely aliases in noisy paper metadata. It
is deliberately not a scientific authority: source-local evidence and the
axis-equivalence review still decide whether two observations can be joined.
"""

from application.core.objectives.domain_knowledge.registry import (
    MaterialMatch,
    MaterialMatchQuality,
    material_identity_key,
    material_match,
    material_registry_version,
    material_text_mentions,
)

__all__ = [
    "MaterialMatch",
    "MaterialMatchQuality",
    "material_identity_key",
    "material_match",
    "material_registry_version",
    "material_text_mentions",
]

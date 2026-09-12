"""Compatibility exports for extraction code.

The shared contractual normalizers live at package root so the Comparison
Engine can use them without importing extraction/ingestion/PDF dependencies.
"""

from vitaguard_do.contractual_normalization import (
    canonicalize_contractual_field,
    canonicalize_coverage_trigger,
    canonicalize_geographic_scope,
    canonicalize_jurisdiction,
)

__all__ = [
    "canonicalize_contractual_field",
    "canonicalize_coverage_trigger",
    "canonicalize_geographic_scope",
    "canonicalize_jurisdiction",
]

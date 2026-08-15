"""AI-assisted sample data generation for JSON Schema and XML Schema."""

from .models import (
    GenerationAttempt,
    GenerationResult,
    SchemaKind,
    ValidationIssue,
    ValidationReport,
)

__all__ = [
    "GenerationAttempt",
    "GenerationResult",
    "SchemaKind",
    "ValidationIssue",
    "ValidationReport",
    "__version__",
]

__version__ = "0.1.0"

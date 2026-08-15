"""Core data types shared by the validators, the generator and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SchemaKind(str, Enum):
    """The two schema languages supported by the editor."""

    JSON_SCHEMA = "json-schema"
    XML_SCHEMA = "xml-schema"

    @property
    def data_format(self) -> str:
        return "JSON" if self is SchemaKind.JSON_SCHEMA else "XML"


@dataclass(frozen=True)
class ValidationIssue:
    """A single schema violation, located as precisely as the validator allows."""

    message: str
    location: str = ""
    line: int | None = None

    def describe(self) -> str:
        prefix = self.location or "<document>"
        if self.line is not None:
            prefix = f"{prefix} (line {self.line})"
        return f"{prefix}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating a document against a schema."""

    issues: tuple[ValidationIssue, ...] = ()
    schema_error: str | None = None
    parse_error: str | None = None

    @property
    def is_valid(self) -> bool:
        return not self.issues and self.schema_error is None and self.parse_error is None

    def as_feedback(self, limit: int = 20) -> str:
        """Render the report as instructions an LLM can act on."""
        if self.schema_error is not None:
            return f"The schema itself could not be loaded: {self.schema_error}"
        if self.parse_error is not None:
            return f"The document is not well-formed: {self.parse_error}"
        lines = [issue.describe() for issue in self.issues[:limit]]
        if len(self.issues) > limit:
            lines.append(f"... and {len(self.issues) - limit} more violation(s)")
        return "\n".join(f"- {line}" for line in lines)


@dataclass
class GenerationAttempt:
    """One round trip to the model, together with the validation verdict."""

    index: int
    document: str
    report: ValidationReport
    raw_response: str = ""

    @property
    def is_valid(self) -> bool:
        return self.report.is_valid


@dataclass
class GenerationResult:
    """The full history of a generation run; ``document`` is only set when valid."""

    attempts: list[GenerationAttempt] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].is_valid

    @property
    def document(self) -> str | None:
        return self.attempts[-1].document if self.succeeded else None

    @property
    def last_report(self) -> ValidationReport | None:
        return self.attempts[-1].report if self.attempts else None

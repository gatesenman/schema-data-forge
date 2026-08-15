"""Schema validation for JSON Schema and XML Schema (XSD) documents."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import xmlschema
from jsonschema import Draft202012Validator, validators
from xmlschema.validators.exceptions import XMLSchemaValidationError

from .models import SchemaKind, ValidationIssue, ValidationReport

_MAX_ISSUES = 200


def _json_pointer(error: jsonschema.ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    parts = ["$"]
    for token in error.absolute_path:
        parts.append(f"[{token}]" if isinstance(token, int) else f".{token}")
    return "".join(parts)


def validate_json(document: str, schema_text: str) -> ValidationReport:
    """Validate a JSON document against a JSON Schema, both given as text."""
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        return ValidationReport(schema_error=f"schema is not valid JSON: {exc}")

    validator_cls = validators.validator_for(schema, default=Draft202012Validator)
    try:
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        return ValidationReport(schema_error=str(exc))

    try:
        instance = json.loads(document)
    except json.JSONDecodeError as exc:
        return ValidationReport(parse_error=f"not valid JSON: {exc}")

    validator = validator_cls(schema)
    issues = [
        ValidationIssue(message=error.message, location=_json_pointer(error))
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]
    return ValidationReport(issues=tuple(issues[:_MAX_ISSUES]))


def _xml_location(error: XMLSchemaValidationError) -> str:
    path = getattr(error, "path", None)
    if path:
        return str(path)
    elem = getattr(error, "elem", None)
    return str(getattr(elem, "tag", "")) if elem is not None else ""


def _xml_issue(error: XMLSchemaValidationError) -> ValidationIssue:
    reason = error.reason or str(error)
    line = getattr(getattr(error, "elem", None), "sourceline", None)
    return ValidationIssue(message=str(reason).strip(), location=_xml_location(error), line=line)


def load_xml_schema(schema_text: str) -> xmlschema.XMLSchema:
    """Compile an XSD from text. Raises ``xmlschema.XMLSchemaException`` when invalid."""
    return xmlschema.XMLSchema(schema_text)


def validate_xml(document: str, schema_text: str) -> ValidationReport:
    """Validate an XML document against an XSD, both given as text."""
    try:
        schema = load_xml_schema(schema_text)
    except Exception as exc:  # noqa: BLE001 - xmlschema raises a wide family of errors
        return ValidationReport(schema_error=f"XSD could not be compiled: {exc}")

    issues: list[ValidationIssue] = []
    try:
        for error in schema.iter_errors(document.strip()):
            issues.append(_xml_issue(error))
            if len(issues) >= _MAX_ISSUES:
                break
    except Exception as exc:  # noqa: BLE001 - malformed XML surfaces as a parse error
        return ValidationReport(parse_error=f"not well-formed XML: {exc}")

    return ValidationReport(issues=tuple(issues))


def validate(document: str, schema_text: str, kind: SchemaKind) -> ValidationReport:
    """Validate ``document`` against ``schema_text`` using the matching schema language."""
    if kind is SchemaKind.JSON_SCHEMA:
        return validate_json(document, schema_text)
    return validate_xml(document, schema_text)


def detect_schema_kind(schema_text: str) -> SchemaKind:
    """Guess the schema language of ``schema_text`` from its first meaningful characters."""
    stripped = schema_text.lstrip()
    if stripped.startswith("<"):
        return SchemaKind.XML_SCHEMA
    return SchemaKind.JSON_SCHEMA


def xsd_root_elements(schema_text: str) -> list[str]:
    """Return the global element names declared by an XSD, best effort."""
    try:
        schema = load_xml_schema(schema_text)
    except Exception:  # noqa: BLE001 - callers only need a best-effort hint
        return []
    return [str(name) for name in schema.elements]


def xsd_target_namespace(schema_text: str) -> str:
    """Return the target namespace of an XSD, or an empty string when unavailable."""
    try:
        schema = load_xml_schema(schema_text)
    except Exception:  # noqa: BLE001 - callers only need a best-effort hint
        return ""
    return schema.target_namespace or ""


def format_document(document: str, kind: SchemaKind) -> str:
    """Pretty-print a document, returning it unchanged when it cannot be parsed."""
    if kind is SchemaKind.JSON_SCHEMA:
        try:
            parsed: Any = json.loads(document)
        except json.JSONDecodeError:
            return document
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    from xml.dom import minidom

    try:
        pretty = minidom.parseString(document.strip()).toprettyxml(indent="  ")
    except Exception:  # noqa: BLE001 - keep the original text for the error panel
        return document
    return "\n".join(line for line in pretty.splitlines() if line.strip())

"""Schema validation for JSON Schema and XML Schema (XSD) documents."""

from __future__ import annotations

import contextlib
import json
from typing import Any
from xml.parsers import expat

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


JsonPath = tuple[str | int, ...]


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _skip_string(text: str, i: int) -> int:
    i += 1
    while text[i] != '"':
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _skip_scalar(text: str, i: int) -> int:
    while i < len(text) and text[i] not in ",]} \t\r\n":
        i += 1
    return i


def _scan_value(text: str, i: int, path: JsonPath, out: dict[JsonPath, int]) -> int:
    out.setdefault(path, i)
    char = text[i]
    if char == "{":
        i = _skip_ws(text, i + 1)
        while text[i] != "}":
            key_end = _skip_string(text, i)
            key = str(json.loads(text[i:key_end]))
            i = _skip_ws(text, _skip_ws(text, key_end) + 1)
            i = _skip_ws(text, _scan_value(text, i, (*path, key), out))
            if text[i] == ",":
                i = _skip_ws(text, i + 1)
        return i + 1
    if char == "[":
        i = _skip_ws(text, i + 1)
        index = 0
        while text[i] != "]":
            i = _skip_ws(text, _scan_value(text, i, (*path, index), out))
            index += 1
            if text[i] == ",":
                i = _skip_ws(text, i + 1)
        return i + 1
    if char == '"':
        return _skip_string(text, i)
    return _skip_scalar(text, i)


def json_line_map(document: str) -> dict[JsonPath, int]:
    """Map every JSON path in ``document`` to the 1-based line where its value starts."""
    if not document.strip():
        return {}
    offsets: dict[JsonPath, int] = {}
    # A partial map is still useful for the error panel when the document is malformed.
    with contextlib.suppress(IndexError, ValueError, RecursionError):
        _scan_value(document, _skip_ws(document, 0), (), offsets)
    return {path: document.count("\n", 0, offset) + 1 for path, offset in offsets.items()}


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
    lines = json_line_map(document)
    issues = [
        ValidationIssue(
            message=error.message,
            location=_json_pointer(error),
            line=lines.get(tuple(error.absolute_path)),
        )
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]
    return ValidationReport(issues=tuple(issues[:_MAX_ISSUES]))


def _xml_location(error: XMLSchemaValidationError) -> str:
    path = getattr(error, "path", None)
    if path:
        return str(path)
    elem = getattr(error, "elem", None)
    return str(getattr(elem, "tag", "")) if elem is not None else ""


def _normalize_xml_path(path: str) -> str:
    """Rewrite an XPath-like location into ``/local[n]/local[n]`` form for line lookups."""
    segments = []
    for raw in path.strip("/").split("/"):
        name = raw.split(":")[-1]
        if not name or name.startswith("@"):
            continue
        segments.append(name if name.endswith("]") else f"{name}[1]")
    return "/" + "/".join(segments)


def xml_line_map(document: str) -> dict[str, int]:
    """Map every element path in ``document`` to the 1-based line of its start tag."""
    lines: dict[str, int] = {}
    stack: list[str] = []
    counts: list[dict[str, int]] = [{}]
    skipped = document.count("\n", 0, len(document) - len(document.lstrip()))
    parser = expat.ParserCreate()

    def start_element(name: str, attrs: dict[str, str]) -> None:
        local = name.split(":")[-1]
        counter = counts[-1]
        counter[local] = counter.get(local, 0) + 1
        stack.append(f"{local}[{counter[local]}]")
        counts.append({})
        lines["/" + "/".join(stack)] = parser.CurrentLineNumber + skipped

    def end_element(name: str) -> None:
        stack.pop()
        counts.pop()

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    with contextlib.suppress(expat.ExpatError):
        parser.Parse(document.strip(), True)
    return lines


def _xml_issue(error: XMLSchemaValidationError, lines: dict[str, int]) -> ValidationIssue:
    reason = error.reason or str(error)
    location = _xml_location(error)
    line = getattr(getattr(error, "elem", None), "sourceline", None)
    if line is None and location:
        line = lines.get(_normalize_xml_path(location))
    return ValidationIssue(message=str(reason).strip(), location=location, line=line)


def load_xml_schema(schema_text: str) -> xmlschema.XMLSchema:
    """Compile an XSD from text. Raises ``xmlschema.XMLSchemaException`` when invalid."""
    return xmlschema.XMLSchema(schema_text)


def validate_xml(document: str, schema_text: str) -> ValidationReport:
    """Validate an XML document against an XSD, both given as text."""
    try:
        schema = load_xml_schema(schema_text)
    except Exception as exc:  # noqa: BLE001 - xmlschema raises a wide family of errors
        return ValidationReport(schema_error=f"XSD could not be compiled: {exc}")

    lines = xml_line_map(document)
    issues: list[ValidationIssue] = []
    try:
        for error in schema.iter_errors(document.strip()):
            issues.append(_xml_issue(error, lines))
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

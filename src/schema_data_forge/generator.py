"""Generate sample data with an LLM and keep repairing it until the schema accepts it."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .llm import LLMClient, LLMError, Message
from .models import (
    GenerationAttempt,
    GenerationResult,
    SchemaKind,
    ValidationReport,
)
from .validation import format_document, validate, xsd_root_elements, xsd_target_namespace

DEFAULT_MAX_ATTEMPTS = 4

_JSON_ENVELOPE_KEY = "data"
_XML_ENVELOPE_KEY = "xml"

_SYSTEM_PROMPT = """You are a data engineer that produces realistic sample data for a given \
schema. You always answer with a single JSON object and nothing else.

Hard requirements:
- The sample data MUST validate against the schema with zero violations.
- Honour every constraint: required fields, types, enumerations, patterns, numeric and length \
bounds, cardinalities, uniqueness/key constraints and namespaces.
- Never invent fields, elements or attributes that the schema does not allow.
- Use plausible, human-readable business values instead of placeholders such as "string" or \
"foo", and keep values consistent with each other.
"""

_JSON_FORMAT_RULES = f"""Answer with a JSON object of the form:
{{"{_JSON_ENVELOPE_KEY}": <the sample instance>}}
The value of "{_JSON_ENVELOPE_KEY}" is the JSON instance described by the schema."""

_XML_FORMAT_RULES = f"""Answer with a JSON object of the form:
{{"{_XML_ENVELOPE_KEY}": "<the sample XML document as a string>"}}
The XML document must be well-formed, must declare every namespace it uses and must start with \
a global element declared by the XSD. Do not include an XML declaration comment or markdown \
fences inside the string."""


class GenerationError(RuntimeError):
    """Raised when the model output cannot be turned into a candidate document at all."""


@dataclass(frozen=True)
class GenerationRequest:
    """Everything needed for one generation run."""

    schema_text: str
    kind: SchemaKind
    instructions: str = ""
    root_element: str = ""
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def format_rules(self) -> str:
        return _JSON_FORMAT_RULES if self.kind is SchemaKind.JSON_SCHEMA else _XML_FORMAT_RULES


ProgressCallback = Callable[[GenerationAttempt], None]


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_document(raw: str, kind: SchemaKind) -> str:
    """Pull the candidate document out of the model's JSON envelope."""
    text = _strip_fences(raw)
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        if kind is SchemaKind.XML_SCHEMA and text.startswith("<"):
            return text
        raise GenerationError(f"model output is not valid JSON: {exc}") from exc

    if kind is SchemaKind.XML_SCHEMA:
        if isinstance(envelope, dict):
            for key in (_XML_ENVELOPE_KEY, "document", "xmlDocument", "content"):
                value = envelope.get(key)
                if isinstance(value, str) and value.strip():
                    return _strip_fences(value)
        raise GenerationError(f'model output has no "{_XML_ENVELOPE_KEY}" string field')

    if isinstance(envelope, dict) and _JSON_ENVELOPE_KEY in envelope:
        instance = envelope[_JSON_ENVELOPE_KEY]
    else:
        instance = envelope
    return json.dumps(instance, indent=2, ensure_ascii=False)


def build_initial_messages(request: GenerationRequest) -> list[Message]:
    """Build the first prompt for a generation run."""
    lines = [
        f"Generate one sample {request.kind.data_format} document for the "
        f"{'JSON Schema' if request.kind is SchemaKind.JSON_SCHEMA else 'XML Schema (XSD)'} below.",
        "",
        "### Schema",
        "```",
        request.schema_text.strip(),
        "```",
    ]

    if request.kind is SchemaKind.XML_SCHEMA:
        root = request.root_element or ""
        if not root:
            candidates = xsd_root_elements(request.schema_text)
            root = candidates[0] if len(candidates) == 1 else ""
        if root:
            lines += ["", f"Use `{root}` as the root element."]
        namespace = xsd_target_namespace(request.schema_text)
        if namespace:
            lines += [
                f"Every element must be in the target namespace `{namespace}`; declare it as the "
                "default namespace on the root element."
            ]

    if request.instructions.strip():
        lines += ["", "### Additional requirements", request.instructions.strip()]

    lines += ["", "### Output format", request.format_rules()]
    return [Message("system", _SYSTEM_PROMPT), Message("user", "\n".join(lines))]


def build_repair_message(report: ValidationReport, kind: SchemaKind) -> Message:
    """Turn a validation report into a repair instruction for the next attempt."""
    body = (
        f"The document you produced does not validate. The {kind.data_format} validator "
        "reported:\n\n"
        f"{report.as_feedback()}\n\n"
        "Fix every issue and return the complete corrected document in the same JSON envelope. "
        "Do not explain the changes and do not repeat the schema."
    )
    return Message("user", body)


class SampleDataGenerator:
    """Drives the generate -> validate -> repair loop."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def generate(
        self,
        request: GenerationRequest,
        on_attempt: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        """Generate a document that validates, or return the failed attempt history."""
        messages = build_initial_messages(request)
        result = GenerationResult()
        max_attempts = max(1, request.max_attempts)

        for index in range(1, max_attempts + 1):
            if should_cancel is not None and should_cancel():
                break

            raw = self._client.complete_json(messages)
            try:
                document = extract_document(raw, request.kind)
            except GenerationError as exc:
                report = ValidationReport(parse_error=str(exc))
                attempt = GenerationAttempt(index, "", report, raw_response=raw)
            else:
                report = validate(document, request.schema_text, request.kind)
                attempt = GenerationAttempt(
                    index,
                    format_document(document, request.kind) if report.is_valid else document,
                    report,
                    raw_response=raw,
                )

            result.attempts.append(attempt)
            if on_attempt is not None:
                on_attempt(attempt)
            if attempt.is_valid:
                break
            if report.schema_error is not None:
                break

            messages = [
                *messages,
                Message("assistant", raw),
                build_repair_message(report, request.kind),
            ]

        return result


def generate_sample(
    schema_text: str,
    kind: SchemaKind | None = None,
    *,
    client: LLMClient | None = None,
    instructions: str = "",
    root_element: str = "",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    on_attempt: ProgressCallback | None = None,
) -> GenerationResult:
    """Convenience wrapper around :class:`SampleDataGenerator`."""
    from .llm import DeepSeekClient
    from .validation import detect_schema_kind

    resolved_kind = kind or detect_schema_kind(schema_text)
    resolved_client = client if client is not None else DeepSeekClient.from_env()
    request = GenerationRequest(
        schema_text=schema_text,
        kind=resolved_kind,
        instructions=instructions,
        root_element=root_element,
        max_attempts=max_attempts,
    )
    return SampleDataGenerator(resolved_client).generate(request, on_attempt=on_attempt)


def attempt_summaries(attempts: Sequence[GenerationAttempt]) -> list[str]:
    """One-line summaries of a run, used by the CLI and the UI log."""
    summaries = []
    for attempt in attempts:
        if attempt.is_valid:
            summaries.append(f"attempt {attempt.index}: valid")
        else:
            report = attempt.report
            detail = (
                report.schema_error or report.parse_error or f"{len(report.issues)} violation(s)"
            )
            summaries.append(f"attempt {attempt.index}: {detail}")
    return summaries


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "GenerationError",
    "GenerationRequest",
    "LLMError",
    "SampleDataGenerator",
    "attempt_summaries",
    "build_initial_messages",
    "build_repair_message",
    "extract_document",
    "generate_sample",
]

from __future__ import annotations

import json

import pytest

from schema_data_forge.generator import (
    GenerationError,
    GenerationRequest,
    SampleDataGenerator,
    attempt_summaries,
    build_initial_messages,
    build_repair_message,
    extract_document,
)
from schema_data_forge.llm import LLMClient, Message
from schema_data_forge.models import SchemaKind, ValidationIssue, ValidationReport


class ScriptedClient(LLMClient):
    """Returns canned completions and records the prompts it received."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[Message]] = []

    def complete_json(self, messages: list[Message]) -> str:
        self.calls.append(list(messages))
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def test_extract_json_envelope() -> None:
    document = extract_document('{"data": {"a": 1}}', SchemaKind.JSON_SCHEMA)
    assert json.loads(document) == {"a": 1}


def test_extract_json_without_envelope() -> None:
    document = extract_document('{"a": 1}', SchemaKind.JSON_SCHEMA)
    assert json.loads(document) == {"a": 1}


def test_extract_xml_envelope_and_fences() -> None:
    raw = '```json\n{"xml": "```xml\\n<a/>\\n```"}\n```'
    assert extract_document(raw, SchemaKind.XML_SCHEMA) == "<a/>"


def test_extract_raw_xml_fallback() -> None:
    assert extract_document("<a/>", SchemaKind.XML_SCHEMA) == "<a/>"


def test_extract_rejects_garbage() -> None:
    with pytest.raises(GenerationError):
        extract_document("not json at all", SchemaKind.JSON_SCHEMA)
    with pytest.raises(GenerationError):
        extract_document('{"note": 1}', SchemaKind.XML_SCHEMA)


def test_prompt_mentions_root_element_and_namespace(ontology_xsd: str) -> None:
    request = GenerationRequest(
        schema_text=ontology_xsd,
        kind=SchemaKind.XML_SCHEMA,
        instructions="only two object types",
        root_element="ontology",
    )
    messages = build_initial_messages(request)
    prompt = messages[-1].content
    assert "Use `ontology` as the root element." in prompt
    assert "https://palantir.com/ontology/v1" in prompt
    assert "only two object types" in prompt
    assert '{"xml"' in prompt


def test_repair_message_lists_violations() -> None:
    report = ValidationReport(issues=(ValidationIssue("value 250 is above maximum", "$.risk"),))
    message = build_repair_message(report, SchemaKind.JSON_SCHEMA)
    assert message.role == "user"
    assert "$.risk: value 250 is above maximum" in message.content


def test_generator_retries_until_valid(object_set_schema: str, valid_object_set: str) -> None:
    broken = json.loads(valid_object_set)
    broken["objects"][0]["lifecycle"] = "RETIRED"
    client = ScriptedClient(
        [
            json.dumps({"data": broken}),
            json.dumps({"data": json.loads(valid_object_set)}),
        ]
    )
    request = GenerationRequest(schema_text=object_set_schema, kind=SchemaKind.JSON_SCHEMA)

    result = SampleDataGenerator(client).generate(request)

    assert result.succeeded
    assert len(result.attempts) == 2
    assert not result.attempts[0].is_valid
    assert attempt_summaries(result.attempts) == [
        "attempt 1: 1 violation(s)",
        "attempt 2: valid",
    ]
    # the second prompt carries the assistant answer plus the validator feedback
    second_prompt = client.calls[1]
    assert second_prompt[-2].role == "assistant"
    assert "RETIRED" in second_prompt[-1].content


def test_generator_gives_up_after_max_attempts(object_set_schema: str) -> None:
    client = ScriptedClient([json.dumps({"data": {"objectType": "Nope"}})])
    request = GenerationRequest(
        schema_text=object_set_schema, kind=SchemaKind.JSON_SCHEMA, max_attempts=3
    )

    result = SampleDataGenerator(client).generate(request)

    assert not result.succeeded
    assert result.document is None
    assert len(result.attempts) == 3
    assert len(client.calls) == 3


def test_generator_stops_when_schema_is_broken() -> None:
    client = ScriptedClient([json.dumps({"data": {}})])
    request = GenerationRequest(schema_text='{"type": 12}', kind=SchemaKind.JSON_SCHEMA)

    result = SampleDataGenerator(client).generate(request)

    assert len(result.attempts) == 1
    assert result.attempts[0].report.schema_error is not None


def test_generator_reports_unparsable_output(object_set_schema: str) -> None:
    client = ScriptedClient(["I am not JSON"])
    request = GenerationRequest(
        schema_text=object_set_schema, kind=SchemaKind.JSON_SCHEMA, max_attempts=1
    )

    result = SampleDataGenerator(client).generate(request)

    assert not result.succeeded
    assert result.attempts[0].report.parse_error is not None


def test_generator_honours_cancellation(object_set_schema: str, valid_object_set: str) -> None:
    client = ScriptedClient([json.dumps({"data": json.loads(valid_object_set)})])
    request = GenerationRequest(schema_text=object_set_schema, kind=SchemaKind.JSON_SCHEMA)

    result = SampleDataGenerator(client).generate(request, should_cancel=lambda: True)

    assert result.attempts == []
    assert client.calls == []


def test_generator_validates_xml_flow(ontology_xsd: str, valid_ontology_xml: str) -> None:
    client = ScriptedClient([json.dumps({"xml": valid_ontology_xml})])
    request = GenerationRequest(
        schema_text=ontology_xsd, kind=SchemaKind.XML_SCHEMA, root_element="ontology"
    )

    result = SampleDataGenerator(client).generate(request)

    assert result.succeeded
    assert result.document is not None
    assert "flightOperations" in result.document

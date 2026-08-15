from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from schema_data_forge.llm import LLMClient, Message
from schema_data_forge.models import SchemaKind
from schema_data_forge.web.server import GenerateBody, create_app


class ScriptedClient(LLMClient):
    """Returns canned completions and records the prompts it received."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[Message]] = []

    def complete_json(self, messages: list[Message]) -> str:
        self.calls.append(list(messages))
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def client_for(responses: list[str]) -> tuple[TestClient, ScriptedClient]:
    scripted = ScriptedClient(responses)

    def factory(body: GenerateBody) -> LLMClient:
        return scripted

    return TestClient(create_app(client_factory=factory)), scripted


def sse_events(text: str) -> Iterator[tuple[str, dict[str, object]]]:
    for chunk in text.strip().split("\n\n"):
        lines = chunk.splitlines()
        event = next(line[7:].strip() for line in lines if line.startswith("event: "))
        payload = next(line[6:] for line in lines if line.startswith("data: "))
        yield event, json.loads(payload)


@pytest.fixture
def app_client() -> TestClient:
    return TestClient(create_app(client_factory=lambda body: ScriptedClient(["{}"])))


def test_index_and_static_assets(app_client: TestClient) -> None:
    assert "Schema Data Forge" in app_client.get("/").text
    assert app_client.get("/static/app.js").status_code == 200
    assert app_client.get("/static/styles.css").status_code == 200


def test_list_examples_includes_palantir_xsd(app_client: TestClient) -> None:
    examples = app_client.get("/api/examples").json()
    xsd = [item for item in examples if item["kind"] == SchemaKind.XML_SCHEMA.value]
    assert xsd, "expected a bundled XSD example"
    assert xsd[0]["rootElement"] == "ontology"
    assert "xs:schema" in xsd[0]["schemaText"]


def test_root_elements(app_client: TestClient, ontology_xsd: str) -> None:
    response = app_client.post("/api/root-elements", json={"schemaText": ontology_xsd})
    assert response.json() == ["ontology"]


def test_root_elements_on_broken_schema(app_client: TestClient) -> None:
    assert app_client.post("/api/root-elements", json={"schemaText": "<nope/>"}).json() == []


def test_validate_xml_valid(
    app_client: TestClient, ontology_xsd: str, valid_ontology_xml: str
) -> None:
    report = app_client.post(
        "/api/validate",
        json={
            "document": valid_ontology_xml,
            "schemaText": ontology_xsd,
            "kind": "xml-schema",
        },
    ).json()
    assert report["valid"] is True
    assert report["issues"] == []


def test_validate_xml_invalid_reports_location(
    app_client: TestClient, ontology_xsd: str, valid_ontology_xml: str
) -> None:
    broken = valid_ontology_xml.replace('cardinality="ONE_TO_ONE"', 'cardinality="SOMETIMES"')
    report = app_client.post(
        "/api/validate",
        json={"document": broken, "schemaText": ontology_xsd, "kind": "xml-schema"},
    ).json()
    assert report["valid"] is False
    assert report["issues"]
    assert report["issues"][0]["message"]


def test_validate_json_invalid(app_client: TestClient, object_set_schema: str) -> None:
    report = app_client.post(
        "/api/validate",
        json={
            "document": json.dumps({"ontologyApiName": "x"}),
            "schemaText": object_set_schema,
            "kind": "json-schema",
        },
    ).json()
    assert report["valid"] is False


def test_validate_reports_parse_error(app_client: TestClient, object_set_schema: str) -> None:
    report = app_client.post(
        "/api/validate",
        json={"document": "{oops", "schemaText": object_set_schema, "kind": "json-schema"},
    ).json()
    assert report["valid"] is False
    assert report["parseError"]


def test_format_json_and_xml(app_client: TestClient) -> None:
    formatted = app_client.post(
        "/api/format", json={"document": '{"a":1}', "kind": "json-schema"}
    ).json()["document"]
    assert formatted.startswith("{\n")

    formatted_xml = app_client.post(
        "/api/format", json={"document": "<a><b>1</b></a>", "kind": "xml-schema"}
    ).json()["document"]
    assert "<b>1</b>" in formatted_xml


def test_generate_rejects_empty_schema(app_client: TestClient) -> None:
    response = app_client.post("/api/generate", json={"schemaText": "  ", "kind": "xml-schema"})
    assert response.status_code == 400


def test_generate_requires_api_key(ontology_xsd: str) -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/generate",
        json={"schemaText": ontology_xsd, "kind": "xml-schema"},
    )
    assert response.status_code == 400
    assert "API Key" in response.json()["detail"]


def test_generate_xsd_streams_success(ontology_xsd: str, valid_ontology_xml: str) -> None:
    client, scripted = client_for([json.dumps({"xml": valid_ontology_xml})])
    response = client.post(
        "/api/generate",
        json={
            "schemaText": ontology_xsd,
            "kind": "xml-schema",
            "rootElement": "ontology",
            "apiKey": "test-key",
        },
    )
    assert response.status_code == 200
    events = dict(sse_events(response.text))
    assert events["start"]["kind"] == "xml-schema"
    assert events["attempt"]["report"]["valid"] is True
    assert events["done"]["succeeded"] is True
    assert events["done"]["attempts"] == 1
    assert 'apiName="flightOperations"' in str(events["done"]["document"])
    assert "ontology" in scripted.calls[0][-1].content


def test_generate_json_retries_with_validation_feedback(
    object_set_schema: str, valid_object_set: str
) -> None:
    invalid = json.dumps({"data": {"ontologyApiName": "supplyChainRisk"}})
    client, scripted = client_for([invalid, json.dumps({"data": json.loads(valid_object_set)})])
    response = client.post(
        "/api/generate",
        json={
            "schemaText": object_set_schema,
            "kind": "json-schema",
            "apiKey": "test-key",
            "maxAttempts": 3,
        },
    )
    events = list(sse_events(response.text))
    attempts = [payload for event, payload in events if event == "attempt"]
    assert len(attempts) == 2
    assert attempts[0]["report"]["valid"] is False
    assert attempts[1]["report"]["valid"] is True
    done = next(payload for event, payload in events if event == "done")
    assert done["succeeded"] is True

    repair_prompt = scripted.calls[1][-1].content
    assert "objectType" in repair_prompt


def test_generate_reports_failure_without_document(object_set_schema: str) -> None:
    client, _ = client_for([json.dumps({"data": {"ontologyApiName": "x"}})])
    response = client.post(
        "/api/generate",
        json={
            "schemaText": object_set_schema,
            "kind": "json-schema",
            "apiKey": "test-key",
            "maxAttempts": 2,
        },
    )
    done = next(payload for event, payload in sse_events(response.text) if event == "done")
    assert done["succeeded"] is False
    assert done["document"] is None


def test_generate_surfaces_llm_errors(ontology_xsd: str) -> None:
    class FailingClient(LLMClient):
        def complete_json(self, messages: list[Message]) -> str:
            raise RuntimeError("boom")

    app = create_app(client_factory=lambda body: FailingClient())
    response = TestClient(app).post(
        "/api/generate",
        json={"schemaText": ontology_xsd, "kind": "xml-schema", "apiKey": "test-key"},
    )
    error = next(payload for event, payload in sse_events(response.text) if event == "error")
    assert "boom" in str(error["message"])

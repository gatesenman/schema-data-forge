"""End-to-end tests that hit the live DeepSeek API.

Run with::

    DEEPSEEK_API_KEY=sk-... pytest -m e2e

They are skipped when no API key is configured.
"""

from __future__ import annotations

import os

import pytest

from schema_data_forge.generator import GenerationRequest, SampleDataGenerator
from schema_data_forge.llm import API_KEY_ENV, DeepSeekClient
from schema_data_forge.models import SchemaKind
from schema_data_forge.validation import validate

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get(API_KEY_ENV), reason=f"{API_KEY_ENV} is not set"),
]


@pytest.fixture(scope="module")
def client() -> DeepSeekClient:
    return DeepSeekClient.from_env(temperature=0.3)


def _run(client: DeepSeekClient, request: GenerationRequest) -> str:
    attempts: list[str] = []
    result = SampleDataGenerator(client).generate(
        request,
        on_attempt=lambda attempt: attempts.append(
            f"attempt {attempt.index}: "
            + ("valid" if attempt.is_valid else attempt.report.as_feedback(limit=5))
        ),
    )
    assert result.succeeded, "\n".join(attempts)
    document = result.document
    assert document is not None
    return document


def test_generates_valid_palantir_ontology_xml(client: DeepSeekClient, ontology_xsd: str) -> None:
    document = _run(
        client,
        GenerationRequest(
            schema_text=ontology_xsd,
            kind=SchemaKind.XML_SCHEMA,
            root_element="ontology",
            instructions=(
                "Model flight operations: object types for flights, aircraft and airports, "
                "at least two link types and one action type."
            ),
            max_attempts=5,
        ),
    )
    assert validate(document, ontology_xsd, SchemaKind.XML_SCHEMA).is_valid
    assert "https://palantir.com/ontology/v1" in document


def test_generates_valid_object_set_json(client: DeepSeekClient, object_set_schema: str) -> None:
    document = _run(
        client,
        GenerationRequest(
            schema_text=object_set_schema,
            kind=SchemaKind.JSON_SCHEMA,
            instructions="Supply chain risk scenario with four suppliers and two links.",
            max_attempts=5,
        ),
    )
    assert validate(document, object_set_schema, SchemaKind.JSON_SCHEMA).is_valid

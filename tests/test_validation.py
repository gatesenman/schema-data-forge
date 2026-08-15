from __future__ import annotations

import json

from schema_data_forge.models import SchemaKind
from schema_data_forge.validation import (
    detect_schema_kind,
    format_document,
    validate,
    validate_json,
    validate_xml,
    xsd_root_elements,
    xsd_target_namespace,
)


def test_valid_json_document_passes(object_set_schema: str, valid_object_set: str) -> None:
    report = validate_json(valid_object_set, object_set_schema)
    assert report.is_valid, report.as_feedback()


def test_json_violations_are_located(object_set_schema: str, valid_object_set: str) -> None:
    document = json.loads(valid_object_set)
    document["objects"][0]["lifecycle"] = "RETIRED"
    document["objects"][0]["properties"]["riskScore"] = 250
    report = validate_json(json.dumps(document), object_set_schema)

    assert not report.is_valid
    locations = {issue.location for issue in report.issues}
    assert "$.objects[0].lifecycle" in locations
    assert "$.objects[0].properties.riskScore" in locations
    assert "- $.objects[0].lifecycle" in report.as_feedback()


def test_json_parse_error_is_reported(object_set_schema: str) -> None:
    report = validate_json("{not json", object_set_schema)
    assert report.parse_error is not None
    assert not report.is_valid


def test_broken_json_schema_is_reported(valid_object_set: str) -> None:
    report = validate_json(valid_object_set, '{"type": 12}')
    assert report.schema_error is not None


def test_valid_ontology_xml_passes(ontology_xsd: str, valid_ontology_xml: str) -> None:
    report = validate_xml(valid_ontology_xml, ontology_xsd)
    assert report.is_valid, report.as_feedback()


def test_xml_pattern_violation_is_detected(ontology_xsd: str, valid_ontology_xml: str) -> None:
    broken = valid_ontology_xml.replace(
        'datasetRid="ri.foundry.main.dataset.7f3c1b90-4e2d-4a11-9d55-2b8c6f0a1d42"',
        'datasetRid="dataset-1"',
    )
    report = validate_xml(broken, ontology_xsd)
    assert not report.is_valid
    assert any("dataset-1" in issue.message for issue in report.issues)


def test_xml_keyref_violation_is_detected(ontology_xsd: str, valid_ontology_xml: str) -> None:
    broken = valid_ontology_xml.replace('targetObjectType="aircraft"', 'targetObjectType="crew"')
    report = validate_xml(broken, ontology_xsd)
    assert not report.is_valid


def test_xml_parse_error_is_reported(ontology_xsd: str) -> None:
    report = validate_xml("<ontology>", ontology_xsd)
    assert report.parse_error is not None


def test_broken_xsd_is_reported(valid_ontology_xml: str) -> None:
    report = validate_xml(valid_ontology_xml, "<xs:schema/>")
    assert report.schema_error is not None


def test_schema_introspection(ontology_xsd: str) -> None:
    assert xsd_root_elements(ontology_xsd) == ["ontology"]
    assert xsd_target_namespace(ontology_xsd) == "https://palantir.com/ontology/v1"


def test_detect_schema_kind(ontology_xsd: str, object_set_schema: str) -> None:
    assert detect_schema_kind(ontology_xsd) is SchemaKind.XML_SCHEMA
    assert detect_schema_kind(object_set_schema) is SchemaKind.JSON_SCHEMA


def test_validate_dispatches_on_kind(ontology_xsd: str, valid_ontology_xml: str) -> None:
    assert validate(valid_ontology_xml, ontology_xsd, SchemaKind.XML_SCHEMA).is_valid


def test_format_document_round_trips() -> None:
    assert json.loads(format_document('{"a":[1,2]}', SchemaKind.JSON_SCHEMA)) == {"a": [1, 2]}
    formatted = format_document("<a><b>1</b></a>", SchemaKind.XML_SCHEMA)
    assert "<b>1</b>" in formatted
    assert format_document("<a>", SchemaKind.XML_SCHEMA) == "<a>"

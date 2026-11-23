from __future__ import annotations

import json
from pathlib import Path

import tomllib
import yaml
from fastapi.testclient import TestClient

from schema_data_forge.cli import main
from schema_data_forge.models import SchemaKind
from schema_data_forge.validation import validate, validate_json
from schema_data_forge.web.server import create_app


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_validate_accepts_valid_json(
    object_set_schema: str, valid_object_set: str, tmp_path: Path
) -> None:
    schema = _write(tmp_path / "schema.json", object_set_schema)
    document = _write(tmp_path / "document.json", valid_object_set)
    assert main(["--schema", str(schema), "--document", str(document)]) == 0


def test_cli_validate_rejects_invalid_json(
    object_set_schema: str, valid_object_set: str, tmp_path: Path
) -> None:
    broken = json.loads(valid_object_set)
    broken["objects"][0]["lifecycle"] = "RETIRED"
    schema = _write(tmp_path / "schema.json", object_set_schema)
    document = _write(tmp_path / "broken.json", json.dumps(broken))
    assert main(["--schema", str(schema), "--document", str(document)]) == 1


def test_cli_validate_accepts_valid_xml(
    ontology_xsd: str, valid_ontology_xml: str, tmp_path: Path
) -> None:
    schema = _write(tmp_path / "schema.xsd", ontology_xsd)
    document = _write(tmp_path / "document.xml", valid_ontology_xml)
    assert main(["--schema", str(schema), "--document", str(document)]) == 0


def test_cli_validate_reports_missing_document(object_set_schema: str, tmp_path: Path) -> None:
    schema = _write(tmp_path / "schema.json", object_set_schema)
    missing = tmp_path / "no-such.json"
    assert main(["--schema", str(schema), "--document", str(missing)]) == 2


def test_yaml_and_toml_round_trip_stays_schema_valid(
    object_set_schema: str, valid_object_set: str
) -> None:
    app_client = TestClient(create_app())
    yaml_text = app_client.post(
        "/api/convert", json={"document": valid_object_set, "target": "yaml"}
    ).json()["document"]
    yaml_report = validate_json(json.dumps(yaml.safe_load(yaml_text)), object_set_schema)
    assert yaml_report.is_valid, yaml_report.as_feedback()

    toml_text = app_client.post(
        "/api/convert", json={"document": valid_object_set, "target": "toml"}
    ).json()["document"]
    toml_report = validate_json(json.dumps(tomllib.loads(toml_text)), object_set_schema)
    assert toml_report.is_valid, toml_report.as_feedback()
    assert validate(valid_object_set, object_set_schema, SchemaKind.JSON_SCHEMA).is_valid

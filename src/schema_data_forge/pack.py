"""Build a validated sample pack from bundled example schemas without calling an LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .examples import read_example
from .models import SchemaKind
from .validation import validate

STARTER_OBJECT_SET = {
    "ontologyApiName": "supplyChainRisk",
    "objectType": "Supplier",
    "objects": [
        {
            "primaryKey": "SUP-10041",
            "rid": "ri.ontology.main.object.4f2a1c88-91de-4d0a-8b57-2c9f0a7d1e30",
            "title": "Northwind Components GmbH",
            "lifecycle": "ACTIVE",
            "properties": {
                "name": "Northwind Components GmbH",
                "classification": "CONFIDENTIAL",
                "createdAt": "2024-03-11T08:15:00Z",
                "riskScore": 42.5,
                "tags": ["tier-1", "eu-region"],
                "location": {"latitude": 52.52, "longitude": 13.405},
            },
        },
        {
            "primaryKey": "SUP-10042",
            "rid": "ri.ontology.main.object.7bb2e910-3c44-4f11-9a02-51de77c4b8aa",
            "title": "Pacific Rim Logistics",
            "lifecycle": "PENDING_REVIEW",
            "properties": {
                "name": "Pacific Rim Logistics",
                "classification": "UNCLASSIFIED",
                "createdAt": "2024-04-02T13:45:00Z",
            },
        },
        {
            "primaryKey": "SUP-10043",
            "rid": "ri.ontology.main.object.9c1d4f27-88ba-4c65-9f31-0d7ab2e51c64",
            "title": "Andes Metal Works",
            "lifecycle": "ARCHIVED",
            "properties": {
                "name": "Andes Metal Works",
                "classification": "SECRET",
                "createdAt": "2023-11-20T21:05:00Z",
                "riskScore": 88,
            },
        },
    ],
    "links": [
        {
            "linkTypeApiName": "shipsThrough",
            "sourcePrimaryKey": "SUP-10041",
            "targetPrimaryKey": "SUP-10042",
        }
    ],
    "page": {"size": 3, "hasMore": False},
}


@dataclass
class PackItem:
    name: str
    kind: str
    valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class PackResult:
    output_dir: Path
    items: list[PackItem]

    @property
    def ok(self) -> bool:
        return all(item.valid for item in self.items)


def _fixture_ontology_xml() -> str:
    bundled = Path(__file__).with_name("example_documents") / "palantir_ontology_valid.xml"
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")
    candidate = Path(__file__).resolve().parents[2] / "tests" / "data" / "palantir_ontology_valid.xml"
    return candidate.read_text(encoding="utf-8")


def write_pack(output_dir: Path) -> PackResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[PackItem] = []

    schema_json = read_example("palantir_object_set.schema.json")
    schema_xsd = read_example("palantir_ontology.xsd")
    (output_dir / "palantir_object_set.schema.json").write_text(schema_json, encoding="utf-8")
    (output_dir / "palantir_ontology.xsd").write_text(schema_xsd, encoding="utf-8")

    object_set = json.dumps(STARTER_OBJECT_SET, indent=2, ensure_ascii=False) + "\n"
    (output_dir / "palantir_object_set.sample.json").write_text(object_set, encoding="utf-8")
    json_result = validate(object_set, schema_json, SchemaKind.JSON_SCHEMA)
    items.append(
        PackItem(
            "palantir_object_set.sample.json",
            "json",
            json_result.is_valid,
            [issue.describe() for issue in json_result.issues] if not json_result.is_valid else [],
        )
    )

    ontology_xml = _fixture_ontology_xml()
    (output_dir / "palantir_ontology.sample.xml").write_text(ontology_xml, encoding="utf-8")
    xml_result = validate(ontology_xml, schema_xsd, SchemaKind.XML_SCHEMA)
    items.append(
        PackItem(
            "palantir_ontology.sample.xml",
            "xml",
            xml_result.is_valid,
            [issue.describe() for issue in xml_result.issues] if not xml_result.is_valid else [],
        )
    )

    manifest = {
        "title": "schema-data-forge starter pack",
        "generator": "schema-data-forge pack (no LLM)",
        "items": [
            {"name": item.name, "kind": item.kind, "valid": item.valid, "errors": item.errors}
            for item in items
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return PackResult(output_dir=output_dir, items=items)


# Keep a copy of the XML fixture next to the package for packs built without the tests tree.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schema_data_forge.examples import read_example

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def ontology_xsd() -> str:
    return read_example("palantir_ontology.xsd")


@pytest.fixture(scope="session")
def object_set_schema() -> str:
    return read_example("palantir_object_set.schema.json")


@pytest.fixture(scope="session")
def valid_ontology_xml() -> str:
    return (DATA_DIR / "palantir_ontology_valid.xml").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def valid_object_set() -> str:
    return json.dumps(
        {
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
        },
        indent=2,
    )

"""Bundled example schemas shown in the editor's example picker."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .models import SchemaKind

_PACKAGE = "schema_data_forge.example_schemas"


@dataclass(frozen=True)
class Example:
    """A bundled schema together with sensible default generation settings."""

    title: str
    filename: str
    kind: SchemaKind
    root_element: str = ""
    instructions: str = ""

    @property
    def schema_text(self) -> str:
        return read_example(self.filename)


EXAMPLES: tuple[Example, ...] = (
    Example(
        title="Palantir 本体模型 (XSD)",
        filename="palantir_ontology.xsd",
        kind=SchemaKind.XML_SCHEMA,
        root_element="ontology",
        instructions=(
            "以航班运营领域建模：包含 Flight、Aircraft、Airport 三个对象类型，"
            "至少两个 linkType 和一个 actionType；"
            "linkType 的 source/target 必须引用已定义的对象类型。"
        ),
    ),
    Example(
        title="Palantir 对象集合 (JSON Schema)",
        filename="palantir_object_set.schema.json",
        kind=SchemaKind.JSON_SCHEMA,
        instructions=(
            "以供应链风控场景为例，生成 4 个对象，其中至少 2 个带有地理坐标和标签，"
            "并给出对象之间的 links。"
        ),
    ),
)


def read_example(filename: str) -> str:
    """Read a bundled example schema by file name."""
    return resources.files(_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def example_path(filename: str) -> Path:
    """Filesystem path of a bundled example, useful for the CLI and tests."""
    with resources.as_file(resources.files(_PACKAGE).joinpath(filename)) as path:
        return path


def load_examples() -> list[Example]:
    """All bundled examples, in display order."""
    return list(EXAMPLES)

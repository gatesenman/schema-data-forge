from __future__ import annotations

import json
from pathlib import Path

from schema_data_forge.cli import main
from schema_data_forge.pack import write_pack


def test_write_pack_validates_bundled_samples_without_llm(tmp_path: Path) -> None:
    result = write_pack(tmp_path / "pack")
    assert result.ok
    assert (result.output_dir / "manifest.json").is_file()
    manifest = json.loads((result.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator"].endswith("no LLM)")
    assert all(item["valid"] for item in manifest["items"])
    assert (result.output_dir / "palantir_object_set.sample.json").is_file()
    assert (result.output_dir / "palantir_ontology.sample.xml").is_file()


def test_cli_pack_writes_directory(tmp_path: Path) -> None:
    out = tmp_path / "starter"
    assert main(["--pack", str(out)]) == 0
    assert (out / "manifest.json").is_file()

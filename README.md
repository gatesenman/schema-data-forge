# Schema Data Forge

**English** | [简体中文](./README.zh-CN.md)

Desktop editor that generates JSON/XML sample data from JSON Schema and XML Schema using AI, with mandatory schema validation.

## What's new in 0.2.0

You can build a starter pack from the bundled Palantir example schemas **without calling an LLM**:

```bash
python -m schema_data_forge.cli --pack ./starter-pack
```

The pack writes the schemas, validated JSON and XML samples, and a `manifest.json` of validation results.

## Features
- JSON Schema → sample data
- XML Schema → sample data
- AI-assisted generation (optional)
- Mandatory schema validation
- Offline starter pack (`--pack`) for generate + validate using bundled examples
- Desktop application

## Tech Stack
- Python

## Verify

```bash
pytest tests -k "not e2e"
```

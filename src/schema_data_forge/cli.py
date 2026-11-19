"""Headless generator, used for end-to-end checks and for scripting."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .examples import EXAMPLES, example_path
from .generator import (
    DEFAULT_MAX_ATTEMPTS,
    GenerationRequest,
    SampleDataGenerator,
)
from .llm import DeepSeekClient, LLMError
from .models import GenerationAttempt, SchemaKind
from .validation import detect_schema_kind, validate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schema-data-forge-cli",
        description="Generate sample data for a JSON Schema or XSD and validate it.",
    )
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--schema", type=Path, help="path to a JSON Schema or .xsd file")
    source.add_argument(
        "--example",
        choices=[example.filename for example in EXAMPLES],
        help="use a bundled example schema",
    )
    parser.add_argument(
        "--pack",
        type=Path,
        help="write a no-LLM starter pack (schemas + validated samples) to this directory and exit",
    )
    parser.add_argument("--kind", choices=[kind.value for kind in SchemaKind])
    parser.add_argument("--root-element", default="", help="root element name for XSD schemas")
    parser.add_argument("--instructions", default="", help="extra requirements for the model")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--out", type=Path, help="write the validated document to this file")
    parser.add_argument(
        "--document",
        type=Path,
        help="validate this document against the schema and exit (no LLM call)",
    )
    return parser


def _load_schema(args: argparse.Namespace) -> tuple[str, SchemaKind]:
    schema_path = args.schema if args.schema else example_path(args.example)
    schema_text = schema_path.read_text(encoding="utf-8")
    kind = SchemaKind(args.kind) if args.kind else detect_schema_kind(schema_text)
    return schema_text, kind


def _validate_document(args: argparse.Namespace) -> int:
    """Validate ``args.document`` against the selected schema and print a report."""
    if not args.document.exists():
        print(f"error: document not found: {args.document}", file=sys.stderr)
        return 2
    schema_text, kind = _load_schema(args)
    document = args.document.read_text(encoding="utf-8")
    report = validate(document, schema_text, kind)
    if report.is_valid:
        print("valid")
        return 0
    print(report.as_feedback(), file=sys.stderr)
    print("invalid", file=sys.stderr)
    return 1


def _write_pack(args: argparse.Namespace) -> int:
    from .pack import write_pack

    result = write_pack(args.pack)
    for item in result.items:
        status = "valid" if item.valid else "invalid"
        print(f"{item.name}: {status}")
        if not item.valid:
            for err in item.errors:
                print(f"  - {err}", file=sys.stderr)
    print(f"wrote pack to {result.output_dir}", file=sys.stderr)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    """Run one generation round, or validate a document when --document is set."""
    args = _build_parser().parse_args(argv)

    if args.pack is not None:
        return _write_pack(args)
    if args.schema is None and args.example is None:
        _build_parser().error("one of --schema, --example, or --pack is required")
    if args.document is not None:
        return _validate_document(args)

    schema_text, kind = _load_schema(args)

    root_element = args.root_element
    if not root_element and args.example:
        root_element = next((ex.root_element for ex in EXAMPLES if ex.filename == args.example), "")

    try:
        client = DeepSeekClient.from_env(model=args.model, temperature=args.temperature)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    request = GenerationRequest(
        schema_text=schema_text,
        kind=kind,
        instructions=args.instructions,
        root_element=root_element,
        max_attempts=args.max_attempts,
    )

    def report_attempt(attempt: GenerationAttempt) -> None:
        if attempt.is_valid:
            print(f"attempt {attempt.index}: valid", file=sys.stderr)
        else:
            print(
                f"attempt {attempt.index}: invalid\n{attempt.report.as_feedback(limit=10)}",
                file=sys.stderr,
            )

    try:
        result = SampleDataGenerator(client).generate(request, on_attempt=report_attempt)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    document = result.document
    if document is None:
        print("error: no valid document produced", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(document, encoding="utf-8")
        print(f"wrote {args.out} after {len(result.attempts)} attempt(s)", file=sys.stderr)
    else:
        print(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

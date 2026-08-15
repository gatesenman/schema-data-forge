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
from .validation import detect_schema_kind


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schema-data-forge-cli",
        description="Generate sample data for a JSON Schema or XSD and validate it.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--schema", type=Path, help="path to a JSON Schema or .xsd file")
    source.add_argument(
        "--example",
        choices=[example.filename for example in EXAMPLES],
        help="use a bundled example schema",
    )
    parser.add_argument("--kind", choices=[kind.value for kind in SchemaKind])
    parser.add_argument("--root-element", default="", help="root element name for XSD schemas")
    parser.add_argument("--instructions", default="", help="extra requirements for the model")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--out", type=Path, help="write the validated document to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one generation round and report the outcome on stdout/stderr."""
    args = _build_parser().parse_args(argv)

    schema_path = args.schema if args.schema else example_path(args.example)
    schema_text = schema_path.read_text(encoding="utf-8")
    kind = SchemaKind(args.kind) if args.kind else detect_schema_kind(schema_text)

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

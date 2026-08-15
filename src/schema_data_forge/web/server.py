"""FastAPI backend for the browser UI."""

from __future__ import annotations

import json
import os
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import tomli_w
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..examples import EXAMPLES
from ..generator import DEFAULT_MAX_ATTEMPTS, GenerationRequest, SampleDataGenerator
from ..llm import API_KEY_ENV, DEFAULT_BASE_URL, DEFAULT_MODEL, DeepSeekClient, LLMClient, LLMError
from ..models import GenerationAttempt, SchemaKind, ValidationReport
from ..validation import format_document, validate, xsd_root_elements

STATIC_DIR = Path(__file__).parent / "static"

ClientFactory = Callable[["GenerateBody"], LLMClient]


class ExampleModel(BaseModel):
    title: str
    filename: str
    kind: SchemaKind
    rootElement: str  # noqa: N815 - mirrors the JSON payload
    instructions: str
    schemaText: str  # noqa: N815 - mirrors the JSON payload


class ValidateBody(BaseModel):
    document: str
    schemaText: str  # noqa: N815 - mirrors the JSON payload
    kind: SchemaKind


class ReportModel(BaseModel):
    valid: bool
    schemaError: str | None = None  # noqa: N815 - mirrors the JSON payload
    parseError: str | None = None  # noqa: N815 - mirrors the JSON payload
    issues: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_report(cls, report: ValidationReport) -> ReportModel:
        return cls(
            valid=report.is_valid,
            schemaError=report.schema_error,
            parseError=report.parse_error,
            issues=[asdict(issue) for issue in report.issues],
        )


class FormatBody(BaseModel):
    document: str
    kind: SchemaKind


class ConvertBody(BaseModel):
    document: str
    target: Literal["yaml", "toml"]


class RootElementsBody(BaseModel):
    schemaText: str  # noqa: N815 - mirrors the JSON payload


class GenerateBody(BaseModel):
    schemaText: str  # noqa: N815 - mirrors the JSON payload
    kind: SchemaKind
    instructions: str = ""
    rootElement: str = ""  # noqa: N815 - mirrors the JSON payload
    maxAttempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1, le=10)  # noqa: N815
    apiKey: str = ""  # noqa: N815 - mirrors the JSON payload
    model: str = DEFAULT_MODEL
    baseUrl: str = DEFAULT_BASE_URL  # noqa: N815 - mirrors the JSON payload
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)

    def to_request(self) -> GenerationRequest:
        return GenerationRequest(
            schema_text=self.schemaText,
            kind=self.kind,
            instructions=self.instructions,
            root_element=self.rootElement,
            max_attempts=self.maxAttempts,
        )


def _default_client_factory(body: GenerateBody) -> LLMClient:
    api_key = body.apiKey.strip() or os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"缺少 DeepSeek API Key（请在左侧填写，或设置环境变量 {API_KEY_ENV}）",
        )
    return DeepSeekClient(
        api_key=api_key,
        model=body.model or DEFAULT_MODEL,
        base_url=body.baseUrl or DEFAULT_BASE_URL,
        temperature=body.temperature,
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _attempt_payload(attempt: GenerationAttempt) -> dict[str, Any]:
    return {
        "index": attempt.index,
        "document": attempt.document,
        "report": ReportModel.from_report(attempt.report).model_dump(),
    }


def _run_generation(
    client: LLMClient, request: GenerationRequest
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Run a generation on a worker thread and yield SSE events as they happen."""
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

    def worker() -> None:
        try:
            result = SampleDataGenerator(client).generate(
                request,
                on_attempt=lambda attempt: events.put(("attempt", _attempt_payload(attempt))),
            )
        except LLMError as exc:
            events.put(("error", {"message": str(exc)}))
        except Exception as exc:  # noqa: BLE001 - report everything to the browser
            events.put(("error", {"message": f"unexpected error: {exc}"}))
        else:
            events.put(
                (
                    "done",
                    {
                        "succeeded": result.succeeded,
                        "document": result.document,
                        "attempts": len(result.attempts),
                    },
                )
            )
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name="generation", daemon=True)
    thread.start()
    while True:
        item = events.get()
        if item is None:
            break
        yield item
    thread.join(timeout=1.0)


def create_app(client_factory: ClientFactory | None = None) -> FastAPI:
    """Build the FastAPI application; ``client_factory`` is overridable for tests."""
    make_client: ClientFactory = client_factory or _default_client_factory
    app = FastAPI(title="Schema Data Forge", docs_url=None, redoc_url=None)

    @app.get("/api/examples", response_model=list[ExampleModel])
    def list_examples() -> list[ExampleModel]:
        return [
            ExampleModel(
                title=example.title,
                filename=example.filename,
                kind=example.kind,
                rootElement=example.root_element,
                instructions=example.instructions,
                schemaText=example.schema_text,
            )
            for example in EXAMPLES
        ]

    @app.post("/api/root-elements", response_model=list[str])
    def root_elements(body: RootElementsBody) -> list[str]:
        return xsd_root_elements(body.schemaText)

    @app.post("/api/validate", response_model=ReportModel)
    def validate_document(body: ValidateBody) -> ReportModel:
        return ReportModel.from_report(validate(body.document, body.schemaText, body.kind))

    @app.post("/api/format", response_model=dict[str, str])
    def format_body(body: FormatBody) -> dict[str, str]:
        return {"document": format_document(body.document, body.kind)}

    @app.post("/api/convert", response_model=dict[str, str])
    def convert_document(body: ConvertBody) -> dict[str, str]:
        try:
            parsed: Any = json.loads(body.document)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON 解析失败：{exc}") from exc
        if body.target == "yaml":
            return {
                "document": yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False, indent=2)
            }
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="TOML 仅支持顶层为对象的 JSON")
        try:
            return {"document": tomli_w.dumps(parsed)}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"无法转换为 TOML：{exc}") from exc

    @app.post("/api/generate")
    def generate(body: GenerateBody) -> StreamingResponse:
        if not body.schemaText.strip():
            raise HTTPException(status_code=400, detail="schema 不能为空")
        client = make_client(body)
        request = body.to_request()

        def stream() -> Iterator[str]:
            yield _sse("start", {"kind": body.kind.value, "maxAttempts": body.maxAttempts})
            for event, payload in _run_generation(client, request):
                yield _sse(event, payload)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    log_level: Literal["info", "warning"] = "info",
) -> None:
    """Run the web UI with uvicorn."""
    uvicorn.run(app, host=host, port=port, log_level=log_level)

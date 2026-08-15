"""Minimal DeepSeek chat client used for structured sample-data generation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
API_KEY_ENV = "DEEPSEEK_API_KEY"


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or answers with an unusable payload."""


class ChatMessage(Protocol):
    role: str
    content: str


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMClient(Protocol):
    """The narrow surface the generator needs; makes it trivial to fake in tests."""

    def complete_json(self, messages: list[Message]) -> str:
        """Return the assistant message content, guaranteed to be a JSON object string."""


@dataclass
class DeepSeekClient:
    """JSON-mode client for the DeepSeek chat completions API."""

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = 0.4
    timeout: float = 180.0
    max_tokens: int = 8192

    @classmethod
    def from_env(cls, **kwargs: Any) -> DeepSeekClient:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise LLMError(f"{API_KEY_ENV} is not set")
        return cls(api_key=api_key, **kwargs)

    def complete_json(self, messages: list[Message]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.as_payload() for message in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"request to DeepSeek failed: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(f"DeepSeek returned HTTP {response.status_code}: {response.text[:500]}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise LLMError(f"unexpected DeepSeek response: {response.text[:500]}") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("DeepSeek returned an empty completion")
        return content

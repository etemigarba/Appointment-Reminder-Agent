"""LLM client abstraction.

`DeepSeekClient` talks to the DeepSeek API through the OpenAI-compatible SDK
(lazily imported, optional `[llm]` extra). `FakeLLMClient` scripts deterministic
turns for tests — no network access anywhere in the suite.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AssistantTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        """Return the next assistant turn for the conversation."""
        ...


class DeepSeekClient:
    """OpenAI-compatible client bound to the DeepSeek endpoint."""

    BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat") -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        self.model = model

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "openai package not installed. Install with: pip install '.[llm]'"
            ) from exc

        client = OpenAI(base_url=self.BASE_URL, api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
        )
        choice = response.choices[0].message
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.tool_calls or [])
        ]
        return AssistantTurn(content=choice.content, tool_calls=tool_calls)


class FakeLLMClient:
    """Scripted turn sequence; records every call for assertions."""

    def __init__(self, turns: list[AssistantTurn] | None = None) -> None:
        self._turns: list[AssistantTurn] = list(turns or [])
        self.calls: list[list[dict[str, Any]]] = []

    def load_script(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        self.calls.append(messages)
        if not self._turns:
            raise AssertionError("FakeLLMClient was called with no scripted turns left")
        if len(self._turns) > 1:
            return self._turns.pop(0)
        return self._turns[0]

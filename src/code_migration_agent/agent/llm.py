"""Optional OpenAI-compatible chat-completions policy. No network in tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..config import LLMConfig, PriceTable
from ..models import FailureClass
from .policy import (
    FIXER_NAMES,
    AgentContext,
    ToolCall,
    ToolName,
)


class LLMError(RuntimeError):
    """Raised when the provider request fails."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    def complete(self, messages: Sequence[dict[str, str]]) -> LLMResponse: ...


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete(self, messages: Sequence[dict[str, str]]) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": list(messages),
            "temperature": 0,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_s
            ) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response missing choices[0].message.content") from exc
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        return LLMResponse(
            text=str(text),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )


class LLMPolicy:
    """Turns model JSON into confined tool calls; malformed output gives up."""

    def __init__(self, client: LLMClient, prices: PriceTable) -> None:
        self.client = client
        self.prices = prices
        self._pending_cost = 0.0
        self._allowed_tools: tuple[ToolName, ...] = (
            "read_file",
            "edit_file",
            "run_build",
            "run_test",
            "git_diff",
            "apply_fixer",
            "give_up",
        )

    def take_cost(self) -> float:
        cost = self._pending_cost
        self._pending_cost = 0.0
        return cost

    def next_action(self, context: AgentContext) -> ToolCall:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Python 2 to Python 3 migration agent. Reply with one "
                    "JSON object only. Never edit tests. Use exact old text for "
                    "edit_file. Prefer apply_fixer. If no safe fix exists, give_up."
                ),
            },
            {"role": "user", "content": self._prompt(context)},
        ]
        try:
            response = self.client.complete(messages)
        except LLMError as exc:
            return ToolCall(
                tool="give_up",
                args={
                    "reason": str(exc),
                    "failure_class": (
                        context.evaluation.failure_class.value
                        if context.evaluation.failure_class
                        else FailureClass.UNCLASSIFIED_FAILURE.value
                    ),
                },
            )
        self._pending_cost += self.prices.cost(
            response.prompt_tokens, response.completion_tokens
        )
        action = self._parse(response.text)
        if action is None:
            return ToolCall(
                tool="give_up",
                args={
                    "reason": "invalid_llm_action",
                    "failure_class": (
                        context.evaluation.failure_class.value
                        if context.evaluation.failure_class
                        else FailureClass.UNCLASSIFIED_FAILURE.value
                    ),
                },
            )
        return action

    def _prompt(self, context: AgentContext) -> str:
        evaluation = context.evaluation
        failure = (
            evaluation.failure_class.value
            if evaluation.failure_class is not None
            else "none"
        )
        lines = [
            "Allowed tools: read_file, edit_file, run_build, run_test, git_diff, "
            "apply_fixer, give_up.",
            "Action schema: {\"tool\": \"apply_fixer\", \"args\": {\"fixer\": "
            "\"cmp_to_key\"}} or {\"tool\": \"edit_file\", \"args\": {\"path\": "
            "\"app/module.py\", \"old\": \"exact text\", \"new\": \"replacement\"}} "
            "or {\"tool\": \"give_up\", \"args\": {\"reason\": \"...\", "
            "\"failure_class\": \"syntax_edge_case\"}}.",
            f"Allowed fixers: {', '.join(FIXER_NAMES)}.",
            f"Failure class: {failure}",
            f"Reason: {evaluation.reason[:2000]}",
            "Files: " + ", ".join(context.files[:80]),
            "History: " + " | ".join(context.history[-8:]),
            "Source excerpt:",
            context.source_excerpt,
            "Diagnostics:",
            context.diagnostics[:4000],
        ]
        return "\n".join(lines)

    def _parse(self, text: str) -> ToolCall | None:
        data: Any = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
        if not isinstance(data, dict):
            return None
        tool = data.get("tool")
        args = data.get("args", {})
        if not isinstance(tool, str) or tool not in self._allowed_tools:
            return None
        if not isinstance(args, dict):
            return None
        typed_tool: ToolName = tool
        if typed_tool == "edit_file":
            if not all(
                isinstance(args.get(key), str) for key in ("path", "old", "new")
            ):
                return None
        elif typed_tool == "apply_fixer":
            if args.get("fixer") not in FIXER_NAMES:
                return None
        elif typed_tool == "read_file":
            if not isinstance(args.get("path"), str):
                return None
        elif typed_tool == "give_up":
            if not isinstance(args.get("reason"), str):
                return None
        return ToolCall(tool=typed_tool, args=dict(args))

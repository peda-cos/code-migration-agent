"""Policy protocol and the offline deterministic diagnostic policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..models import Evaluation, FailureClass

ToolName = Literal[
    "read_file",
    "edit_file",
    "run_build",
    "run_test",
    "git_diff",
    "apply_fixer",
    "give_up",
]

FIXER_NAMES = (
    "functools_reduce",
    "urllib2_request",
    "cmp_to_key",
    "keys_to_list",
    "fix_packaging",
    "commands_shim",
)

_KNOWN_MODULE_MOVES = (
    "urllib2",
    "urlparse",
    "httplib",
    "HTMLParser",
    "ConfigParser",
    "SocketServer",
    "cPickle",
    "cStringIO",
    "StringIO",
    "Queue",
    "copy_reg",
    "thread",
    "repr",
)


@dataclass(frozen=True)
class ToolCall:
    tool: ToolName
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    evaluation: Evaluation
    diagnostics: str
    source_excerpt: str
    files: list[str]
    history: list[str]
    allowed_fixers: list[str]


class Policy(Protocol):
    def next_action(self, context: AgentContext) -> ToolCall: ...

    def take_cost(self) -> float: ...


def _diagnostics(evaluation: Evaluation) -> str:
    parts = [evaluation.reason]
    parts.append(evaluation.build.output)
    if evaluation.tests is not None:
        parts.append(evaluation.tests.output)
    return "\n".join(parts)


class DeterministicPolicy:
    """Maps observable diagnostics to one targeted fixer, else gives up."""

    def __init__(self) -> None:
        self._last_signature: tuple[FailureClass | None, str] | None = None

    def take_cost(self) -> float:
        return 0.0

    def next_action(self, context: AgentContext) -> ToolCall:
        evaluation = context.evaluation
        classification = evaluation.failure_class
        text = context.diagnostics
        history = "\n".join(context.history)
        signature = (classification, evaluation.reason[:240])
        self._last_signature = signature

        if classification in {
            FailureClass.TEST_FLAKE,
            FailureClass.COVERAGE_REGRESSION,
            FailureClass.TEST_INTEGRITY,
            FailureClass.CUSTOM_ANNOTATION,
            FailureClass.BUDGET_EXHAUSTED,
        }:
            return self._give_up(classification, evaluation.reason)

        if evaluation.build.packaging_diagnostics or classification is FailureClass.BUILD_TOOL_DRIFT:
            return self._fix("fix_packaging", history)

        patterns: list[tuple[str, str]] = [
            (r"name 'reduce' is not defined", "functools_reduce"),
            (r"\bcommands\b", "commands_shim"),
            (r"not subscriptable|dict_keys", "keys_to_list"),
            (r"sort\(\) takes no positional|invalid keyword.*cmp|'cmp'", "cmp_to_key"),
        ]
        for pattern, fixer in patterns:
            if re.search(pattern, text):
                return self._fix(fixer, history)

        if classification is FailureClass.DEP_UPGRADE_REQUIRED:
            mentioned = [name for name in _KNOWN_MODULE_MOVES if name in text]
            if mentioned:
                return self._fix("urllib2_request", history)
            return self._give_up(classification, "external dependency unavailable offline")

        if classification is FailureClass.SYNTAX_EDGE_CASE:
            if "__metaclass__" in text:
                return self._give_up(FailureClass.CUSTOM_ANNOTATION, "py2 metaclass")
            return self._give_up(classification, evaluation.reason)

        return self._give_up(classification, evaluation.reason)

    def _fix(self, fixer: str, history: str) -> ToolCall:
        if fixer in history:
            return ToolCall(
                tool="give_up",
                args={
                    "reason": f"fixer {fixer} already applied and failure persists",
                },
            )
        return ToolCall(tool="apply_fixer", args={"fixer": fixer})

    @staticmethod
    def _give_up(classification: FailureClass | None, reason: str) -> ToolCall:
        return ToolCall(
            tool="give_up",
            args={
                "reason": reason,
                "failure_class": (
                    classification.value
                    if classification is not None
                    else FailureClass.UNCLASSIFIED_FAILURE.value
                ),
            },
        )

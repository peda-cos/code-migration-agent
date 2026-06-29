"""Budgeted agent loop: decide, act, re-evaluate, stop on gate or budget."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from ..models import (
    Budgets,
    Evaluation,
    FailureClass,
    LoopResult,
)
from ..runtime.git import GitError
from .policy import AgentContext, Policy, ToolCall
from .tools import ToolBox, ToolError

_NO_AGENT_CLASSES = {
    FailureClass.TEST_FLAKE,
    FailureClass.COVERAGE_REGRESSION,
    FailureClass.TEST_INTEGRITY,
    FailureClass.BUDGET_EXHAUSTED,
    FailureClass.CUSTOM_ANNOTATION,
}
_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_ALT_FILE_RE = re.compile(r"([\w./-]+\.py):(\d+)")


def _source_excerpt(root: Path, text: str) -> str:
    matches = list(_FILE_RE.finditer(text)) or list(_ALT_FILE_RE.finditer(text))
    for match in reversed(matches):
        candidate = Path(match.group(1))
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            line = int(match.group(2))
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            continue
        start = max(0, line - 9)
        end = min(len(lines), line + 8)
        width = len(str(end))
        return "\n".join(
            f"{index + 1:>{width}}: {lines[index]}" for index in range(start, end)
        )
    return ""


def _budget_reason(
    turns: int,
    cost: float,
    elapsed: float,
    budgets: Budgets,
    *,
    check_turns: bool = True,
) -> str | None:
    if check_turns and turns >= budgets.max_turns:
        return f"turn budget exhausted ({turns}/{budgets.max_turns})"
    if elapsed >= budgets.max_seconds:
        return f"wall-clock budget exhausted ({elapsed:.2f}s/{budgets.max_seconds:.0f}s)"
    if cost > budgets.max_cost_usd:
        return f"cost budget exhausted (${cost:.4f}/${budgets.max_cost_usd:.2f})"
    return None


def _failure_from_action(
    action: ToolCall, evaluation: Evaluation
) -> tuple[FailureClass, str]:
    args = action.args
    reason = str(args.get("reason", evaluation.reason or "agent gave up"))
    raw_class = args.get("failure_class")
    if isinstance(raw_class, str):
        try:
            return FailureClass(raw_class), reason
        except ValueError:
            pass
    return (
        evaluation.failure_class or FailureClass.UNCLASSIFIED_FAILURE,
        reason,
    )


def _dispatch(
    toolbox: ToolBox, action: ToolCall
) -> tuple[bool, str, str | None]:
    """Return (changed, observation, fixer_name)."""
    tool = action.tool
    args = action.args
    if tool == "read_file":
        path = args.get("path")
        if not isinstance(path, str):
            raise ToolError("read_file requires a path")
        return False, toolbox.read_file(path), None
    if tool == "edit_file":
        path = args.get("path")
        old = args.get("old")
        new = args.get("new")
        if not (isinstance(path, str) and isinstance(old, str) and isinstance(new, str)):
            raise ToolError("edit_file requires path, old, and new strings")
        result = toolbox.edit_file(path, old, new)
        return result.edits > 0, f"edited {', '.join(result.files)}", "edit_file"
    if tool == "apply_fixer":
        fixer = args.get("fixer")
        if not isinstance(fixer, str):
            raise ToolError("apply_fixer requires a fixer name")
        result = toolbox.apply_fixer(fixer)
        return (
            result.edits > 0,
            f"fixer {fixer}: {result.edits} edits in {', '.join(result.files) or 'no files'}",
            fixer,
        )
    if tool == "run_build":
        build_result = toolbox.run_build()
        return False, "BUILD OK" if build_result.ok else build_result.output, None
    if tool == "run_test":
        test_result = toolbox.run_test()
        return False, test_result.output, None
    if tool == "git_diff":
        return False, toolbox.git_diff()[:4000], None
    if tool == "give_up":
        return False, "", None
    raise ToolError(f"unknown tool: {tool}")


def run_agent(
    toolbox: ToolBox,
    policy: Policy,
    evaluation: Evaluation,
    budgets: Budgets,
    clock: Callable[[], float] = time.monotonic,
) -> LoopResult:
    started = clock()
    turns = 0
    cost = 0.0
    fixes: list[str] = []
    history: list[str] = []
    current = evaluation
    stagnant = 0

    if current.passed:
        return LoopResult(
            outcome="passed",
            failure_class=None,
            reason=current.reason,
            turns=0,
            cost_usd=0.0,
            duration_s=0.0,
            final_evaluation=current,
        )
    if current.failure_class in _NO_AGENT_CLASSES:
        return LoopResult(
            outcome="failed",
            failure_class=current.failure_class,
            reason=current.reason,
            turns=0,
            cost_usd=0.0,
            duration_s=clock() - started,
            final_evaluation=current,
        )

    while True:
        elapsed = clock() - started
        breach = _budget_reason(turns, cost, elapsed, budgets)
        if breach is not None:
            return LoopResult(
                outcome="failed",
                failure_class=FailureClass.BUDGET_EXHAUSTED,
                reason=breach,
                turns=turns,
                cost_usd=cost,
                duration_s=elapsed,
                agent_fixes=fixes,
                final_evaluation=current,
            )

        diagnostics = current.reason
        if current.build.output:
            diagnostics += "\n" + current.build.output
        if current.tests is not None:
            diagnostics += "\n" + current.tests.output
        context = AgentContext(
            evaluation=current,
            diagnostics=diagnostics,
            source_excerpt=_source_excerpt(toolbox.root, diagnostics),
            files=toolbox.list_files(),
            history=history,
            allowed_fixers=[
                "functools_reduce",
                "urllib2_request",
                "cmp_to_key",
                "keys_to_list",
                "fix_packaging",
                "commands_shim",
            ],
        )
        action = policy.next_action(context)
        cost += policy.take_cost()
        if cost > budgets.max_cost_usd:
            return LoopResult(
                outcome="failed",
                failure_class=FailureClass.BUDGET_EXHAUSTED,
                reason=f"cost budget exhausted (${cost:.4f}/${budgets.max_cost_usd:.2f})",
                turns=turns,
                cost_usd=cost,
                duration_s=clock() - started,
                agent_fixes=fixes,
                final_evaluation=current,
            )
        if action.tool == "give_up":
            turns += 1
            failure_class, reason = _failure_from_action(action, current)
            return LoopResult(
                outcome="failed",
                failure_class=failure_class,
                reason=reason,
                turns=turns,
                cost_usd=cost,
                duration_s=clock() - started,
                agent_fixes=fixes,
                final_evaluation=current,
            )

        turns += 1
        changed = False
        fixer: str | None = None
        try:
            changed, observation, fixer = _dispatch(toolbox, action)
        except (ToolError, KeyError, TypeError, ValueError) as exc:
            history.append(f"tool error: {exc}")
        else:
            history.append(
                f"{action.tool}: {observation[:500]}" if observation else action.tool
            )
            if changed and fixer is not None:
                classification = (
                    current.failure_class.value
                    if current.failure_class is not None
                    else "unclassified_failure"
                )
                try:
                    toolbox.commit(f"agent: {fixer} for {classification}")
                except GitError:
                    # A commit failure must not hide the evaluation result; the
                    # evidence bundle still records the turn.
                    history.append("commit failed")
                fixes.append(fixer)

        updated = toolbox.evaluate()
        elapsed = clock() - started
        success_breach = _budget_reason(turns, cost, elapsed, budgets, check_turns=False)
        if updated.passed:
            if success_breach is not None:
                return LoopResult(
                    outcome="failed",
                    failure_class=FailureClass.BUDGET_EXHAUSTED,
                    reason=success_breach,
                    turns=turns,
                    cost_usd=cost,
                    duration_s=elapsed,
                    agent_fixes=fixes,
                    final_evaluation=updated,
                )
            return LoopResult(
                outcome="passed",
                failure_class=None,
                reason=updated.reason,
                turns=turns,
                cost_usd=cost,
                duration_s=elapsed,
                agent_fixes=fixes,
                final_evaluation=updated,
            )
        if updated.failure_class in _NO_AGENT_CLASSES:
            return LoopResult(
                outcome="failed",
                failure_class=updated.failure_class,
                reason=updated.reason,
                turns=turns,
                cost_usd=cost,
                duration_s=elapsed,
                agent_fixes=fixes,
                final_evaluation=updated,
            )

        same = (
            updated.failure_class == current.failure_class
            and updated.reason[:240] == current.reason[:240]
        )
        if same and not changed:
            stagnant += 1
            if stagnant >= 2:
                return LoopResult(
                    outcome="failed",
                    failure_class=(
                        updated.failure_class or FailureClass.UNCLASSIFIED_FAILURE
                    ),
                    reason="no progress after two unchanged turns: " + updated.reason,
                    turns=turns,
                    cost_usd=cost,
                    duration_s=elapsed,
                    agent_fixes=fixes,
                    final_evaluation=updated,
                )
        else:
            stagnant = 0
        current = updated

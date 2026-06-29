from pathlib import Path

from code_migration_agent.agent.loop import run_agent
from code_migration_agent.agent.policy import AgentContext, ToolCall
from code_migration_agent.models import (
    Budgets,
    BuildResult,
    Evaluation,
    FailureClass,
    FixerResult,
    MigrationSpec,
    TestResult,
)


def _evaluation(
    passed: bool = False,
    failure: FailureClass | None = FailureClass.SYNTAX_EDGE_CASE,
    reason: str = "NameError: name 'reduce' is not defined",
) -> Evaluation:
    return Evaluation(
        passed=passed,
        failure_class=failure,
        reason=reason,
        build=BuildResult(True, [], "BUILD OK"),
        tests=TestResult(
            ok=passed, ran=1, failures=0 if passed else 1, output=reason
        ),
    )


class _Policy:
    def __init__(self, actions, cost: float = 0.0) -> None:
        self.actions = list(actions)
        self.cost = cost
        self.calls = 0

    def next_action(self, context: AgentContext) -> ToolCall:
        del context
        self.calls += 1
        if not self.actions:
            return ToolCall("git_diff")
        return self.actions.pop(0)

    def take_cost(self) -> float:
        return self.cost


class _Toolbox:
    def __init__(self, evaluations) -> None:
        self.root = Path(".")
        self.spec = MigrationSpec(name="stub", source=Path("."))
        self.evaluations = list(evaluations)
        self.commits: list[str] = []
        self.fixes: list[str] = []

    def list_files(self) -> list[str]:
        return []

    def git_diff(self) -> str:
        return ""

    def read_file(self, path: str) -> str:
        return ""

    def edit_file(self, path: str, old: str, new: str) -> FixerResult:
        return FixerResult("edit_file", [path], 1)

    def apply_fixer(self, name: str) -> FixerResult:
        self.fixes.append(name)
        return FixerResult(name, ["app/x.py"], 1)

    def commit(self, message: str) -> str:
        self.commits.append(message)
        return "abc123"

    def run_build(self) -> BuildResult:
        return BuildResult(True, [], "BUILD OK")

    def run_test(self) -> TestResult:
        return TestResult(True, 1, 0, "OK")

    def evaluate(self) -> Evaluation:
        if not self.evaluations:
            return _evaluation()
        return self.evaluations.pop(0)


def test_agent_fixer_turn_succeeds_and_commits():
    toolbox = _Toolbox([_evaluation(passed=True, failure=None, reason="ok")])
    policy = _Policy([ToolCall("apply_fixer", {"fixer": "functools_reduce"})])
    result = run_agent(toolbox, policy, _evaluation(), Budgets(max_turns=3))
    assert result.outcome == "passed"
    assert result.turns == 1
    assert result.agent_fixes == ["functools_reduce"]
    assert toolbox.commits and "functools_reduce" in toolbox.commits[0]


def test_turn_budget_halts():
    toolbox = _Toolbox([_evaluation(), _evaluation()])
    policy = _Policy([ToolCall("git_diff"), ToolCall("git_diff")])
    result = run_agent(toolbox, policy, _evaluation(), Budgets(max_turns=1))
    assert result.outcome == "failed"
    assert result.failure_class is FailureClass.BUDGET_EXHAUSTED
    assert result.turns == 1
    assert "turn budget" in result.reason
    assert policy.calls == 1


def test_cost_budget_halts_before_action():
    toolbox = _Toolbox([_evaluation()])
    policy = _Policy([ToolCall("git_diff")], cost=5.0)
    result = run_agent(
        toolbox, policy, _evaluation(), Budgets(max_turns=5, max_cost_usd=1.0)
    )
    assert result.failure_class is FailureClass.BUDGET_EXHAUSTED
    assert "cost budget" in result.reason
    assert result.turns == 0
    assert not toolbox.commits


def test_wall_clock_budget_halts():
    ticks = iter([0.0, 0.0, 50.0, 100.0])
    toolbox = _Toolbox([_evaluation()])
    policy = _Policy([ToolCall("git_diff")])
    result = run_agent(
        toolbox,
        policy,
        _evaluation(),
        Budgets(max_turns=10, max_seconds=10.0),
        clock=lambda: next(ticks),
    )
    assert result.failure_class is FailureClass.BUDGET_EXHAUSTED
    assert "wall-clock" in result.reason


def test_give_up_preserves_policy_class():
    toolbox = _Toolbox([])
    policy = _Policy(
        [
            ToolCall(
                "give_up",
                {"reason": "needs a dependency", "failure_class": "dep_upgrade_required"},
            )
        ]
    )
    result = run_agent(toolbox, policy, _evaluation(), Budgets(max_turns=3))
    assert result.failure_class is FailureClass.DEP_UPGRADE_REQUIRED
    assert "dependency" in result.reason
    assert result.turns == 1


def test_no_progress_stops_after_two_turns():
    toolbox = _Toolbox([_evaluation(), _evaluation(), _evaluation()])
    policy = _Policy([ToolCall("git_diff"), ToolCall("git_diff")])
    result = run_agent(toolbox, policy, _evaluation(), Budgets(max_turns=10))
    assert result.failure_class is FailureClass.SYNTAX_EDGE_CASE
    assert "no progress" in result.reason
    assert result.turns == 2


def test_fatal_class_skips_agent_turns():
    toolbox = _Toolbox([])
    policy = _Policy([ToolCall("git_diff")])
    result = run_agent(
        toolbox,
        policy,
        _evaluation(failure=FailureClass.COVERAGE_REGRESSION),
        Budgets(),
    )
    assert result.failure_class is FailureClass.COVERAGE_REGRESSION
    assert result.turns == 0
    assert policy.calls == 0

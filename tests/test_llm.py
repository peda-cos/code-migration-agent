import pytest

from code_migration_agent.agent.llm import LLMError, LLMPolicy, LLMResponse
from code_migration_agent.agent.policy import AgentContext
from code_migration_agent.config import LLMConfig, LLMConfigurationError, PriceTable
from code_migration_agent.models import BuildResult, Evaluation, FailureClass, TestResult


class _Client:
    def __init__(self, response: LLMResponse | Exception) -> None:
        self.response = response
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _context() -> AgentContext:
    evaluation = Evaluation(
        passed=False,
        failure_class=FailureClass.SYNTAX_EDGE_CASE,
        reason="TypeError: sort() takes no positional arguments",
        build=BuildResult(True, [], "BUILD OK"),
        tests=TestResult(False, 1, 1, "TypeError: sort()"),
    )
    return AgentContext(
        evaluation=evaluation,
        diagnostics="TypeError: sort() takes no positional arguments",
        source_excerpt="3: result.sort(cmp=f)",
        files=["app/order.py"],
        history=[],
        allowed_fixers=["cmp_to_key"],
    )


def test_llm_policy_parses_action_and_accounts_cost():
    client = _Client(
        LLMResponse(
            '{"tool": "apply_fixer", "args": {"fixer": "cmp_to_key"}}',
            prompt_tokens=1000,
            completion_tokens=500,
        )
    )
    policy = LLMPolicy(client, PriceTable(input_per_mtok=3.0, output_per_mtok=15.0))
    action = policy.next_action(_context())
    assert action.tool == "apply_fixer"
    assert action.args == {"fixer": "cmp_to_key"}
    assert policy.take_cost() == pytest.approx(0.0105)
    assert policy.take_cost() == 0.0
    assert client.messages is not None
    assert "Never edit tests" in client.messages[0]["content"]


def test_llm_policy_rejects_malformed_action():
    policy = LLMPolicy(_Client(LLMResponse("not json", 1, 1)), PriceTable())
    action = policy.next_action(_context())
    assert action.tool == "give_up"
    assert action.args["reason"] == "invalid_llm_action"
    assert action.args["failure_class"] == "syntax_edge_case"


def test_llm_policy_rejects_unknown_fixer():
    policy = LLMPolicy(
        _Client(LLMResponse('{"tool": "apply_fixer", "args": {"fixer": "rm_rf"}}')),
        PriceTable(),
    )
    assert policy.next_action(_context()).tool == "give_up"


def test_llm_error_becomes_give_up():
    policy = LLMPolicy(_Client(LLMError("offline")), PriceTable())
    action = policy.next_action(_context())
    assert action.tool == "give_up"
    assert "offline" in action.args["reason"]


def test_llm_config_requires_env(monkeypatch):
    for name in ("CMA_LLM_BASE_URL", "CMA_LLM_API_KEY", "CMA_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LLMConfigurationError):
        LLMConfig.from_env()

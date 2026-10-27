import pytest
from smolagents import Model
from smolagents.models import ChatMessage, MessageRole

from fridge.agent import run_agent
from fridge.errors import AgentFailure
from fridge.planner import DinnerRequest


class ScriptedModel(Model):
    """A deterministic test model. Runs real CodeAgent/tools, no remote inference."""
    def generate(self, messages, **kwargs):
        return ChatMessage(role=MessageRole.ASSISTANT, content='''
<code>
recipes = find_recipes()
ids = [r["id"] for r in recipes]
assert "tomato-eggs" in ids and "cabbage" in ids
check = evaluate_menu(["tomato-eggs", "cabbage"])
assert check["valid"]
final_answer({"recipe_ids": ["tomato-eggs", "cabbage"]})
</code>
''')


def test_real_code_agent_executes_tools_and_produces_auditable_code():
    request = DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"], mode="agent")
    result = run_agent(request, model=ScriptedModel())
    assert result["mode"] == "agent"
    assert result["plan"]["shopping"] == []
    assert {t.get("tool") for t in result["trace"]} >= {"find_recipes", "evaluate_menu"}
    assert any("evaluate_menu" in t.get("code", "") for t in result["trace"])


class InventingModel(Model):
    def generate(self, messages, **kwargs):
        return ChatMessage(role=MessageRole.ASSISTANT, content='<code>final_answer({"recipe_ids": ["invented", "cabbage"]})</code>')


def test_model_cannot_bypass_application_validation():
    with pytest.raises(AgentFailure) as error:
        run_agent(DinnerRequest(ingredients=["白菜"]), model=InventingModel())
    assert error.value.code == "menu_incomplete"


class CorrectingModel(ScriptedModel):
    calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ChatMessage(role=MessageRole.ASSISTANT, content=(
                '<code>final_answer({"recipe_ids": ["tomato-eggs", "cabbage"]})</code>'))
        return super().generate(messages, **kwargs)


def test_agent_retries_when_valid_ids_skip_required_tools():
    model = CorrectingModel()
    result = run_agent(DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"]), model=model)
    assert model.calls == 2
    assert result["mode"] == "agent"
    assert any("未成功" in t.get("detail", "") for t in result["trace"])


@pytest.mark.parametrize("base,deepseek", [
    ("https://api.deepseek.com", True),
    ("https://api.deepseek.com/v1", True),
    ("https://api.deepseek.com.attacker.invalid", False),
    ("https://example.invalid/v1", False),
])
def test_deepseek_options_are_scoped_to_provider(monkeypatch, base, deepseek):
    from fridge import agent
    monkeypatch.setenv("MODEL_API_KEY", "fake-test-key")
    monkeypatch.setenv("MODEL_BASE_URL", base)
    monkeypatch.setenv("MODEL_ID", "deepseek-flash")
    monkeypatch.setattr(agent, "OpenAIModel", lambda **kwargs: kwargs)
    options = agent.create_model()
    assert options["client_kwargs"]["max_retries"] == 0
    assert ("extra_body" in options) == deepseek
    if deepseek:
        assert options["extra_body"] == {"thinking": {"type": "disabled"}}


def test_live_check_does_not_call_provider_without_key(monkeypatch, capsys):
    from fridge import check_agent
    monkeypatch.setattr(check_agent, "model_ready", lambda: False)
    monkeypatch.setattr(check_agent.server, "isolated_agent", lambda _: pytest.fail("Unexpected call"))
    assert check_agent.main() == 1
    assert "未开始" in capsys.readouterr().out


def test_live_check_never_prints_provider_secrets(monkeypatch, capsys):
    from fridge import check_agent
    monkeypatch.setattr(check_agent, "model_ready", lambda: True)
    def fail(_):
        raise RuntimeError("private-key-from-provider")
    monkeypatch.setattr(check_agent.server, "isolated_agent", fail)
    assert check_agent.main() == 1
    assert "private-key" not in capsys.readouterr().out


def test_deepseek_request_runs_through_real_sdk_without_network(monkeypatch):
    import httpx
    import json
    from fridge import agent
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": ScriptedModel().generate([]).content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    monkeypatch.setenv("MODEL_API_KEY", "fake-test-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MODEL_ID", "deepseek-flash")
    model = agent.create_model()
    model.client.close()
    from openai import OpenAI
    model.client = OpenAI(api_key="fake-test-key", base_url="https://api.deepseek.com",
                          http_client=httpx.Client(transport=httpx.MockTransport(respond)), max_retries=0)
    try:
        result = run_agent(DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"]), model=model)
    finally:
        model.client.close()
    assert result["mode"] == "agent"
    assert len(captured) == 1
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["model"] == "deepseek-flash"


def test_successful_check_for_another_pair_does_not_validate_final_pair():
    class SwitchingModel(ScriptedModel):
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChatMessage(role=MessageRole.ASSISTANT, content='''<code>
find_recipes()
evaluate_menu(["tomato-eggs", "cabbage"])
final_answer({"recipe_ids": ["tomato-soup", "cabbage"]})
</code>''')
            return super().generate(messages, **kwargs)

    model = SwitchingModel()
    result = run_agent(DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"]), model=model)
    assert model.calls == 2
    assert {d["id"] for d in result["plan"]["dishes"]} == {"tomato-eggs", "cabbage"}


class UnfinishedModel(Model):
    """Models a run that evaluates a menu but exhausts steps before final_answer."""
    def __init__(self, lookup=True, valid=True):
        super().__init__()
        self.calls = 0
        self.lookup = lookup
        self.valid = valid

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls > 6:
            return ChatMessage(role=MessageRole.ASSISTANT, content="这次菜单尚未完成最终回答。")
        lookup = "find_recipes()" if self.lookup else ""
        ids = '["tomato-eggs", "cabbage"]' if self.valid else '["invented", "cabbage"]'
        return ChatMessage(role=MessageRole.ASSISTANT,
                           content=f'<code>\n{lookup}\nevaluate_menu({ids})\n</code>')


def test_step_limit_recovers_only_the_pair_really_evaluated_this_run():
    model = UnfinishedModel()
    result = run_agent(DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"]), model=model)
    assert model.calls == 7
    assert result["mode"] == "agent"
    assert {d["id"] for d in result["plan"]["dishes"]} == {"tomato-eggs", "cabbage"}
    assert not result["plan"]["shopping"]
    assert any(t["kind"] == "recovery" for t in result["trace"])
    assert result["trace"][-1]["kind"] == "validation"


@pytest.mark.parametrize("lookup,valid", [(False, True), (True, False)])
def test_step_limit_never_fabricates_success_without_lookup_and_valid_evaluation(lookup, valid):
    with pytest.raises(AgentFailure) as error:
        run_agent(DinnerRequest(ingredients=["鸡蛋", "番茄", "白菜"]),
                  model=UnfinishedModel(lookup=lookup, valid=valid))
    assert error.value.code == "menu_incomplete"
    assert error.value.diagnostics["steps"] == 6
    assert error.value.diagnostics["evaluated"] == (1 if valid else 0)


def test_provider_connection_failure_keeps_its_category_through_code_agent():
    import httpx
    from openai import APIConnectionError

    class DisconnectedModel(Model):
        def generate(self, messages, **kwargs):
            raise APIConnectionError(message="secret-provider-message",
                                     request=httpx.Request("POST", "https://example.invalid"))

    with pytest.raises(AgentFailure) as error:
        run_agent(DinnerRequest(ingredients=["鸡蛋"]), model=DisconnectedModel())
    assert error.value.code == "model_connection"
    assert "secret-provider" not in str(error.value)


def test_explicit_empty_menu_is_not_reported_as_authentication_failure():
    class EmptyModel(Model):
        calls = 0
        def generate(self, messages, **kwargs):
            self.calls += 1
            content = ('<code>find_recipes(); final_answer({"recipe_ids": []})</code>'
                       if self.calls <= 6 else '{"recipe_ids": []}')
            return ChatMessage(role=MessageRole.ASSISTANT, content=content)

    with pytest.raises(AgentFailure) as error:
        run_agent(DinnerRequest(ingredients=["鸡蛋"], minutes=15), model=EmptyModel())
    assert error.value.code == "menu_unavailable"

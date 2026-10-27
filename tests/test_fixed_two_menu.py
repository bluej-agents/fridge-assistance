"""Menus must only return complete two-dish meals."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from smolagents import Model
from smolagents.models import ChatMessage, MessageRole

from fridge import server
from fridge.agent import run_agent
from fridge.errors import AgentFailure
from fridge.planner import DinnerRequest, build_plan, demo_plan


STOCK = ["鸡蛋", "番茄", "白菜", "土豆", "黄瓜"]
PAIR = ["tomato-eggs", "cabbage"]
WRONG_MENUS = [["cabbage"], [*PAIR, "potato"], [*PAIR, "potato", "tomato-soup"]]


class FixedCodeModel(Model):
    """Exercise the actual CodeAgent and tools; no model provider is contacted."""
    def __init__(self, code, unfinished_ids=None):
        super().__init__()
        self.code = code
        self.unfinished_ids = unfinished_ids
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        content = (json.dumps({"recipe_ids": self.unfinished_ids})
                   if self.unfinished_ids is not None and self.calls > 6
                   else f"<code>\n{self.code}\n</code>")
        return ChatMessage(role=MessageRole.ASSISTANT, content=content)


def request(**changes):
    return DinnerRequest(**dict({"ingredients": STOCK, "people": 2, "minutes": 60,
                                 "vegetarian": True}, **changes))


def draft(name, food, people):
    return {"name": name, "minutes": 10, "vegetarian": True,
            "ingredients": [{"name": food, "amount": 100*people, "unit": "克"}],
            "staples": ["盐", "食用油"],
            "steps": ["清洗并准备食材。", "将食材炒至熟透后调味。"]}


@pytest.mark.parametrize("people", range(1, 7))
def test_demo_always_returns_two_dishes_for_every_supported_party_size(people):
    result = demo_plan(request(people=people))
    assert result["mode"] == "demo"
    assert result["plan"]["people"] == people
    assert len(result["plan"]["dishes"]) == 2
    assert len({dish["id"] for dish in result["plan"]["dishes"]}) == 2


@pytest.mark.parametrize("people", range(1, 7))
def test_code_agent_composes_exactly_two_for_every_supported_party_size(people):
    dishes = [draft("家常番茄", "番茄", people), draft("家常白菜", "白菜", people)]
    result = run_agent(request(people=people, mode="agent"), model=FixedCodeModel(f"""
find_recipes()
menu = compose_menu(dishes={dishes!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    assert result["mode"] == "agent"
    assert result["plan"]["people"] == people
    assert len(result["plan"]["dishes"]) == 2
    assert len([event for event in result["trace"] if event.get("tool") == "compose_menu"]) == 1


@pytest.mark.parametrize("ids", WRONG_MENUS)
def test_application_validation_rejects_one_three_or_four_dishes(ids):
    with pytest.raises(ValueError, match="两道"):
        build_plan(request(), ids)


@pytest.mark.parametrize("count", [1, 3, 4])
def test_compose_and_evaluate_tools_reject_wrong_count_before_correct_pair(count):
    all_dishes = [draft("家常" + food, food, 2) for food in STOCK[:4]]
    wrong_ids = WRONG_MENUS[[1, 3, 4].index(count)]
    result = run_agent(request(mode="agent"), model=FixedCodeModel(f"""
find_recipes()
assert not compose_menu(dishes={all_dishes[:count]!r})['valid']
assert not evaluate_menu({wrong_ids!r})['valid']
menu = compose_menu(dishes={all_dishes[:2]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    assert len(result["plan"]["dishes"]) == 2
    assert [event["result"]["valid"] for event in result["trace"]
            if event.get("tool") == "compose_menu"] == [False, True]


@pytest.mark.parametrize("extra", [{"menu_count": 3}, {"replace_index": 0},
                                   {"keep_recipes": []},
                                   {"menu_count": 1, "replace_index": 0, "keep_recipes": []}])
def test_api_does_not_accept_adaptive_menu_controls(monkeypatch, extra):
    def unexpected(*args, **kwargs):
        pytest.fail("Adaptive payloads must be rejected before model access")
    monkeypatch.setattr("fridge.agent.model_ready", unexpected)
    monkeypatch.setattr(server, "isolated_agent", unexpected)
    payload = dict(request(mode="agent").model_dump(), **extra)
    response = TestClient(server.app, base_url="http://127.0.0.1").post("/api/plan", json=payload)
    assert response.status_code == 422
    assert "plan" not in response.json()


def test_short_demo_request_fails_instead_of_returning_only_one_dish():
    payload = request(minutes=15).model_dump()
    response = TestClient(server.app, base_url="http://127.0.0.1").post("/api/plan", json=payload)
    assert response.status_code == 422
    assert "plan" not in response.json()


@pytest.mark.parametrize("wrong_ids", WRONG_MENUS)
def test_wrong_size_final_answer_without_valid_pair_never_recovers(wrong_ids):
    model = FixedCodeModel(f"""
find_recipes()
assert not evaluate_menu({wrong_ids!r})['valid']
final_answer({{'recipe_ids': {wrong_ids!r}}})
""", unfinished_ids=wrong_ids)
    with pytest.raises(AgentFailure) as error:
        run_agent(request(mode="agent"), model=model)
    assert error.value.code == "menu_incomplete"
    assert error.value.diagnostics["evaluated"] == 0


@pytest.mark.parametrize("wrong_ids", WRONG_MENUS)
def test_recovery_during_replacement_keeps_two_and_the_complete_other_dish(wrong_ids):
    req = request(people=6, mode="agent")
    original = build_plan(req, PAIR)
    kept = original["dishes"][1]
    snapshot = {key: deepcopy(kept[key]) for key in ("id", "name", "minutes", "vegetarian", "staples", "steps")}
    snapshot["ingredients"] = [{key: item[key] for key in ("name", "amount", "unit")}
                               for item in kept["ingredients"]]
    snapshot["servings"] = req.people
    swap = DinnerRequest(**dict(req.model_dump(), keep_recipe=snapshot, keep_index=1,
                                exclude_ids=[PAIR[0]], exclude_names=[original["dishes"][0]["name"]]))
    replacement = draft("新做法番茄", "番茄", req.people)
    result = run_agent(swap, model=FixedCodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[replacement]!r})
assert menu['valid']
""", unfinished_ids=wrong_ids))
    assert len(result["plan"]["dishes"]) == 2
    assert result["plan"]["dishes"][1] == kept
    assert result["plan"]["dishes"][0]["id"] != PAIR[0]
    assert any(event["kind"] == "recovery" for event in result["trace"])

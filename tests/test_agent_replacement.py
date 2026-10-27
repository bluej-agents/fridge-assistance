import copy

import pytest
from smolagents import Model
from smolagents.models import ChatMessage, MessageRole

from fridge.agent import run_agent
from fridge.errors import AgentFailure
from fridge.planner import DinnerRequest, RECIPES, build_plan


PORK = {"name": "蒜苔炒五花肉", "minutes": 18, "vegetarian": False,
        "ingredients": [{"name": "五花肉", "amount": 200, "unit": "克"},
                        {"name": "蒜苔", "amount": 200, "unit": "克"}],
        "staples": ["食用油", "盐"], "steps": ["将食材洗净切好。", "将肉炒至熟透，再炒熟蒜苔。"]}
LOOFAH = {"name": "清炒丝瓜", "minutes": 10, "vegetarian": True,
          "ingredients": [{"name": "丝瓜", "amount": 350, "unit": "克"}],
          "staples": ["食用油", "盐"], "steps": ["丝瓜洗净去皮切块。", "炒至熟透后调味。"]}


class CodeModel(Model):
    def __init__(self, code, unfinished=False):
        super().__init__()
        self.code = code
        self.unfinished = unfinished
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        text = ("菜单最后回答未完成。" if self.unfinished and self.calls > 6
                else f"<code>\n{self.code}\n</code>")
        return ChatMessage(role=MessageRole.ASSISTANT, content=text)


def request(**changes):
    return DinnerRequest(**dict({"ingredients": ["五花肉", "蒜苔", "丝瓜"],
                                 "people": 2, "minutes": 30, "mode": "agent"}, **changes))


def initial(req):
    return run_agent(req, model=CodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[PORK, LOOFAH]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))


def replacement_request(req, result, keep_index, excluded=True):
    kept = result["plan"]["dishes"][keep_index]
    snapshot = {k: copy.deepcopy(kept[k]) for k in ("id", "name", "minutes", "vegetarian", "staples", "steps")}
    snapshot["ingredients"] = [{k: item[k] for k in ("name", "amount", "unit")} for item in kept["ingredients"]]
    snapshot["servings"] = result["plan"]["people"]
    removed = result["plan"]["dishes"][1-keep_index]
    return DinnerRequest(**dict(req.model_dump(), keep_recipe=snapshot, keep_index=keep_index,
                                exclude_ids=[removed["id"]] if excluded else [],
                                exclude_names=[removed["name"]] if excluded else []))


@pytest.mark.parametrize("keep_index,people", [(0, 2), (1, 4)])
def test_one_draft_replaces_only_clicked_slot_and_keeps_complete_generated_recipe(keep_index, people):
    req = request(people=people)
    first = initial(req)
    changed = replacement_request(req, first, keep_index)
    new_draft = dict(LOOFAH, name="丝瓜汤") if keep_index == 0 else dict(PORK, name="蒜苔炒肉片", minutes=15)
    result = run_agent(changed, model=CodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[new_draft]!r})
assert menu['valid']
final_answer({{'recipe_ids': list(reversed(menu['recipe_ids']))}})
"""))
    assert result["plan"]["dishes"][keep_index] == first["plan"]["dishes"][keep_index]
    assert result["plan"]["dishes"][1-keep_index]["id"] != first["plan"]["dishes"][1-keep_index]["id"]
    assert result["plan"]["minutes"] <= req.minutes
    assert not result["plan"]["shopping"]
    assert result["trace"][0]["kind"] == "retained"
    assert result["trace"][0]["recipe_id"] == first["plan"]["dishes"][keep_index]["id"]


def test_replacing_left_then_right_preserves_the_latest_other_dish():
    req = request()
    first = initial(req)
    second = run_agent(replacement_request(req, first, 1), model=CodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[dict(PORK, name='蒜苔炒肉片', minutes=15)]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    third = run_agent(replacement_request(req, second, 0), model=CodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[dict(LOOFAH, name='丝瓜汤')]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    assert second["plan"]["dishes"][1] == first["plan"]["dishes"][1]
    assert third["plan"]["dishes"][0] == second["plan"]["dishes"][0]
    assert third["plan"]["minutes"] == 25


@pytest.mark.parametrize("bad", [
    [PORK, LOOFAH],  # Cannot resubmit the complete pair during a single-dish replacement.
    [dict(PORK, name="蒜苔炒肉片", minutes=25)],  # Insufficient time with the retained dish.
    [LOOFAH],  # Cannot return the retained dish twice.
    [PORK],  # The replaced name and ID remain excluded.
])
def test_rejected_single_replacement_does_not_poison_corrected_atomic_retry(bad):
    req = request()
    first = initial(req)
    corrected = dict(PORK, name="蒜苔炒肉片", minutes=15)
    result = run_agent(replacement_request(req, first, 1), model=CodeModel(f"""
find_recipes()
bad = compose_menu(dishes={bad!r})
assert not bad['valid']
menu = compose_menu(dishes={[corrected]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    assert result["plan"]["dishes"][1] == first["plan"]["dishes"][1]
    assert result["plan"]["minutes"] == 25
    assert [e["result"]["valid"] for e in result["trace"] if e.get("tool") == "compose_menu"] == [False, True]


def test_model_cannot_replace_both_dishes_or_recover_an_unrelated_pair():
    req = request(ingredients=["五花肉", "蒜苔", "丝瓜", "番茄", "鸡蛋", "白菜"], minutes=45)
    first = initial(req)
    with pytest.raises(AgentFailure) as error:
        run_agent(replacement_request(req, first, 1), model=CodeModel("""
find_recipes()
check = evaluate_menu(['tomato-eggs', 'cabbage'])
assert not check['valid']
final_answer({'recipe_ids': ['tomato-eggs', 'cabbage']})
"""))
    assert error.value.code == "menu_incomplete"
    assert error.value.diagnostics["evaluated"] == 0


def test_mutating_tool_results_does_not_change_canonical_retained_recipe():
    req = request(ingredients=["番茄", "鸡蛋", "白菜", "丝瓜"], people=4)
    first = {"plan": build_plan(req, ["cabbage", "tomato-eggs"])}
    changed = replacement_request(req, first, 0)
    original_book = copy.deepcopy(RECIPES)
    result = run_agent(changed, model=CodeModel(f"""
references = find_recipes()
for recipe in references:
    if recipe['id'] == 'cabbage':
        recipe['ingredients'][0]['amount'] = 9999
        recipe['steps'][0] = '篡改参考返回值'
menu = compose_menu(dishes={[LOOFAH]!r})
assert menu['valid']
menu['plan']['dishes'][0]['ingredients'][0]['amount'] = 9999
menu['plan']['dishes'][0]['steps'][0] = '篡改菜单返回值'
final_answer({{'recipe_ids': menu['recipe_ids']}})
"""))
    assert result["plan"]["dishes"][0] == first["plan"]["dishes"][0]
    assert RECIPES == original_book


def test_step_limit_recovery_still_preserves_the_locked_slot():
    req = request()
    first = initial(req)
    model = CodeModel(f"""
find_recipes()
menu = compose_menu(dishes={[dict(PORK, name='蒜苔炒肉片', minutes=15)]!r})
assert menu['valid']
""", unfinished=True)
    result = run_agent(replacement_request(req, first, 1), model=model)
    assert result["plan"]["dishes"][1] == first["plan"]["dishes"][1]
    assert any(t["kind"] == "recovery" for t in result["trace"])

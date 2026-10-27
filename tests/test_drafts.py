import copy

import pytest

from fridge.drafts import validate_draft
from fridge.planner import DinnerRequest, build_plan, demo_plan


PORK = {"name": "蒜苔炒五花肉", "minutes": 18, "vegetarian": False,
        "ingredients": [{"name": "五花肉", "amount": 200, "unit": "克"},
                        {"name": "蒜苔", "amount": 200, "unit": "克"}],
        "staples": ["食用油", "盐", "生抽"],
        "steps": ["五花肉切薄片，蒜苔洗净切段。", "将肉片炒至熟透，再加入蒜苔炒熟，调味。"]}
LOOFAH = {"name": "清炒丝瓜", "minutes": 10, "vegetarian": True,
          "ingredients": [{"name": "丝瓜", "amount": 350, "unit": "克"}],
          "staples": ["食用油", "盐", "水"],
          "steps": ["丝瓜洗净去皮切块。", "锅中热油加入丝瓜，少量水炒至熟透，加盐。"]}


def request(**changes):
    return DinnerRequest(**dict({"ingredients": ["五花肉", "蒜苔", "丝瓜"],
                                 "mode": "agent", "people": 2, "minutes": 30}, **changes))


def test_user_reported_stock_can_form_a_valid_generated_menu():
    req = request()
    dishes = [validate_draft(recipe, req) for recipe in [PORK, LOOFAH]]
    plan = build_plan(req, [r["id"] for r in dishes], dishes)
    assert set(plan["used"]) == set(req.ingredients)
    assert not plan["shopping"]
    assert plan["minutes"] == 28
    assert all("AI" in d["source"] for d in plan["dishes"])


def test_unrelated_cabbage_no_longer_passes_with_only_potato_matching():
    req = request(ingredients=["五花肉", "蒜苔", "土豆", "丝瓜"])
    with pytest.raises(ValueError):
        build_plan(req, ["cabbage", "potato"])
    with pytest.raises(ValueError):
        demo_plan(req.model_copy(update={"mode": "demo"}))


@pytest.mark.parametrize("edit", [
    {"ingredients": [{"name": "白菜", "amount": 350, "unit": "克"}]},
    {"staples": ["五花肉"]},
    {"minutes": 40}, {"minutes": 0}, {"steps": ["炒一下"]},
    {"ingredients": [{"name": "丝瓜", "amount": -1, "unit": "克"}]},
    {"ingredients": [{"name": "丝瓜", "amount": float("nan"), "unit": "克"}]},
    {"ingredients": [{"name": "丝瓜", "amount": 1, "unit": "随便"}]},
])
def test_bad_generated_recipes_are_rejected(edit):
    with pytest.raises(ValueError):
        validate_draft(dict(LOOFAH, **edit), request())


def test_vegetarian_constraint_cannot_be_bypassed_with_meat_flag():
    with pytest.raises(ValueError):
        validate_draft(PORK, request(vegetarian=True))
    with pytest.raises(ValueError):
        validate_draft(dict(PORK, vegetarian=True), request(vegetarian=True))


def test_generated_exclusion_survives_a_new_request():
    draft = validate_draft(LOOFAH, request())
    changed = request(exclude_ids=[draft["id"]], exclude_names=[draft["name"]])
    with pytest.raises(ValueError):
        validate_draft(LOOFAH, changed)


def test_generated_pair_total_time_is_checked_independently():
    req = request()
    drafts = [validate_draft(dict(PORK, minutes=25), req), validate_draft(LOOFAH, req)]
    with pytest.raises(ValueError, match="总时间"):
        build_plan(req, [r["id"] for r in drafts], drafts)


def test_draft_quantities_are_for_requested_people_without_double_scaling():
    req = request(people=4)
    recipes = [validate_draft(PORK, req), validate_draft(LOOFAH, req)]
    plan = build_plan(req, [r["id"] for r in recipes], recipes)
    assert next(i["amount"] for i in plan["stock_check"] if i["name"] == "丝瓜") == 350


def test_real_code_agent_can_register_and_evaluate_new_recipes():
    from smolagents import Model
    from smolagents.models import ChatMessage, MessageRole
    from fridge.agent import run_agent

    class DraftModel(Model):
        def generate(self, messages, **kwargs):
            code = f'''<code>
find_recipes()
a = draft_recipe({PORK!r})
b = draft_recipe({LOOFAH!r})
assert a['valid'] and b['valid']
ids = [a['recipe']['id'], b['recipe']['id']]
assert evaluate_menu(ids)['valid']
final_answer({{'recipe_ids': ids}})
</code>'''
            return ChatMessage(role=MessageRole.ASSISTANT, content=code)

    original = copy.deepcopy(PORK)
    result = run_agent(request(), model=DraftModel())
    assert set(result["plan"]["used"]) == {"五花肉", "蒜苔", "丝瓜"}
    assert sum(t.get("tool") == "draft_recipe" for t in result["trace"]) == 2
    assert PORK == original


def run_menu_script(code, req=None):
    from smolagents import Model
    from smolagents.models import ChatMessage, MessageRole
    from fridge.agent import run_agent

    class MenuModel(Model):
        def generate(self, messages, **kwargs):
            return ChatMessage(role=MessageRole.ASSISTANT, content=f"<code>\n{code}\n</code>")

    return run_agent(req or request(), model=MenuModel())


def test_complete_pair_can_be_submitted_evaluated_and_finished_in_one_step():
    result = run_menu_script(f'''
find_recipes()
menu = compose_menu(dishes={[PORK, LOOFAH]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
''')
    assert result["mode"] == "agent"
    assert set(result["plan"]["used"]) == {"五花肉", "蒜苔", "丝瓜"}
    tools = [t.get("tool") for t in result["trace"] if t.get("tool")]
    assert tools == ["find_recipes", "evaluate_menu", "compose_menu"]
    assert len([t for t in result["trace"] if t["kind"] == "code"]) == 1


@pytest.mark.parametrize("bad_pair", [
    [PORK, dict(LOOFAH, staples=["蒜"])],
    [dict(PORK, minutes=25), LOOFAH],
    [PORK, dict(LOOFAH, ingredients=[{"name": "白菜", "amount": 350, "unit": "克"}])],
    [PORK, dict(LOOFAH, steps=["炒一下"])],
])
def test_rejected_pair_does_not_register_partial_recipes_or_block_corrected_retry(bad_pair):
    corrected = dict(PORK, minutes=17)
    result = run_menu_script(f'''
find_recipes()
failed = compose_menu(dishes={bad_pair!r})
assert not failed['valid']
menu = compose_menu(dishes={[corrected, LOOFAH]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
''')
    submissions = [t for t in result["trace"] if t.get("tool") == "compose_menu"]
    assert [t["result"]["valid"] for t in submissions] == [False, True]
    assert result["plan"]["minutes"] == 27
    assert not result["plan"]["shopping"]


def test_repeated_identical_draft_is_idempotent_and_reusable_by_complete_pair():
    result = run_menu_script(f'''
find_recipes()
for i in range(14):
    draft = draft_recipe({PORK!r})
    assert draft['valid']
menu = compose_menu(dishes={[PORK, LOOFAH]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
''')
    assert len(result["plan"]["dishes"]) == 2
    assert result["plan"]["minutes"] == 28


def test_complete_pair_cannot_bypass_excluded_name_or_duplicate_dish_check():
    alternative = dict(LOOFAH, name="丝瓜汤")
    result = run_menu_script(f'''
find_recipes()
excluded = compose_menu(dishes={[PORK, LOOFAH]!r})
assert not excluded['valid']
duplicate = compose_menu(dishes={[PORK, PORK]!r})
assert not duplicate['valid']
menu = compose_menu(dishes={[PORK, alternative]!r})
assert menu['valid']
final_answer({{'recipe_ids': menu['recipe_ids']}})
''', request(exclude_names=[LOOFAH["name"]]))
    assert LOOFAH["name"] not in [r["name"] for r in result["plan"]["dishes"]]
